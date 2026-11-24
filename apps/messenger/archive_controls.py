"""Account-scoped, explicit and atomic chat-list operations."""
import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import views
from .models import ChatFolder, ChatParticipant
from .folder_rules import MAX_CHATS, requested_folder
from .ratelimit import rate_limit
from .services import set_membership_archived, set_membership_pinned

MAX_SELECTION = 200
ACTIONS = {"archive", "unarchive", "pin", "unpin", "mute", "unmute",
           "mark_read", "mark_unread", "move_up", "move_down"}
MUTE_DURATIONS = {"1h": timedelta(hours=1), "8h": timedelta(hours=8),
                  "2d": timedelta(days=2), "forever": None}


def _error(message, status=400):
    return JsonResponse({"ok": False, "error": message}, status=status)


def _ids(raw):
    try:
        items = json.loads(raw)
        if not isinstance(items, list) or not 1 <= len(items) <= MAX_SELECTION:
            raise ValueError
        if any(type(item) is not int or not 0 < item <= 9223372036854775807 for item in items):
            raise ValueError
        return set(items)
    except (ValueError, TypeError, OverflowError):
        raise ValueError("Выберите от 1 до 200 чатов.") from None


def _reorder(membership, action):
    # Lock all pins in the folder and normalize rank values after swapping.
    # The user lock serializes rank allocation and reorder across tabs.
    pins = list(ChatParticipant.objects.select_for_update().filter(
        user_id=membership.user_id, is_archived=membership.is_archived,
        is_hidden=False, is_pinned=True,
    ).order_by("-pin_order", "-pk"))
    index = next((i for i, row in enumerate(pins) if row.pk == membership.pk), -1)
    if index < 0:
        return False
    other = index + (-1 if action == "move_up" else 1)
    if not 0 <= other < len(pins):
        return False
    pins[index], pins[other] = pins[other], pins[index]
    for rank, row in enumerate(reversed(pins), 1):
        row.pin_order = rank
    ChatParticipant.objects.bulk_update(pins, ["pin_order"])
    return True


@login_required
@require_POST
@rate_limit("chat_list_action")
def chat_list_action(request):
    if request.POST.get("account_id") != str(request.user.pk):
        return _error("Аккаунт изменился. Обновите страницу.", 409)
    action = request.POST.get("action", "")
    if action == "archive_visibility":
        hidden = request.POST.get("hidden")
        if hidden not in ("0", "1"):
            return _error("Некорректная настройка архива.")
        get_user_model().objects.filter(pk=request.user.pk).update(archive_in_main_menu=hidden == "1")
        return JsonResponse({"ok": True, "archive_hidden": hidden == "1"})

    if action == "archive_read_all":
        with transaction.atomic():
            rows = ChatParticipant.objects.select_for_update().filter(
                user=request.user, is_hidden=False, is_archived=True,
            ).order_by("pk")
            count = 0
            for membership in rows:
                views._mark_membership_read(membership, request.user)
                count += 1
        return JsonResponse({"ok": True, "count": count})

    if action not in ACTIONS:
        return _error("Неизвестное действие.")
    try:
        ids = _ids(request.POST.get("chat_ids", ""))
    except ValueError as error:
        return _error(str(error))
    folder = request.POST.get("folder")
    if folder not in ("main", "archive", "custom"):
        return _error("Неизвестная папка.")
    custom = requested_folder(request.user, request.POST.get("folder_id")) if folder == "custom" else None
    if folder == "custom" and custom is None:
        return _error("Выберите папку.")
    archived = folder == "archive"
    if not custom and ((action == "archive" and archived) or (action == "unarchive" and not archived)):
        return _error("Чаты уже находятся в выбранной папке.")
    duration = request.POST.get("duration", "forever")
    if action == "mute" and duration not in MUTE_DURATIONS:
        return _error("Неизвестный срок отключения уведомлений.")
    if action in {"move_up", "move_down"} and len(ids) != 1:
        return _error("Выберите один закреплённый чат.")

    with transaction.atomic():
        get_user_model().objects.select_for_update().only("id").get(pk=request.user.pk)
        rows = list(ChatParticipant.objects.select_for_update().filter(
            user=request.user, chat_id__in=ids, is_hidden=False,
        ).order_by("pk"))
        # No partial operation and no existence oracle for other users' chats.
        if len(rows) != len(ids):
            return _error("Один из чатов больше недоступен.", 404)
        if custom:
            custom = ChatFolder.objects.select_for_update().filter(pk=custom.pk, owner=request.user).first()
            if custom is None:
                return _error("Папка удалена.", 404)
            visible_ids = [chat.pk for chat in views._folder_sidebar_context(
                request.user, raw_folder=custom.pk,
            )["chats"]]
            if not ids.issubset(set(visible_ids)):
                return _error("Список чатов изменился. Обновите его.", 409)
            if action in {"pin", "unpin", "move_up", "move_down"}:
                pins = list(custom.pinned_chat_ids)
                if action == "pin":
                    pins = [pk for pk in visible_ids if pk in ids and pk not in pins] + pins
                    if len(pins) > MAX_CHATS:
                        return _error("Слишком много закреплённых чатов.")
                elif action == "unpin":
                    pins = [pk for pk in pins if pk not in ids]
                else:
                    pinned_visible = [pk for pk in pins if pk in visible_ids]
                    pk = next(iter(ids))
                    if pk in pinned_visible:
                        index = pinned_visible.index(pk)
                        other = index + (-1 if action == "move_up" else 1)
                        if 0 <= other < len(pinned_visible):
                            first, second = pins.index(pk), pins.index(pinned_visible[other])
                            pins[first], pins[second] = pins[second], pins[first]
                if pins != custom.pinned_chat_ids:
                    custom.pinned_chat_ids = pins
                    custom.revision += 1
                    custom.save(update_fields=["pinned_chat_ids", "revision"])
                return JsonResponse({"ok": True, "count": len(rows)})
        elif any(row.is_archived != archived for row in rows):
            return _error("Список чатов изменился. Обновите его.", 409)
        now = timezone.now()
        for row in rows:
            if action in {"archive", "unarchive"}:
                set_membership_archived(row, action == "archive")
            elif action in {"pin", "unpin"}:
                set_membership_pinned(row, action == "pin")
            elif action == "mute":
                delta = MUTE_DURATIONS[duration]
                row.is_muted = True
                row.muted_until = now + delta if delta is not None else None
                row.save(update_fields=["is_muted", "muted_until"])
            elif action == "unmute":
                row.is_muted = False
                row.muted_until = None
                row.save(update_fields=["is_muted", "muted_until"])
            elif action == "mark_read":
                views._mark_membership_read(row, request.user)
            elif action == "mark_unread":
                row.marked_unread_at = now
                row.save(update_fields=["marked_unread_at"])
            else:
                _reorder(row, action)
    return JsonResponse({"ok": True, "count": len(rows)})
