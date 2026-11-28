"""Explicit community-local bans, restrictions and administrator permissions."""
import json
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import community_profiles as profiles
from .community_permissions import ADMIN_RIGHTS, DURATIONS, available_member_denials, can_moderate, has_admin_right
from .models import Chat, ChatJoinRequest, ChatMemberModeration, ChatParticipant
from .ratelimit import rate_limit
from .membership_statistics import Source as MembershipSource, record_membership_event


def error(message, status=400):
    return JsonResponse({"ok": False, "error": message}, status=status)


def parse_rights(request, name, choices):
    try:
        values = json.loads(request.POST.get(name, ""))
        if not isinstance(values, list) or any(type(value) is not str or value not in choices for value in values):
            raise ValueError
        return [key for key in choices if key in values]
    except (ValueError, TypeError):
        raise ValueError("Некорректный набор разрешений.") from None


@login_required
@require_POST
@rate_limit("community_moderation")
def community_moderation(request, chat_id):
    if request.POST.get("account_id") != str(request.user.pk):
        return error("Аккаунт изменился. Обновите страницу.", 409)
    action = request.POST.get("action")
    try:
        user_id = int(request.POST.get("user_id", ""))
        if not 0 < user_id <= 9223372036854775807:
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        return error("Некорректный участник.")
    if action not in {"admin_rights", "ban", "restrict", "lift"}:
        return error("Неизвестное действие.")
    with transaction.atomic():
        chat = get_object_or_404(Chat.objects.select_for_update(), pk=chat_id, type__in=(Chat.Type.GROUP, Chat.Type.CHANNEL))
        actor = get_object_or_404(ChatParticipant.objects.select_for_update(), chat=chat, user=request.user, is_hidden=False)
        target = ChatParticipant.objects.select_for_update().filter(chat=chat, user_id=user_id).first()
        if action == "admin_rights":
            if actor.role != ChatParticipant.Role.OWNER:
                return error("Права администраторов изменяет только владелец.", 403)
            if target is None or target.role != ChatParticipant.Role.ADMIN:
                return error("Выберите администратора.", 404)
            try:
                rights = parse_rights(request, "permissions", ADMIN_RIGHTS)
            except ValueError as exc:
                return error(str(exc))
            target.admin_permissions = rights
            target.save(update_fields=["admin_permissions"])
            profiles._log(chat, request.user, "admin_rights", "Изменены права администратора " + target.user.display_name,
                          target_user=target.user)
        else:
            if not has_admin_right(actor, "moderate_members"):
                return error("Недостаточно прав для модерации.", 403)
            row = ChatMemberModeration.objects.select_for_update().filter(chat=chat, user_id=user_id).first()
            if user_id == actor.user_id or (target and not can_moderate(actor, target)):
                return error("Нельзя модерировать этого участника.", 403)
            if action == "lift":
                if row is None:
                    return error("Ограничение не найдено.", 404)
                target_user = row.user
                row.delete()
                profiles._log(chat, request.user, "moderation_lift", "Сняты ограничения: " + target_user.display_name,
                              target_user=target_user)
            else:
                # Only existing members can be sanctioned. A prior ban can
                # be extended using the list, even after membership removal.
                if target is None and not (action == "ban" and row and row.banned):
                    return error("Участник не найден.", 404)
                if action == "restrict" and target.role != ChatParticipant.Role.MEMBER:
                    return error("Индивидуальные ограничения доступны для обычных участников.", 400)
                duration = request.POST.get("duration")
                if duration not in DURATIONS:
                    return error("Некорректный срок.")
                reason = request.POST.get("reason", "").strip()
                if len(reason) > 200:
                    return error("Причина должна содержать не более 200 символов.")
                try:
                    denied = parse_rights(request, "permissions", available_member_denials(chat)) if action == "restrict" else []
                except ValueError as exc:
                    return error(str(exc))
                if action == "restrict" and not denied:
                    return error("Выберите хотя бы одно ограничение.")
                target_user = target.user if target else row.user
                seconds = DURATIONS[duration]
                ChatMemberModeration.objects.update_or_create(chat=chat, user=target_user, defaults={
                    "banned": action == "ban", "denied_permissions": denied,
                    "expires_at": timezone.now() + timedelta(seconds=seconds) if seconds else None,
                    "reason": reason, "actor": request.user,
                })
                if action == "ban":
                    if target:
                        target.delete()
                        record_membership_event(chat, MembershipSource.BANNED)
                    ChatJoinRequest.objects.filter(chat=chat, user=target_user, status=ChatJoinRequest.Status.PENDING).update(
                        status=ChatJoinRequest.Status.REJECTED, decided_at=timezone.now(), decided_by=request.user,
                    )
                profiles._log(chat, request.user, "member_" + action,
                              ("Заблокирован: " if action == "ban" else "Ограничен: ") + target_user.display_name,
                              target_user=target_user)
    return JsonResponse({"ok": True, "settings": profiles._settings_payload(request, chat),
                         "profile": profiles._profile_payload(request, chat)})
