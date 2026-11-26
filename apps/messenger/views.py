import copy
import hashlib
from functools import wraps
from itertools import islice
from uuid import UUID
import json
import math
import re
import tempfile
import zipfile
from datetime import timedelta
from io import StringIO
from pathlib import Path
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.db import connection, transaction
from django.db.models import (
    BigIntegerField,
    BooleanField,
    Case,
    Count,
    F,
    Exists,
    OuterRef,
    Prefetch,
    Q,
    Subquery,
    TextField,
    Value,
    When,
)
from django.db.models.functions import Coalesce, Concat, Greatest, Trim
from django.http import (
    FileResponse,
    Http404,
    HttpResponse,
    HttpResponseNotModified,
    HttpResponseForbidden,
    JsonResponse,
    StreamingHttpResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.http import parse_etags, url_has_allowed_host_and_scheme
from django.utils.cache import patch_vary_headers
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.multiaccount import account_slots
from apps.accounts.privacy import (
    AUTO_DELETE_CHOICES,
    INACTIVITY_CHOICES,
    active_sessions_payload,
    auto_delete_label,
    blocked_users_payload,
    inactivity_label,
    is_blocked_between,
    privacy_allows,
    privacy_rule_payload,
)

from .forms import CommunityForm, EditMessageForm, MessageForm
from .media_processing import THUMBNAIL_VERSION, compress_image_upload, make_thumbnail
from PIL import Image
from .community_permissions import (
    can_pin_messages, has_admin_right, is_banned, member_denials, member_reaction_emojis,
)
from .folder_rules import decorate_folder_categories, matching_chats, requested_folder
from .markdown import render_message_markdown
from .models import (
    Chat,
    ChatFolder,
    ChatJoinRequest,
    ChatParticipant,
    Contact,
    Message,
    MessageAttachment,
    MessageHiddenForUser,
    PinnedMessage,
    Sticker,
    VoiceMessagePlayback,
)
from .models import MessageReaction, MessageSendReceipt
from .contact_names import contact_aliases, contact_display_name, normalize_alias
from .ratelimit import rate_limit
from .services import (
    apply_archive_rules_on_new_message,
    attachment_kind,
    attachment_url,
    visible_chat_attachments,
    shared_attachment_payload,
    clone_attachments,
    delete_message_content,
    discussion_counts,
    get_or_create_direct_chat,
    invited_membership_defaults,
    mark_chat_read,
    set_membership_archived,
    set_membership_pinned,
    other_user_for_chat,
    serialize_message,
    serialize_reactions,
    serialize_pins,
    serialize_special_content,
    touch_chat,
    visible_forward_username,
)

User = get_user_model()


def _safe_next(request, fallback):
    candidate = request.POST.get("next", "")
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return fallback


def _wants_json(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _form_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _clean_special_payload(special_type, raw_payload):
    if not isinstance(raw_payload, dict):
        raise ValueError("Некорректные данные вложения.")

    if special_type == Message.SpecialType.POLL:
        question = str(raw_payload.get("question", "")).strip()[:255]
        raw_options = raw_payload.get("options")
        if not isinstance(raw_options, list):
            raise ValueError("Варианты опроса должны быть списком.")
        if len(raw_options) > 10:
            raise ValueError("В опросе может быть не больше 10 вариантов.")
        options = []
        seen = set()
        for value in raw_options:
            text = str(value).strip()[:100]
            key = text.casefold()
            if not text or key in seen:
                continue
            seen.add(key)
            options.append({"text": text, "voters": []})
        if not question:
            raise ValueError("Введите вопрос опроса.")
        if len(options) < 2:
            raise ValueError("В опросе должно быть хотя бы два варианта.")
        if len(options) > 10:
            raise ValueError("В опросе может быть не больше 10 вариантов.")
        quiz = bool(raw_payload.get("quiz"))
        multiple = bool(raw_payload.get("multiple")) and not quiz
        correct_option = raw_payload.get("correct_option")
        if quiz:
            try:
                correct_option = int(correct_option)
            except (TypeError, ValueError):
                raise ValueError("Для викторины выберите правильный ответ.")
            if correct_option < 0 or correct_option >= len(options):
                raise ValueError("Для викторины выберите правильный ответ.")
        else:
            correct_option = None
        return {
            "question": question,
            "options": options,
            "anonymous": bool(raw_payload.get("anonymous", True)),
            "multiple": multiple,
            "quiz": quiz,
            "correct_option": correct_option,
            "explanation": str(raw_payload.get("explanation", "")).strip()[:500],
            "closed": False,
        }, question

    if special_type == Message.SpecialType.TODO:
        title = str(raw_payload.get("title", "")).strip()[:255]
        raw_tasks = raw_payload.get("tasks")
        if not isinstance(raw_tasks, list):
            raise ValueError("Задачи должны быть списком.")
        if len(raw_tasks) > 30:
            raise ValueError("В списке может быть не больше 30 задач.")
        tasks = []
        for value in raw_tasks:
            text = str(value).strip()[:160]
            if text:
                tasks.append({"text": text, "done": False, "done_by": None})
        if not title:
            raise ValueError("Введите название списка задач.")
        if not tasks:
            raise ValueError("Добавьте хотя бы одну задачу.")
        if len(tasks) > 30:
            raise ValueError("В списке может быть не больше 30 задач.")
        return {
            "title": title,
            "tasks": tasks,
            "allow_others_add": bool(raw_payload.get("allow_others_add", False)),
            "allow_others_mark": bool(raw_payload.get("allow_others_mark", True)),
        }, title

    if special_type == Message.SpecialType.ARTICLE:
        title = str(raw_payload.get("title", "")).strip()[:200]
        subtitle = str(raw_payload.get("subtitle", "")).strip()[:300]
        body = str(raw_payload.get("body", "")).strip()[:40000]
        if not title:
            raise ValueError("Введите заголовок статьи.")
        if not body:
            raise ValueError("Введите текст статьи.")
        search_text = "\n".join(
            part for part in (title, subtitle, body[:3000]) if part
        )[:4096]
        return {
            "title": title,
            "subtitle": subtitle,
            "body": body,
            "format": "sovietgram-markdown-v1",
        }, search_text

    if special_type == Message.SpecialType.LOCATION:
        label = str(raw_payload.get("label", "")).strip()[:120]
        try:
            latitude = round(float(raw_payload.get("latitude")), 6)
            longitude = round(float(raw_payload.get("longitude")), 6)
        except (TypeError, ValueError):
            raise ValueError("Укажите корректные координаты.")
        if not (math.isfinite(latitude) and math.isfinite(longitude)):
            raise ValueError("Укажите конечные значения координат.")
        if latitude < -90 or latitude > 90 or longitude < -180 or longitude > 180:
            raise ValueError("Координаты находятся вне допустимого диапазона.")
        return {
            "label": label or "Геопозиция",
            "latitude": latitude,
            "longitude": longitude,
        }, label or "Геопозиция"

    raise ValueError("Неизвестный тип вложения.")


def _special_restriction_text(special_type, special_data, fallback=""):
    """Check the entire user-visible text, not just a shortened search preview.

    In particular, article bodies after character 3000, poll options and task
    descriptions must respect group policies disallowing links.
    """
    data = special_data if isinstance(special_data, dict) else {}
    if special_type == Message.SpecialType.ARTICLE:
        return "\n".join(
            str(data.get(key, "")) for key in ("title", "subtitle", "body")
        )
    if special_type == Message.SpecialType.POLL:
        return "\n".join([
            str(data.get("question", "")),
            *(str(item.get("text", "")) for item in (data.get("options") or []) if isinstance(item, dict)),
            str(data.get("explanation", "")),
        ])
    if special_type == Message.SpecialType.TODO:
        return "\n".join([
            str(data.get("title", "")),
            *(str(item.get("text", "")) for item in (data.get("tasks") or []) if isinstance(item, dict)),
        ])
    return fallback


def _chat_for_user(user, chat_id):
    return get_object_or_404(
        Chat.objects.filter(
            participants=user,
            memberships__user=user,
            memberships__is_hidden=False,
        )
        .prefetch_related("participants", "memberships__user")
        .distinct(),
        pk=chat_id,
    )


def _membership(chat, user):
    viewer_memberships = getattr(chat, "_viewer_memberships", None)
    if viewer_memberships is not None:
        for membership in viewer_memberships:
            if membership.user_id == user.pk:
                return membership
    for membership in chat.memberships.all():
        if membership.user_id == user.pk:
            return membership
    return ChatParticipant.objects.get(chat=chat, user=user)


def _other_membership(chat, user):
    for membership in chat.memberships.all():
        if membership.user_id != user.pk:
            return membership
    return None


def _other_last_read_id(chat, user):
    other = _other_membership(chat, user)
    if other is not None:
        return max(other.read_through_id, other.last_read_message_id or 0)
    return chat.messages.filter(is_deleted=False).order_by("-id").values_list("id", flat=True).first() or 0


def _presence_text(user, viewer=None):
    exact = bool(
        viewer
        and getattr(viewer, "is_authenticated", False)
        and privacy_allows(user, viewer, "last_seen")
    )
    if viewer and getattr(viewer, "pk", None) == user.pk:
        exact = True

    if exact and user.is_online:
        return "в сети"
    if not user.last_seen_at:
        return "был(а) давно"

    now = timezone.now()
    delta = now - user.last_seen_at
    if not exact:
        return "был(а) недавно" if delta < timedelta(days=3) else "был(а) давно"

    local_seen = timezone.localtime(user.last_seen_at)
    if local_seen.date() == timezone.localdate():
        return f"был(а) сегодня в {local_seen:%H:%M}"
    if local_seen.date() == timezone.localdate() - timedelta(days=1):
        return f"был(а) вчера в {local_seen:%H:%M}"
    return f"был(а) {local_seen:%d.%m.%Y} в {local_seen:%H:%M}"


def _decorate_chat_ui(chat, user, aliases=None):
    chat.is_saved_ui = (
        chat.type == Chat.Type.PRIVATE
        and chat.direct_key == f"self:{user.pk}"
    )
    chat.is_collective_ui = chat.type != Chat.Type.PRIVATE

    if chat.type == Chat.Type.PRIVATE:
        other_user = other_user_for_chat(chat, user)
        chat.other_user = other_user
        chat.display_name_ui = "Избранное" if chat.is_saved_ui else contact_display_name(user, other_user, aliases)
        chat.username_ui = "" if chat.is_saved_ui else other_user.username
        chat.avatar_text_ui = "★" if chat.is_saved_ui else other_user.initials
        chat.other_user_avatar_url_ui = (
            other_user.avatar_url
            if (
                not chat.is_saved_ui
                and other_user.avatar
                and privacy_allows(other_user, user, "profile_photo")
            )
            else ""
        )
        chat.search_text_ui = f"{chat.display_name_ui} {other_user.display_name} {chat.username_ui}".lower()
        chat.status_ui = "Личное облако" if chat.is_saved_ui else _presence_text(other_user, user)
    else:
        chat.other_user = None
        chat.display_name_ui = chat.title or (
            "Канал" if chat.type == Chat.Type.CHANNEL else "Группа"
        )
        chat.username_ui = chat.username or ""
        chat.avatar_text_ui = "К" if chat.type == Chat.Type.CHANNEL else "Г"
        chat.search_text_ui = f"{chat.display_name_ui} {chat.username_ui}".lower()
        members_count = getattr(chat, "member_count_ui", None)
        if members_count is None:
            members_count = chat.memberships.count()
        if chat.type == Chat.Type.CHANNEL:
            chat.status_ui = f"канал · {members_count} подписчик(ов)"
        else:
            chat.status_ui = f"группа · {members_count} участник(ов)"
    return chat


def _base_message_queryset(chat):
    return (
        chat.messages.select_related(
            "sender", "reply_to", "reply_to__sender",
            "forwarded_from", "forwarded_from__sender",
        ).prefetch_related("attachments", "reactions")
    )


_LINK_RE = re.compile(
    r"(?:https?://\S+|www\.\S+|\b[\w.-]+\.[a-z]{2,}(?=[:/?#\s.,!?)]|$))",
    re.IGNORECASE,
)


def _visible_message_queryset(chat, user):
    membership = ChatParticipant.objects.get(chat=chat, user=user)
    queryset = _base_message_queryset(chat).exclude(hidden_for_users__user=user).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
    )
    if membership.cleared_before_message_id:
        queryset = queryset.filter(id__gt=membership.cleared_before_message_id)
    if (
        chat.type != Chat.Type.PRIVATE
        and not chat.history_visible_to_new_members
        and not membership.can_see_pre_join_history
    ):
        queryset = queryset.filter(created_at__gte=membership.joined_at)
    return queryset.distinct()


def _visible_pins_queryset(chat, user):
    membership = ChatParticipant.objects.get(chat=chat, user=user)
    queryset = PinnedMessage.objects.filter(
        chat=chat,
        message__is_deleted=False,
    ).exclude(message__hidden_for_users__user=user)
    if membership.cleared_before_message_id:
        queryset = queryset.filter(
            message_id__gt=membership.cleared_before_message_id
        )
    if (
        chat.type != Chat.Type.PRIVATE
        and not chat.history_visible_to_new_members
        and not membership.can_see_pre_join_history
    ):
        queryset = queryset.filter(message__created_at__gte=membership.joined_at)
    return queryset.distinct()


def _latest_visible_message_id(chat, user):
    return (
        _visible_message_queryset(chat, user)
        .filter(is_deleted=False)
        .order_by("-id")
        .values_list("id", flat=True)
        .first()
        or 0
    )


def _clear_history_for_user(chat, membership):
    latest_id = _latest_visible_message_id(chat, membership.user)
    if latest_id:
        membership.cleared_before_message_id = max(
            membership.cleared_before_message_id,
            latest_id,
        )
    membership.last_read_message_id = latest_id or membership.last_read_message_id
    membership.read_through_id = max(membership.read_through_id, latest_id or 0)
    membership.marked_unread_at = None
    membership.draft_text = ""
    membership.draft_updated_at = None
    membership.last_typing_at = None
    membership.save(
        update_fields=(
            "cleared_before_message_id",
            "last_read_message",
            "read_through_id",
            "marked_unread_at",
            "draft_text",
            "draft_updated_at",
            "last_typing_at",
        )
    )
    if membership.cleared_before_message_id:
        MessageHiddenForUser.objects.filter(
            user=membership.user,
            message__chat=chat,
            message_id__lte=membership.cleared_before_message_id,
        ).delete()
    return latest_id


def _can_delete_message_for_everyone(chat, membership, message):
    if chat.type == Chat.Type.PRIVATE:
        return True
    return (
        message.sender_id == membership.user_id
        or has_admin_right(membership, "delete_messages")
    )


def _posting_restriction(
    chat,
    membership,
    text="",
    has_attachments=False,
    check_slow_mode=True,
):
    if has_admin_right(membership, "post_messages"):
        return None

    if chat.type == Chat.Type.CHANNEL:
        return ("Публикация в канале недоступна.", 0)

    if chat.type != Chat.Type.GROUP:
        return None

    denied = member_denials(chat, membership)
    if text and "send_text" in denied:
        return ("Вам запрещено отправлять текстовые сообщения в этой группе.", 0)
    if has_attachments and "send_media" in denied:
        return ("Вам запрещено отправлять медиа и файлы в этой группе.", 0)
    if text and "send_links" in denied and _LINK_RE.search(text):
        return ("Вам запрещено отправлять ссылки в этой группе.", 0)

    if text and not chat.members_can_send_messages:
        return ("Администраторы запретили участникам отправлять текстовые сообщения.", 0)
    if has_attachments and not chat.members_can_send_media:
        return ("Администраторы запретили участникам отправлять медиа и файлы.", 0)
    if text and not chat.members_can_send_links and _LINK_RE.search(text):
        return ("Администраторы запретили участникам отправлять ссылки.", 0)

    if check_slow_mode and chat.slow_mode_seconds:
        last_sent = (
            Message.objects.filter(
                chat=chat,
                sender=membership.user,
                is_deleted=False,
            )
            .order_by("-created_at")
            .values_list("created_at", flat=True)
            .first()
        )
        if last_sent:
            remaining = chat.slow_mode_seconds - int(
                (timezone.now() - last_sent).total_seconds()
            )
            if remaining > 0:
                return (f"Медленный режим: подождите ещё {remaining} сек.", remaining)
    return None


def _hide_inaccessible_reply_previews(chat, user, messages):
    membership = ChatParticipant.objects.get(chat=chat, user=user)
    reply_ids = {
        message.reply_to_id
        for message in messages
        if message.reply_to_id is not None
    }
    hidden_reply_ids = set(
        MessageHiddenForUser.objects.filter(
            user=user,
            message_id__in=reply_ids,
        ).values_list("message_id", flat=True)
    )
    for message in messages:
        reply = message.reply_to
        if reply is None:
            continue
        if (
            reply.pk <= membership.cleared_before_message_id
            or reply.pk in hidden_reply_ids
            or (
                chat.type != Chat.Type.PRIVATE
                and not chat.history_visible_to_new_members
                and not membership.can_see_pre_join_history
                and reply.created_at < membership.joined_at
            )
        ):
            message.reply_to = None


def _serialize_visible_pins(chat, user):
    return [
        {
            "id": pin.pk,
            "message_id": pin.message_id,
            "sender_name": pin.message.sender.display_name,
            "preview": pin.message.preview[:180],
        }
        for pin in _visible_pins_queryset(chat, user)
        .select_related("message", "message__sender")
        .order_by("-pinned_at", "-id")[:8]
    ]


def _prepare_sidebar_chats(user, archived=False):
    membership = ChatParticipant.objects.filter(chat=OuterRef("pk"), user=user)
    member_count = (
        ChatParticipant.objects.filter(chat=OuterRef("pk"))
        .values("chat_id")
        .annotate(total=Count("id"))
        .values("total")
    )
    history_visible = (
        Q(chat__type=Chat.Type.PRIVATE)
        | Q(chat__history_visible_to_new_members=True)
        | Q(chat__memberships__can_see_pre_join_history=True)
        | Q(created_at__gte=F("chat__memberships__joined_at"))
    )
    visible_message = (
        Message.objects.filter(
            Q(id__gt=F("chat__memberships__cleared_before_message_id")),
            history_visible,
            chat=OuterRef("pk"),
            chat__memberships__user=user,
            is_deleted=False,
        )
        .exclude(hidden_for_users__user=user)
        .order_by("-id")
    )
    unread_count = (
        Message.objects.filter(
            Q(id__gt=F("chat__memberships__cleared_before_message_id")),
            Q(id__gt=Greatest(F("chat__memberships__read_through_id"), Coalesce(F("chat__memberships__last_read_message_id"), Value(0, output_field=BigIntegerField()), output_field=BigIntegerField()), output_field=BigIntegerField())),
            history_visible,
            chat=OuterRef("pk"),
            chat__memberships__user=user,
            is_deleted=False,
        )
        .exclude(sender=user)
        .exclude(hidden_for_users__user=user)
        .order_by()
        .values("chat_id")
        .annotate(total=Count("id"))
        .values("total")
    )

    chats = list(
        Chat.objects.filter(
            memberships__user=user,
            memberships__is_archived=archived,
            memberships__is_hidden=False,
        )
        .annotate(
            last_message_id_ui=Subquery(visible_message.values("id")[:1]),
            last_message_text_ui=Subquery(visible_message.values("text")[:1]),
            last_message_sender_id_ui=Subquery(
                visible_message.values("sender_id")[:1]
            ),
            last_message_created_at_ui=Subquery(
                visible_message.values("created_at")[:1]
            ),
            last_read_message_id_ui=Coalesce(
                Subquery(
                    membership.annotate(cursor=Greatest(
                        F("read_through_id"),
                        Coalesce(F("last_read_message_id"), Value(0, output_field=BigIntegerField()), output_field=BigIntegerField()),
                        output_field=BigIntegerField(),
                    )).values("cursor")[:1],
                    output_field=BigIntegerField(),
                ),
                Value(0, output_field=BigIntegerField()),
            ),
            is_pinned_ui=Subquery(
                membership.values("is_pinned")[:1], output_field=BooleanField()
            ),
            pin_order_ui=Coalesce(
                Subquery(membership.values("pin_order")[:1], output_field=BigIntegerField()),
                Value(0, output_field=BigIntegerField()),
            ),
            marked_unread_ui=Exists(membership.filter(marked_unread_at__isnull=False)),
            is_muted_ui=Subquery(
                membership.annotate(
                    is_currently_muted=Case(
                        When(
                            is_muted=True,
                            muted_until__isnull=True,
                            then=Value(True),
                        ),
                        When(
                            is_muted=True,
                            muted_until__gt=timezone.now(),
                            then=Value(True),
                        ),
                        default=Value(False),
                        output_field=BooleanField(),
                    )
                ).values("is_currently_muted")[:1],
                output_field=BooleanField(),
            ),
            draft_text_ui=Subquery(
                membership.values("draft_text")[:1], output_field=TextField()
            ),
            joined_at_ui=Subquery(membership.values("joined_at")[:1]),
            can_see_pre_join_history_ui=Subquery(
                membership.values("can_see_pre_join_history")[:1],
                output_field=BooleanField(),
            ),
            member_count_ui=Coalesce(
                Subquery(member_count[:1], output_field=BigIntegerField()),
                Value(0, output_field=BigIntegerField()),
            ),
            unread_count_ui=Coalesce(
                Subquery(unread_count[:1], output_field=BigIntegerField()),
                Value(0, output_field=BigIntegerField()),
            ),
        )
        .prefetch_related("participants")
        .order_by(
            F("is_pinned_ui").desc(nulls_last=True),
            F("pin_order_ui").desc(nulls_last=True),
            F("last_message_created_at_ui").desc(nulls_last=True),
            "-updated_at",
        )
        .distinct()
    )

    last_message_ids = [
        chat.last_message_id_ui
        for chat in chats
        if chat.last_message_id_ui
    ]
    attachment_kinds = {}
    if last_message_ids:
        for message_id, kind in (
            MessageAttachment.objects.filter(message_id__in=last_message_ids)
            .order_by("message_id", "id")
            .values_list("message_id", "kind")
        ):
            attachment_kinds.setdefault(message_id, kind)

    aliases = contact_aliases(user)
    for chat in chats:
        _decorate_chat_ui(chat, user, aliases)
        chat.is_archived_ui = archived
        chat.has_unread_ui = bool(chat.unread_count_ui or chat.marked_unread_ui)
        chat.unread_badge_count_ui = max(chat.unread_count_ui or 0, int(chat.marked_unread_ui))
        preview = " ".join((chat.last_message_text_ui or "").split())
        if preview:
            chat.last_message_preview_ui = preview
        elif chat.last_message_id_ui:
            chat.last_message_preview_ui = {
                MessageAttachment.Kind.VOICE: "Голосовое сообщение",
                MessageAttachment.Kind.STICKER: "Стикер",
                MessageAttachment.Kind.AUDIO: "Аудио",
                MessageAttachment.Kind.IMAGE: "Фото",
                MessageAttachment.Kind.VIDEO: "Видео",
                MessageAttachment.Kind.FILE: "Файл",
            }.get(
                attachment_kinds.get(chat.last_message_id_ui),
                "Медиа",
            )
        else:
            chat.last_message_preview_ui = ""

    chats.sort(
        key=lambda chat: (
            1 if chat.is_pinned_ui else 0,
            chat.pin_order_ui if chat.is_pinned_ui else 0,
            (chat.last_message_created_at_ui or chat.updated_at).timestamp(),
            chat.updated_at.timestamp(),
        ),
        reverse=True,
    )
    return chats


def _posting_capabilities(chat, membership, user):
    can_text = True
    can_media = True
    can_voice = True
    reason = ""

    if not has_admin_right(membership, "post_messages"):
        if chat.type == Chat.Type.CHANNEL:
            can_text = can_media = can_voice = False
            reason = "Публиковать в канале могут только администраторы."
        elif chat.type == Chat.Type.GROUP:
            can_text = bool(chat.members_can_send_messages)
            can_media = bool(chat.members_can_send_media)
            can_voice = can_media
            if not can_text and not can_media:
                reason = "Администраторы запретили отправлять сообщения и медиа."
            denied = member_denials(chat, membership)
            if "send_text" in denied:
                can_text = False
            if "send_media" in denied:
                can_media = can_voice = False
            if denied.intersection({"send_text", "send_media"}):
                reason = "На вашу отправку сообщений наложены ограничения."

    if (
        chat.type == Chat.Type.PRIVATE
        and chat.direct_key != f"self:{user.pk}"
    ):
        recipient = other_user_for_chat(chat, user)
        if is_blocked_between(user, recipient):
            can_text = can_media = can_voice = False
            reason = "Диалог недоступен из-за блокировки."
        elif not privacy_allows(recipient, user, "messages"):
            can_text = can_media = can_voice = False
            reason = "Пользователь ограничил входящие личные сообщения."
        else:
            can_voice = can_voice and privacy_allows(
                recipient,
                user,
                "voice_messages",
            )

    return {
        "text": can_text,
        "media": can_media,
        "voice": can_voice,
        "reason": reason,
    }


def _forward_targets(user):
    member_count = (
        ChatParticipant.objects.filter(chat=OuterRef("pk"))
        .values("chat_id")
        .annotate(total=Count("id"))
        .values("total")
    )
    targets = list(
        Chat.objects.filter(
            participants=user,
            memberships__user=user,
            memberships__is_hidden=False,
        )
        .annotate(
            member_count_ui=Coalesce(
                Subquery(member_count[:1], output_field=BigIntegerField()),
                Value(0, output_field=BigIntegerField()),
            )
        )
        .prefetch_related(
            "participants",
            Prefetch(
                "memberships",
                queryset=ChatParticipant.objects.filter(user=user).select_related("user"),
                to_attr="_viewer_memberships",
            ),
        )
        .distinct()
        .order_by("-updated_at")[:60]
    )
    visible = []
    aliases = contact_aliases(user)
    for chat in targets:
        _decorate_chat_ui(chat, user, aliases)
        membership = _membership(chat, user)
        capabilities = _posting_capabilities(chat, membership, user)
        chat.can_forward_text_ui = capabilities["text"]
        chat.can_forward_media_ui = capabilities["media"]
        chat.can_forward_voice_ui = capabilities["voice"]
        if capabilities["text"] or capabilities["media"]:
            visible.append(chat)
    return visible


def _account_slots_with_unread(request):
    slots = account_slots(request)
    for slot in slots:
        slot_user = slot["user"]
        unread = (
            Message.objects.filter(
                Q(id__gt=Greatest(F("chat__memberships__read_through_id"), Coalesce(F("chat__memberships__last_read_message_id"), Value(0, output_field=BigIntegerField()), output_field=BigIntegerField()), output_field=BigIntegerField())),
                Q(id__gt=F("chat__memberships__cleared_before_message_id")),
                (
                    Q(chat__type=Chat.Type.PRIVATE)
                    | Q(chat__history_visible_to_new_members=True)
                    | Q(chat__memberships__can_see_pre_join_history=True)
                    | Q(created_at__gte=F("chat__memberships__joined_at"))
                ),
                chat__memberships__user=slot_user,
                chat__memberships__is_hidden=False,
                is_deleted=False,
            )
            .exclude(sender=slot_user)
            .exclude(hidden_for_users__user=slot_user)
            .count()
        )
        # Manual markers add one reminder only if the chat has no real unread
        # messages, so a marked conversation is never counted twice.
        pending = Message.objects.filter(
            chat_id=OuterRef("chat_id"), is_deleted=False,
            id__gt=OuterRef("cleared_before_message_id"),
        ).filter(
            Q(id__gt=Greatest(
                OuterRef("read_through_id"),
                Coalesce(OuterRef("last_read_message_id"), Value(0, output_field=BigIntegerField()), output_field=BigIntegerField()),
                output_field=BigIntegerField(),
            )),
            Q(chat__type=Chat.Type.PRIVATE)
            | Q(chat__history_visible_to_new_members=True)
            | Q(chat__memberships__user=slot_user, chat__memberships__can_see_pre_join_history=True)
            | Q(created_at__gte=OuterRef("joined_at")),
        ).exclude(sender=slot_user).exclude(hidden_for_users__user=slot_user)
        manual_only = ChatParticipant.objects.filter(
            user=slot_user, is_hidden=False, marked_unread_at__isnull=False,
        ).filter(~Exists(pending)).count()
        slot["unread_count"] = unread + manual_only
    return slots


def _community_candidates(user):
    candidates = list(
        User.objects.filter(is_active=True)
        .exclude(pk=user.pk)
        .order_by("-last_seen_at", "username")[:200]
    )
    visible = []
    for candidate in candidates:
        if is_blocked_between(user, candidate):
            continue
        if not privacy_allows(candidate, user, "invites"):
            continue
        candidate.presence_ui = _presence_text(candidate, user)
        candidate.avatar_url_ui = (
            candidate.avatar_url
            if candidate.avatar and privacy_allows(candidate, user, "profile_photo")
            else ""
        )
        visible.append(candidate)
    return visible


def _archive_summary(archive_chats):
    return {
        "archived_count": len(archive_chats),
        "archived_unread_count": sum(chat.unread_badge_count_ui for chat in archive_chats),
        "archive_has_loud_unread": any(chat.has_unread_ui and not chat.is_muted_ui for chat in archive_chats),
        "archive_preview": ", ".join(chat.display_name_ui for chat in archive_chats[:3]),
    }


def _folder_sidebar_context(user, archived=False, raw_folder=None):
    active_folder = requested_folder(user, raw_folder)
    if active_folder:
        archived = False
    main_chats = _prepare_sidebar_chats(user, archived=False)
    archive_chats = _prepare_sidebar_chats(user, archived=True)
    folders = list(ChatFolder.objects.filter(owner=user))
    all_chats = main_chats + archive_chats
    tabs = []
    current_chats = archive_chats if archived else main_chats
    if folders:
        decorate_folder_categories(all_chats, user)
        for folder in folders:
            matches = matching_chats(folder, all_chats)
            tabs.append({
                "id": folder.pk, "name": folder.name,
                "unread": sum(chat.unread_badge_count_ui for chat in matches),
                "active": bool(active_folder and folder.pk == active_folder.pk),
            })
            if active_folder and folder.pk == active_folder.pk:
                order = {pk: index for index, pk in enumerate(folder.pinned_chat_ids)}
                current_chats = sorted(matches, key=lambda chat: (
                    chat.pk not in order, order.get(chat.pk, 0),
                    -(chat.last_message_created_at_ui or chat.updated_at).timestamp(), -chat.pk,
                ))
                for chat in current_chats:
                    chat.is_pinned_ui = chat.pk in order
    return {
        "chats": current_chats, "show_archived": archived,
        "active_folder": active_folder, "folder_tabs": tabs,
        "main_unread_count": sum(chat.unread_badge_count_ui for chat in main_chats),
        **_archive_summary(archive_chats),
    }


def _messenger_context(request, selected_chat=None, chat_messages=None, archived=False, focus_id=0):
    user = request.user
    sidebar = _folder_sidebar_context(user, archived, request.GET.get("folder"))
    context = {
        **sidebar,
        "selected_chat": selected_chat,
        "chat_messages": chat_messages or [],
        "message_form": MessageForm(),
        "forward_targets": _forward_targets(user),
        "message_focus_id": focus_id,
        "server_time": timezone.now().isoformat(),
        "account_slots": _account_slots_with_unread(request),
        "community_candidates": _community_candidates(user),
        "community_create_url": reverse("messenger:create_community"),
        "settings_privacy_rules": privacy_rule_payload(user),
        "settings_blocked_users": blocked_users_payload(user),
        "settings_sessions": active_sessions_payload(
            user,
            request.session.session_key or "",
        ),
        "settings_inactivity_label": inactivity_label(user.delete_after_inactive_days),
        "settings_auto_delete_label": auto_delete_label(user.default_auto_delete_seconds),
        "privacy_inactivity_choices": list(INACTIVITY_CHOICES.items()),
        "privacy_auto_delete_choices": list(AUTO_DELETE_CHOICES.items()),
    }
    if selected_chat is None:
        return context

    membership = _membership(selected_chat, user)
    _decorate_chat_ui(selected_chat, user)
    selected_chat.other_status_ui = selected_chat.status_ui
    selected_chat.other_last_seen_exact_ui = False
    selected_chat.other_last_seen_at_ui = ""
    selected_chat.other_is_online_ui = False
    if selected_chat.type == Chat.Type.PRIVATE and not selected_chat.is_saved_ui:
        peer = selected_chat.other_user
        if privacy_allows(peer, user, "last_seen"):
            selected_chat.other_last_seen_exact_ui = True
            selected_chat.other_last_seen_at_ui = (
                peer.last_seen_at.isoformat() if peer.last_seen_at else ""
            )
            selected_chat.other_is_online_ui = bool(peer.is_online)
    other_last_read_id = (
        _other_last_read_id(selected_chat, user)
        if selected_chat.type == Chat.Type.PRIVATE
        else 0
    )

    pins = list(
        _visible_pins_queryset(selected_chat, user)
        .select_related("message", "message__sender")
        .order_by("-pinned_at", "-id")[:8]
    )
    pinned_ids = {pin.message_id for pin in pins}
    comment_counts = discussion_counts(
        message.pk for message in context["chat_messages"] if not message.is_deleted
    ) if selected_chat.type == Chat.Type.CHANNEL and selected_chat.comments_enabled else {}
    for message in context["chat_messages"]:
        message.comment_count_ui = comment_counts.get(message.pk, 0)
        message.is_pinned_ui = message.pk in pinned_ids
        message.is_read_ui = message.sender_id == user.pk and message.pk <= other_last_read_id
        message.reactions_ui = serialize_reactions(message, user)
        message.markdown_html_ui = (
            render_message_markdown(message.text, f"message-{message.pk}")
            if not message.is_deleted and not message.special_type else ""
        )

    voice_listened_attachment_ids = set(
        VoiceMessagePlayback.objects.filter(
            user=user,
            attachment__message__chat=selected_chat,
            attachment__kind=MessageAttachment.Kind.VOICE,
        ).values_list("attachment_id", flat=True)
    )

    shared_items = []
    attachments = visible_chat_attachments(selected_chat, membership)[:36]
    for attachment in attachments:
        attachment.ui_url = attachment_url(attachment)
        shared_items.append(attachment)

    capabilities = _posting_capabilities(selected_chat, membership, user)
    can_send_text = capabilities["text"]
    can_send_media = capabilities["media"]
    can_record_voice = capabilities["media"] and capabilities["voice"]
    can_post = can_send_text or can_send_media

    context.update(
        {
            "active_membership": membership,
            "can_post": can_post,
            "can_pin_messages": can_pin_messages(selected_chat, membership),
            "can_moderate_messages": has_admin_right(membership, "delete_messages"),
            "can_send_text": can_send_text,
            "can_send_media": can_send_media,
            "can_record_voice": can_record_voice,
            "post_restriction_ui": capabilities["reason"],
            "composer_draft_text": membership.draft_text if can_send_text else "",
            "other_last_read_id": other_last_read_id,
            "pinned_records": pins,
            "pinned_message_ids": pinned_ids,
            "shared_attachments": shared_items,
            "voice_listened_attachment_ids": voice_listened_attachment_ids,
            "search_url": reverse("messenger:search_messages", args=[selected_chat.pk]),
            "mention_url": reverse("messenger:mention_candidates", args=[selected_chat.pk]),
            "markdown_preview_url": reverse("messenger:markdown_preview", args=[selected_chat.pk]),
            "reaction_choices": MessageReaction.Emoji.choices,
            "allowed_reactions": member_reaction_emojis(selected_chat, membership)
                if selected_chat.type != Chat.Type.PRIVATE or can_send_text else [],
            "mention_profile_prefix": reverse("accounts:public_profile", args=["__mention__"]).split("__mention__")[0],
            "draft_url": reverse("messenger:save_draft", args=[selected_chat.pk]),
            "scheduled_url": reverse("messenger:scheduled_messages", args=[selected_chat.pk]),
            "typing_url": reverse("messenger:typing", args=[selected_chat.pk]),
        }
    )
    return context


def _serialized_message(message, user, chat):
    pinned_ids = set(
        _visible_pins_queryset(chat, user).values_list("message_id", flat=True)
    )
    return serialize_message(
        message,
        user,
        other_last_read_id=(
            _other_last_read_id(chat, user)
            if chat.type == Chat.Type.PRIVATE
            else 0
        ),
        pinned_ids=pinned_ids,
    )


@login_required
def home(request):
    archived = request.GET.get("archived") == "1"
    return render(
        request,
        "messenger/index.html",
        _messenger_context(request, archived=archived),
    )


@login_required
@require_GET
def sidebar_snapshot(request):
    """Refresh unread counts and new chats without reloading the conversation."""
    archived = request.GET.get("archived") == "1"
    response = render(
        request, "messenger/_chat_list.html",
        _folder_sidebar_context(request.user, archived, request.GET.get("folder")),
    )
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
def chat_detail(request, chat_id):
    snapshot_at = timezone.now()
    chat = _chat_for_user(request.user, chat_id)
    membership = _membership(chat, request.user)
    try:
        focus_id = max(0, int(request.GET.get("message", "0")))
    except (TypeError, ValueError):
        focus_id = 0

    base = _visible_message_queryset(chat, request.user).filter(is_deleted=False)
    focus = base.filter(pk=focus_id).first() if focus_id else None
    read_cursor = max(membership.read_through_id, membership.last_read_message_id or 0)
    first_unread_id = (
        base.filter(id__gt=read_cursor).exclude(sender=request.user)
        .order_by("id").values_list("id", flat=True).first() or 0
    )
    unread_anchor_id = 0
    if focus is not None:
        before = list(base.filter(id__lte=focus.pk).order_by("-id")[:50])
        before.reverse()
        after = list(base.filter(id__gt=focus.pk).order_by("id")[:50])
        chat_messages = before + after
    else:
        chat_messages = list(base.order_by("-id")[:100])
        chat_messages.reverse()
        focus_id = 0
        if first_unread_id:
            unread_anchor_id = first_unread_id
            if chat_messages and first_unread_id < chat_messages[0].pk:
                before = list(base.filter(id__lt=first_unread_id).order_by("-id")[:30])
                before.reverse()
                chat_messages = before + list(base.filter(id__gte=first_unread_id).order_by("id")[:70])

    _hide_inaccessible_reply_previews(chat, request.user, chat_messages)
    for message in chat_messages:
        message.special_ui = serialize_special_content(message, request.user)
        message.forwarded_from_username_ui = visible_forward_username(
            message, request.user,
        )

    context = _messenger_context(
        request, chat, chat_messages,
        archived=membership.is_archived, focus_id=focus_id,
    )
    context.update({
        "server_time": snapshot_at.isoformat(),
        "history_has_older": bool(chat_messages and base.filter(id__lt=chat_messages[0].pk).exists()),
        "history_has_newer": bool(chat_messages and base.filter(id__gt=chat_messages[-1].pk).exists()),
        "own_last_read_id": read_cursor,
        "unread_anchor_id": unread_anchor_id,
        "marked_unread_token": membership.marked_unread_at.isoformat() if membership.marked_unread_at else "",
    })
    return render(request, "messenger/index.html", context)


@login_required
@require_GET
def message_history(request, chat_id):
    snapshot_at = timezone.now()
    chat = _chat_for_user(request.user, chat_id)
    base = _visible_message_queryset(chat, request.user).filter(is_deleted=False)
    try:
        before = int(request.GET.get("before", "0"))
        after = int(request.GET.get("after", "0"))
        around = int(request.GET.get("around", "0"))
        if any(value < 0 or value > 9223372036854775807 for value in (before, after, around)):
            raise ValueError
        if sum(bool(value) for value in (before, after, around)) > 1:
            raise ValueError
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "Некорректный курсор истории."}, status=400)
    if before:
        items = list(base.filter(id__lt=before).order_by("-id")[:50])
        items.reverse()
    elif after:
        items = list(base.filter(id__gt=after).order_by("id")[:50])
    elif around:
        # A deleted scroll anchor can be restored to its closest visible neighbor.
        anchor = base.filter(id__gte=around).order_by("id").first()
        if anchor is None:
            anchor = base.order_by("-id").first()
        if anchor is None:
            items = []
        else:
            items = list(base.filter(id__lt=anchor.pk).order_by("-id")[:49])
            items.reverse()
            items += list(base.filter(id__gte=anchor.pk).order_by("id")[:51])
    else:
        items = list(base.order_by("-id")[:100])
        items.reverse()
    _hide_inaccessible_reply_previews(chat, request.user, items)
    pins = set(_visible_pins_queryset(chat, request.user).values_list("message_id", flat=True))
    other_cursor = _other_last_read_id(chat, request.user) if chat.type == Chat.Type.PRIVATE else 0
    membership = _membership(chat, request.user)
    return JsonResponse({
        "ok": True,
        "messages": [serialize_message(item, request.user, other_cursor, pins) for item in items],
        "has_older": base.filter(id__lt=items[0].pk if items else before).exists() if items or before else False,
        "has_newer": base.filter(id__gt=items[-1].pk if items else after).exists() if items or after else False,
        "own_last_read_id": max(membership.read_through_id, membership.last_read_message_id or 0),
        "other_last_read_id": other_cursor,
        "server_time": snapshot_at.isoformat(),
    })


@login_required
@require_POST
def read_messages(request, chat_id):
    account_id = request.POST.get("account_id")
    if account_id is not None and account_id != str(request.user.pk):
        return JsonResponse({"ok": False, "error": "Аккаунт изменился. Обновите страницу."}, status=409)
    chat = _chat_for_user(request.user, chat_id)
    token = request.POST.get("opened_marker", "")
    marker = None
    try:
        message_id = int(request.POST.get("message_id", "0"))
        if token:
            marker = parse_datetime(token)
            if marker is None or timezone.is_naive(marker):
                raise ValueError
        if not 0 <= message_id <= 9223372036854775807 or (not message_id and not marker):
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        return JsonResponse({"ok": False, "error": "Некорректное сообщение."}, status=400)
    with transaction.atomic():
        membership = ChatParticipant.objects.select_for_update().get(chat=chat, user=request.user)
        if membership.is_hidden:
            raise Http404
        if message_id:
            message = _visible_message_queryset(chat, request.user).filter(
                pk=message_id, is_deleted=False,
            ).exclude(sender=request.user).first()
            if message is None:
                return JsonResponse({"ok": False, "error": "Сообщение недоступно."}, status=404)
            mark_chat_read(chat, request.user, message)
        if marker:
            # Only clear the marker that was present when this page was opened.
            # A stale tab must not erase a newer manual mark from another tab.
            ChatParticipant.objects.filter(pk=membership.pk, marked_unread_at=marker).update(marked_unread_at=None)
        membership.refresh_from_db(fields=["read_through_id", "last_read_message", "marked_unread_at"])
    response = JsonResponse({
        "ok": True,
        "account_id": request.user.pk,
        "own_last_read_id": max(membership.read_through_id, membership.last_read_message_id or 0),
        "marked_unread": membership.marked_unread_at is not None,
    })
    response["Cache-Control"] = "private, no-store"
    return response


def _mark_membership_read(membership, user):
    # Explicit "mark read" may acknowledge a whole conversation, not just
    # the visible viewport. Respect cleared/deleted/hidden/pre-join history.
    chat = membership.chat
    latest = _visible_message_queryset(chat, user).filter(
        is_deleted=False,
    ).exclude(sender=user).order_by("-id").first()
    if latest is not None:
        mark_chat_read(chat, user, latest)
    ChatParticipant.objects.filter(pk=membership.pk).update(marked_unread_at=None)


@login_required
@require_POST
def mark_all_chats_read(request):
    # Legacy main-list action includes archived chats. The archive button
    # explicitly scopes the same operation to that folder (also without JS).
    archive_only = request.POST.get("scope") == "archive"
    active_folder = requested_folder(request.user, request.POST.get("folder_id"))
    scope = {"is_archived": True} if archive_only else {}
    if active_folder:
        scope = {"chat_id__in": [chat.pk for chat in _folder_sidebar_context(
            request.user, raw_folder=active_folder.pk,
        )["chats"]]}
    with transaction.atomic():
        memberships = ChatParticipant.objects.select_for_update().filter(
            user=request.user, is_hidden=False, **scope,
        ).order_by("pk")
        for membership in memberships:
            _mark_membership_read(membership, request.user)
    label = ("Папка отмечена прочитанной." if active_folder else
             "Весь архив отмечен прочитанным." if archive_only else "Все чаты, включая архив, отмечены прочитанными.")
    if _wants_json(request):
        return JsonResponse({"ok": True, "message": label})
    messages.success(request, label)
    fallback = reverse("messenger:home") + (
        f"?folder={active_folder.pk}" if active_folder else "?archived=1" if archive_only else ""
    )
    return redirect(_safe_next(request, fallback))


@login_required
@require_GET
def export_chat_history(request, chat_id):
    chat = _chat_for_user(request.user, chat_id)
    if chat.protect_content:
        return HttpResponseForbidden(
            "Экспорт истории отключён для этой переписки."
        )

    _decorate_chat_ui(chat, request.user)
    visible_messages = (
        _visible_message_queryset(chat, request.user)
        .filter(is_deleted=False)
        .order_by("id")
    )
    archive = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")

    try:
        with zipfile.ZipFile(
            archive,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as bundle:
            html = StringIO()
            html.write(
                "<!doctype html><html lang=\"ru\"><head><meta charset=\"utf-8\">"
                "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
                f"<title>{escape(chat.display_name_ui)} — история Sovietgram</title>"
                "<style>body{max-width:900px;margin:32px auto;padding:0 18px;"
                "font:15px/1.5 system-ui,sans-serif;color:#28231f;background:#f7f2eb}"
                "h1{font-size:24px}.message{margin:14px 0;padding:14px 16px;"
                "background:#fff;border:1px solid #e8dfd4;border-radius:12px}"
                ".meta{color:#887b6d;font-size:12px}.body{white-space:normal;"
                "overflow-wrap:anywhere}.attachments{font-size:13px}</style>"
                "</head><body>"
                f"<h1>{escape(chat.display_name_ui)}</h1>"
                "<p class=\"meta\">Экспортировано из Sovietgram</p>"
            )

            for message in visible_messages.iterator(chunk_size=100):
                sender = escape(message.sender.display_name)
                created_at = timezone.localtime(message.created_at).strftime(
                    "%d.%m.%Y в %H:%M"
                )
                body_text = message.text or message.preview
                body_html = escape(body_text).replace("\r\n", "\n").replace("\n", "<br>")
                html.write(
                    "<article class=\"message\">"
                    f"<div class=\"meta\">{sender} · {created_at}</div>"
                    f"<div class=\"body\">{body_html}</div>"
                )

                if message.special_type:
                    special_json = escape(
                        json.dumps(serialize_special_content(message, request.user), ensure_ascii=False, indent=2)
                    )
                    html.write(
                        "<details><summary>Данные вложения</summary>"
                        f"<pre>{special_json}</pre></details>"
                    )

                attachments = list(message.attachments.all())
                if attachments:
                    html.write("<ul class=\"attachments\">")
                    for index, attachment in enumerate(attachments, start=1):
                        original_name = str(attachment.original_name or "file")
                        safe_name = Path(original_name.replace("\\", "/")).name or f"file-{index}"
                        media_path = f"media/{message.pk}-{index}-{safe_name}"
                        try:
                            attachment.file.open("rb")
                            try:
                                with bundle.open(media_path, "w") as media_file:
                                    while True:
                                        chunk = attachment.file.read(64 * 1024)
                                        if not chunk:
                                            break
                                        media_file.write(chunk)
                            finally:
                                attachment.file.close()
                            html.write(
                                f"<li><a href=\"{escape(quote(media_path))}\">"
                                f"{escape(safe_name)}</a> "
                                f"({int(attachment.size or 0)} байт)</li>"
                            )
                        except (OSError, ValueError):
                            html.write(
                                f"<li>{escape(safe_name)} — файл недоступен</li>"
                            )
                    html.write("</ul>")

                html.write("</article>")

            html.write("</body></html>")
            bundle.writestr("history.html", html.getvalue())

        archive.seek(0)
        return FileResponse(
            archive,
            as_attachment=True,
            filename=f"sovietgram-chat-{chat.pk}-history.zip",
            content_type="application/zip",
        )
    except Exception:
        archive.close()
        raise


@login_required
def calls(request):
    return render(request, "messenger/calls.html")


@login_required
def saved_messages(request):
    chat = get_or_create_direct_chat(request.user, request.user)
    return redirect("messenger:chat", chat_id=chat.pk)


@login_required
def create_community(request):
    initial_type = request.GET.get("type")
    if initial_type not in {Chat.Type.GROUP, Chat.Type.CHANNEL}:
        initial_type = Chat.Type.GROUP

    if request.method != "POST":
        return redirect(f"{reverse('messenger:home')}?create={initial_type}")

    form = CommunityForm(request.POST, request.FILES)
    if not form.is_valid():
        if _wants_json(request):
            return JsonResponse(
                {"ok": False, "errors": form.errors.get_json_data()},
                status=400,
            )
        for field_errors in form.errors.values():
            for error in field_errors:
                messages.error(request, error)
        return redirect(f"{reverse('messenger:home')}?create={initial_type}")

    with transaction.atomic():
        chat = Chat.objects.create(
            type=form.cleaned_data["type"],
            title=form.cleaned_data["title"],
            username=form.cleaned_data["username"] or None,
            description=form.cleaned_data["description"],
        )
        avatar = form.cleaned_data.get("avatar")
        if avatar is not None:
            chat.avatar = avatar
            chat.save(update_fields=["avatar", "updated_at"])

        ChatParticipant.objects.create(
            chat=chat,
            user=request.user,
            role=ChatParticipant.Role.OWNER,
        )

        if chat.type == Chat.Type.GROUP:
            requested = form.cleaned_data["members"]
            member_query = Q()
            for username in requested:
                member_query |= Q(username__iexact=username)
            users = (
                list(
                    User.objects.filter(member_query, is_active=True)
                    .exclude(pk=request.user.pk)
                )
                if requested
                else []
            )
            users = [
                user
                for user in users
                if not is_blocked_between(request.user, user)
                and privacy_allows(user, request.user, "invites")
            ]
            known_ids = set(Contact.objects.filter(
                user=request.user, owner__in=users,
            ).values_list("owner_id", flat=True))
            ChatParticipant.objects.bulk_create(
                [
                    ChatParticipant(
                        chat=chat,
                        user=user,
                        role=ChatParticipant.Role.MEMBER,
                        **invited_membership_defaults(request.user, user, user.pk in known_ids),
                    )
                    for user in users
                ],
                ignore_conflicts=True,
            )

    redirect_url = reverse("messenger:chat", args=[chat.pk])
    if _wants_json(request):
        return JsonResponse(
            {
                "ok": True,
                "chat_id": chat.pk,
                "redirect_url": redirect_url,
            }
        )

    messages.success(
        request,
        "Канал создан." if chat.type == Chat.Type.CHANNEL else "Группа создана.",
    )
    return redirect(redirect_url)


@login_required
@require_POST
def join_public_chat(request, username):
    with transaction.atomic():
        chat = get_object_or_404(
            Chat.objects.select_for_update(),
            username__iexact=username,
            type__in=(Chat.Type.GROUP, Chat.Type.CHANNEL),
        )
        if is_banned(chat, request.user.pk):
            messages.error(request, "Вы заблокированы в этом сообществе.")
            return redirect("messenger:home")
        membership, created = ChatParticipant.objects.get_or_create(
            chat=chat,
            user=request.user,
            defaults={
                "role": ChatParticipant.Role.MEMBER,
                "can_see_pre_join_history": chat.history_visible_to_new_members,
            },
        )
        if not created and membership.is_hidden:
            # Rejoining a hidden chat preserves the clear-history watermark.
            ChatParticipant.objects.filter(pk=membership.pk).update(is_hidden=False)
        ChatJoinRequest.objects.filter(chat=chat, user=request.user, status=ChatJoinRequest.Status.PENDING).update(
            status=ChatJoinRequest.Status.APPROVED, decided_at=timezone.now(),
        )
    return redirect("messenger:chat", chat_id=chat.pk)


@login_required
@require_POST
def start_chat(request, username):
    if request.POST.get("account_id", str(request.user.pk)) != str(request.user.pk):
        return JsonResponse({"ok": False, "error": "Аккаунт изменился. Обновите страницу."}, status=409)
    target = get_object_or_404(User, username__iexact=username, is_active=True)
    if target.pk != request.user.pk:
        if is_blocked_between(request.user, target):
            if _wants_json(request):
                return JsonResponse(
                    {"ok": False, "error": "Диалог недоступен из-за блокировки."},
                    status=403,
                )
            messages.error(request, "Диалог недоступен из-за блокировки.")
            return redirect("messenger:home")
        if not privacy_allows(target, request.user, "messages"):
            if _wants_json(request):
                return JsonResponse(
                    {
                        "ok": False,
                        "error": "Пользователь ограничил входящие личные сообщения.",
                    },
                    status=403,
                )
            messages.error(request, "Пользователь ограничил входящие личные сообщения.")
            return redirect("messenger:home")

    chat = get_or_create_direct_chat(request.user, target)
    ChatParticipant.objects.filter(chat=chat, user=request.user).update(
        is_hidden=False,
    )
    return redirect("messenger:chat", chat_id=chat.pk)



@login_required
@require_GET
@rate_limit("global_search")
def global_search(request):
    query = request.GET.get("q", "").strip()[:120]
    if not query:
        return JsonResponse(
            {
                "ok": True,
                "query": "",
                "chats": [],
                "people": [],
                "communities": [],
                "messages": [],
                "next_before": None,
            }
        )

    normalized = query.lower().lstrip("@")
    aliases = contact_aliases(request.user)
    alias_matches = [pk for pk, alias in aliases.items() if normalized in alias.casefold()]
    active_folder = requested_folder(request.user, request.GET.get("folder"))
    archive_only = request.GET.get("archived") == "1" and not active_folder
    membership_scope = {"is_archived": True} if archive_only else {}
    message_scope = {"chat__memberships__is_archived": True} if archive_only else {}
    if active_folder:
        ids = [chat.pk for chat in _folder_sidebar_context(request.user, raw_folder=active_folder.pk)["chats"]]
        membership_scope = {"chat_id__in": ids}
        message_scope = {"chat_id__in": ids}
    messages_only = request.GET.get("messages_only") == "1"
    try:
        before = _search_before(request)
    except ValueError:
        return JsonResponse({"ok": False, "error": "Некорректный курсор поиска."}, status=400)

    membership_base = ChatParticipant.objects.filter(
        user=request.user, is_hidden=False, **membership_scope,
    )
    joined_ids = membership_base.values("chat_id")
    chat_results = []
    if not messages_only:
        # Match against every accessible chat before limiting the result set.
        # A scalar subquery avoids loading every member of every group.
        peer_name = (
            User.objects.filter(chat_memberships__chat_id=OuterRef("chat_id"))
            .exclude(pk=request.user.pk)
            .annotate(search_name=Concat(
                Trim(Concat("first_name", Value(" "), "last_name")), Value(" "), "username", Value(" "),
                Coalesce(Subquery(Contact.objects.filter(owner=request.user, user_id=OuterRef("pk"))
                                  .values("alias")[:1]), Value("")),
                output_field=TextField(),
            ))
            .order_by("pk").values("search_name")[:1]
        )
        candidates = membership_base.annotate(
            search_name=Case(
                When(chat__type=Chat.Type.PRIVATE, chat__direct_key=f"self:{request.user.pk}", then=Value("Избранное")),
                When(chat__type=Chat.Type.PRIVATE, then=Coalesce(Subquery(peer_name), Value(""), output_field=TextField())),
                default=Concat(
                    Case(
                        When(chat__title="", chat__type=Chat.Type.CHANNEL, then=Value("Канал")),
                        When(chat__title="", then=Value("Группа")),
                        default=F("chat__title"), output_field=TextField(),
                    ),
                    Value(" "), Coalesce("chat__username", Value("")), output_field=TextField(),
                ),
                output_field=TextField(),
            ),
        ).order_by("-is_pinned", "-pin_order", "-chat__updated_at", "-pk")
        if connection.vendor == "sqlite":
            # SQLite LIKE only folds ASCII; preserve Cyrillic/Unicode names.
            ids = list(islice((pk for pk, name in candidates.values_list("pk", "search_name").iterator(chunk_size=200)
                               if normalized in (name or "").lower()), 12))
            matched = candidates.filter(pk__in=ids)
        else:
            matched = candidates.filter(search_name__icontains=normalized)
        memberships = list(matched.select_related("chat").prefetch_related("chat__participants")[:12])
        collective_ids = [m.chat_id for m in memberships if m.chat.type != Chat.Type.PRIVATE]
        collective_counts = dict(
            ChatParticipant.objects.filter(chat_id__in=collective_ids)
            .values("chat_id").annotate(total=Count("id")).values_list("chat_id", "total")
        )
        for membership in memberships:
            chat = membership.chat
            if chat.type != Chat.Type.PRIVATE:
                chat.member_count_ui = collective_counts.get(chat.pk, 0)
            _decorate_chat_ui(chat, request.user, aliases)
            chat_results.append({
                "id": chat.pk,
                "type": chat.type,
                "avatar_kind": "user" if chat.type == Chat.Type.PRIVATE and not chat.is_saved_ui else "chat",
                "avatar_id": chat.other_user.pk if chat.type == Chat.Type.PRIVATE and not chat.is_saved_ui else chat.pk,
                "title": chat.display_name_ui,
                "username": chat.username_ui,
                "status": chat.status_ui,
                "avatar_url": chat.other_user_avatar_url_ui if chat.type == Chat.Type.PRIVATE and chat.other_user else chat.avatar.url if chat.type != Chat.Type.PRIVATE and chat.avatar else "",
                "avatar_text": chat.avatar_text_ui,
                "url": reverse("messenger:chat", args=[chat.pk]) + (f"?folder={active_folder.pk}" if active_folder else ""),
                "is_archived": membership.is_archived,
            })

    people = [] if messages_only or archive_only or active_folder else list(
        User.objects.filter(is_active=True)
        .exclude(pk=request.user.pk)
        .filter(
            Q(username__icontains=normalized)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(pk__in=alias_matches)
        )
        .order_by("-last_seen_at", "username")[:10]
    )
    people_results = [
        {
            "id": user.pk,
            "avatar_kind": "user",
            "avatar_id": user.pk,
            "display_name": contact_display_name(request.user, user, aliases),
            "username": user.username,
            "avatar_url": (
                user.avatar_url
                if user.avatar and privacy_allows(user, request.user, "profile_photo")
                else ""
            ),
            "avatar_text": user.initials,
            "status": _presence_text(user, request.user),
            "profile_url": reverse(
                "accounts:public_profile",
                args=[user.username],
            ),
        }
        for user in people
    ]

    communities = [] if messages_only or archive_only or active_folder else list(
        Chat.objects.filter(
            type__in=(Chat.Type.GROUP, Chat.Type.CHANNEL),
        )
        .exclude(username__isnull=True)
        .exclude(username="")
        .exclude(pk__in=joined_ids)
        .filter(
            Q(username__icontains=normalized)
            | Q(title__icontains=query)
        )
        .annotate(member_count_ui=Count("memberships"))
        .order_by("title", "username")[:10]
    )
    community_results = [
        {
            "id": chat.pk,
            "type": chat.type,
            "avatar_kind": "chat",
            "avatar_id": chat.pk,
            "title": chat.title or (
                "Канал" if chat.type == Chat.Type.CHANNEL else "Группа"
            ),
            "username": chat.username or "",
            "avatar_url": chat.avatar.url if chat.avatar else "",
            "avatar_text": "К" if chat.type == Chat.Type.CHANNEL else "Г",
            "status": (
                f"канал · {chat.member_count_ui} подписчик(ов)"
                if chat.type == Chat.Type.CHANNEL
                else f"группа · {chat.member_count_ui} участник(ов)"
            ),
            "join_url": reverse(
                "messenger:join_public_chat",
                args=[chat.username],
            ),
        }
        for chat in communities
    ]

    message_results = []
    message_query = (
        Message.objects.filter(
            Q(id__gt=F("chat__memberships__cleared_before_message_id")),
            (
                Q(chat__type=Chat.Type.PRIVATE)
                | Q(chat__history_visible_to_new_members=True)
                | Q(chat__memberships__can_see_pre_join_history=True)
                | Q(created_at__gte=F("chat__memberships__joined_at"))
            ),
            _search_text_condition(query),
            chat__memberships__user=request.user,
            chat__memberships__is_hidden=False,
            is_deleted=False,
            **message_scope,
        )
        .exclude(hidden_for_users__user=request.user)
        .select_related("sender", "chat")
        .distinct()
    )
    search_matches, next_before = _search_page(message_query, before, 18)
    chat_by_id = {}
    for message in search_matches:
        chat = message.chat
        decorated = chat_by_id.get(chat.pk)
        if decorated is None:
            _decorate_chat_ui(chat, request.user, aliases)
            decorated = chat
            chat_by_id[chat.pk] = chat
        message_results.append({
            "id": message.pk,
            "chat_id": chat.pk,
            "chat_title": decorated.display_name_ui,
            "sender_name": message.sender.display_name,
            "preview": message.preview[:180],
            "time": timezone.localtime(message.created_at).strftime("%d.%m.%Y %H:%M"),
            "url": (
                f"{reverse('messenger:chat', args=[chat.pk])}?message={message.pk}"
                + (f"&folder={active_folder.pk}" if active_folder else "")
                + f"#message-{message.pk}"
            ),
        })

    return JsonResponse(
        {
            "ok": True,
            "query": query,
            "chats": chat_results,
            "people": people_results,
            "communities": community_results,
            "messages": message_results,
            "next_before": next_before,
        }
    )


@login_required
def contacts(request):
    query = request.GET.get("q", "").strip().lstrip("@")[:150]
    contact_links = list(
        Contact.objects.filter(owner=request.user)
        .select_related("user")
        .order_by("user__username")
    )
    contact_ids = {item.user_id for item in contact_links}
    aliases = {item.user_id: item.alias for item in contact_links if item.alias}
    contact_links.sort(key=lambda item: (item.alias or item.user.display_name).casefold())
    for item in contact_links:
        item.display_name_ui = item.alias or item.user.display_name
        item.avatar_url_ui = (
            item.user.avatar_url
            if item.user.avatar and privacy_allows(item.user, request.user, "profile_photo")
            else ""
        )
        item.can_message_ui = (
            not is_blocked_between(request.user, item.user)
            and privacy_allows(item.user, request.user, "messages")
        )

    user_results = []
    channel_results = []
    if query:
        user_results = list(
            User.objects.filter(is_active=True).filter(
                Q(username__icontains=query) |
                Q(pk__in=[pk for pk, alias in aliases.items() if query.casefold() in alias.casefold()])
            ).exclude(pk=request.user.pk)
            .order_by("username")[:30]
        )
        for user in user_results:
            user.is_contact_ui = user.pk in contact_ids
            user.display_name_ui = contact_display_name(request.user, user, aliases)
            user.avatar_url_ui = (
                user.avatar_url
                if user.avatar and privacy_allows(user, request.user, "profile_photo")
                else ""
            )
            user.can_message_ui = (
                not is_blocked_between(request.user, user)
                and privacy_allows(user, request.user, "messages")
            )

        channel_results = list(
            Chat.objects.filter(
                type__in=(Chat.Type.GROUP, Chat.Type.CHANNEL),
            )
            .exclude(username__isnull=True)
            .filter(
                Q(username__icontains=query)
                | Q(title__icontains=query)
            )
            .order_by("username")[:30]
        )
        joined_chat_ids = set(
            ChatParticipant.objects.filter(user=request.user).values_list(
                "chat_id", flat=True
            )
        )
        for channel in channel_results:
            channel.is_joined_ui = channel.pk in joined_chat_ids

    return render(
        request,
        "messenger/contacts.html",
        {
            "contacts": contact_links,
            "query": query,
            "search_results": user_results,
            "channel_results": channel_results,
            "focus_search": request.GET.get("focus") == "search",
        },
    )


@login_required
@require_POST
def add_contact(request, username):
    if request.POST.get("account_id", str(request.user.pk)) != str(request.user.pk):
        return JsonResponse({"ok": False, "error": "Аккаунт изменился. Обновите страницу."}, status=409)
    target = get_object_or_404(User, username__iexact=username, is_active=True)
    if target.pk != request.user.pk:
        Contact.objects.get_or_create(owner=request.user, user=target)

    if _wants_json(request):
        return JsonResponse({"ok": True, "is_contact": target.pk != request.user.pk})

    if target.pk != request.user.pk:
        messages.success(request, f"@{target.username} добавлен в контакты.")
    return redirect(_safe_next(request, reverse("messenger:contacts")))


@login_required
@require_POST
def remove_contact(request, username):
    if request.POST.get("account_id", str(request.user.pk)) != str(request.user.pk):
        return JsonResponse({"ok": False, "error": "Аккаунт изменился. Обновите страницу."}, status=409)
    target = get_object_or_404(User, username__iexact=username, is_active=True)
    Contact.objects.filter(owner=request.user, user=target).delete()

    if _wants_json(request):
        return JsonResponse({"ok": True, "is_contact": False})

    messages.success(request, f"@{target.username} удалён из контактов.")
    return redirect(_safe_next(request, reverse("messenger:contacts")))


@login_required
@require_POST
@rate_limit("chat_list_action")
def rename_contact(request, username):
    if request.POST.get("account_id", str(request.user.pk)) != str(request.user.pk):
        return JsonResponse({"ok": False, "error": "Аккаунт изменился. Обновите страницу."}, status=409)
    target = get_object_or_404(User, username__iexact=username, is_active=True)
    try:
        alias = normalize_alias(request.POST.get("alias", ""))
    except ValueError as error:
        return JsonResponse({"ok": False, "error": str(error)}, status=400)
    if target.pk == request.user.pk or not Contact.objects.filter(owner=request.user, user=target).update(alias=alias):
        return JsonResponse({"ok": False, "error": "Сначала добавьте пользователя в контакты."}, status=404)
    response = JsonResponse({"ok": True, "contact_alias": alias,
                             "contact_name": alias or target.display_name,
                             "message": "Имя контакта сохранено."})
    response["Cache-Control"] = "private, no-store"
    return response


def _send_request_digest(request):
    # Bind an idempotency key to the exact operation, fields and file bytes.
    fields = [(key, request.POST.getlist(key)) for key in sorted(request.POST)
              if key not in {"csrfmiddlewaretoken", "client_message_id"}]
    digest = hashlib.sha256(json.dumps(
        [request.path, fields], ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8"))
    for key in sorted(request.FILES):
        for uploaded in request.FILES.getlist(key):
            metadata = [key, uploaded.name, uploaded.size, uploaded.content_type]
            digest.update(json.dumps(metadata, ensure_ascii=False).encode("utf-8"))
            for chunk in uploaded.chunks():
                digest.update(chunk)
            uploaded.seek(0)
    return digest.hexdigest()


def idempotent_send(view):
    """Serialize keyed sends by sender; commit message and receipt together."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        account_id = request.POST.get("account_id")
        if account_id is not None and account_id != str(request.user.pk):
            return JsonResponse({"ok": False, "error": "Аккаунт изменился. Обновите страницу."}, status=409)
        raw = request.POST.get("client_message_id", "")
        if not raw:
            # Backwards-compatible with older clients and non-JS forms.
            return view(request, *args, **kwargs)
        try:
            client_id = UUID(raw)
        except (ValueError, TypeError, AttributeError):
            return JsonResponse({"ok": False, "error": "Некорректный идентификатор отправки."}, status=400)
        if not _wants_json(request):
            return JsonResponse({"ok": False, "error": "Требуется JSON-ответ."}, status=400)
        digest = _send_request_digest(request)
        with transaction.atomic():
            get_user_model().objects.select_for_update().only("id").get(pk=request.user.pk)
            receipt = MessageSendReceipt.objects.filter(sender=request.user, client_id=client_id).first()
            if receipt:
                if receipt.request_digest != digest:
                    return JsonResponse({"ok": False, "error": "Идентификатор уже использован для другой отправки."}, status=409)
                if receipt.message_id is None:
                    return JsonResponse({"ok": False, "error": "Сообщение было отправлено, но уже удалено."}, status=409)
                original = receipt.message
                chat = _chat_for_user(request.user, original.chat_id)
                message = _visible_message_queryset(chat, request.user).filter(pk=original.pk, is_deleted=False).first()
                if message is None:
                    return JsonResponse({"ok": False, "error": "Сообщение было отправлено, но больше недоступно."}, status=409)
                _hide_inaccessible_reply_previews(chat, request.user, [message])
                return JsonResponse({
                    "ok": True,
                    "message": _serialized_message(message, request.user, chat),
                    "target_chat_id": chat.pk,
                    "target_url": reverse("messenger:chat", args=[chat.pk]),
                    "replayed": True,
                })
            response = view(request, *args, **kwargs)
            if 200 <= response.status_code < 300:
                payload = json.loads(response.content)
                if payload.get("ok") and payload.get("message"):
                    MessageSendReceipt.objects.create(
                        sender=request.user, client_id=client_id, request_digest=digest,
                        message_id=payload["message"]["id"],
                    )
            return response
    return wrapped


@login_required
@require_POST
@idempotent_send
@rate_limit("send_message")
def send_message(request, chat_id):
    chat = _chat_for_user(request.user, chat_id)
    membership = _membership(chat, request.user)
    form = MessageForm(request.POST, request.FILES)
    wants_json = _wants_json(request)

    if not form.is_valid():
        if wants_json:
            return JsonResponse({"ok": False, "errors": form.errors.get_json_data()}, status=400)
        for error in form.non_field_errors():
            messages.error(request, error)
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect("messenger:chat", chat_id=chat.pk)

    sticker_id = form.cleaned_data.get("sticker_id")
    sticker = None
    if sticker_id:
        if request.POST.get("account_id") != str(request.user.pk):
            return JsonResponse({"ok": False, "error": "Аккаунт изменился. Обновите страницу."}, status=409)
        sticker = Sticker.objects.filter(pk=sticker_id, pack__owner=request.user).first()
        if sticker is None:
            return JsonResponse({"ok": False, "error": "Стикер недоступен."}, status=404)

    if chat.type == Chat.Type.PRIVATE and chat.direct_key != f"self:{request.user.pk}":
        recipient = other_user_for_chat(chat, request.user)
        if is_blocked_between(request.user, recipient):
            error = "Сообщение не отправлено: один из пользователей заблокировал другого."
            if wants_json:
                return JsonResponse({"ok": False, "error": error}, status=403)
            messages.error(request, error)
            return redirect("messenger:chat", chat_id=chat.pk)
        if not privacy_allows(recipient, request.user, "messages"):
            error = "Пользователь ограничил входящие личные сообщения."
            if wants_json:
                return JsonResponse({"ok": False, "error": error}, status=403)
            messages.error(request, error)
            return redirect("messenger:chat", chat_id=chat.pk)

        attachment_mode = form.cleaned_data.get("attachment_mode") or MessageForm.MODE_MEDIA
        if (
            attachment_mode == MessageForm.MODE_VOICE
            and form.cleaned_data["attachments"]
            and not privacy_allows(recipient, request.user, "voice_messages")
        ):
            error = "Пользователь ограничил входящие голосовые сообщения."
            if wants_json:
                return JsonResponse({"ok": False, "error": error}, status=403)
            messages.error(request, error)
            return redirect("messenger:chat", chat_id=chat.pk)

    restriction = _posting_restriction(
        chat,
        membership,
        text=form.cleaned_data["text"],
        has_attachments=bool(form.cleaned_data["attachments"] or sticker),
    )
    if restriction:
        error, retry_after = restriction
        if wants_json:
            response = JsonResponse({"ok": False, "error": error}, status=403)
            if retry_after:
                response["Retry-After"] = str(retry_after)
            return response
        messages.error(request, error)
        return redirect("messenger:chat", chat_id=chat.pk)

    reply_to = None
    reply_id = form.cleaned_data.get("reply_to")
    if reply_id:
        reply_to = _visible_message_queryset(chat, request.user).filter(
            pk=reply_id,
            is_deleted=False,
        ).first()
        if reply_to is None:
            payload = {"ok": False, "errors": {"reply_to": [{"message": "Сообщение для ответа больше недоступно."}]}}
            if wants_json:
                return JsonResponse(payload, status=400)
            messages.error(request, "Сообщение для ответа больше недоступно.")
            return redirect("messenger:chat", chat_id=chat.pk)

    attachment_mode = form.cleaned_data.get("attachment_mode") or MessageForm.MODE_MEDIA
    send_as_file = attachment_mode == MessageForm.MODE_FILE
    send_as_audio = attachment_mode == MessageForm.MODE_AUDIO
    send_as_voice = attachment_mode == MessageForm.MODE_VOICE

    with transaction.atomic():
        # Allocate IDs under the chat row lock so a later ID cannot become
        # visible to polling before an earlier send in the same chat commits.
        chat = Chat.objects.select_for_update().get(pk=chat.pk)
        membership = ChatParticipant.objects.filter(chat=chat, user=request.user, is_hidden=False).first()
        if membership is None:
            raise Http404
        restriction = _posting_restriction(chat, membership, text=form.cleaned_data["text"],
                                           has_attachments=bool(form.cleaned_data["attachments"] or sticker))
        if restriction:
            if wants_json:
                response = JsonResponse({"ok": False, "error": restriction[0]}, status=403)
                if restriction[1]:
                    response["Retry-After"] = str(restriction[1])
                return response
            messages.error(request, restriction[0])
            return redirect("messenger:chat", chat_id=chat.pk)
        message = Message.objects.create(
            chat=chat,
            sender=request.user,
            text=form.cleaned_data["text"],
            silent=form.cleaned_data["silent"],
            reply_to=reply_to,
            signature_name=(
                request.user.display_name
                if chat.type == Chat.Type.CHANNEL and chat.signatures_enabled
                else ""
            ),
        )
        if sticker:
            # Copy into the message's protected attachment storage. Removing a
            # sticker or its pack must not change messages already sent.
            image = bytes(sticker.image)
            MessageAttachment.objects.create(
                message=message, file=ContentFile(image, name="sticker.webp"),
                kind=MessageAttachment.Kind.STICKER, original_name="sticker.webp",
                mime_type="image/webp", size=len(image),
            )
            Sticker.objects.filter(pk=sticker.pk, pack__owner=request.user).update(last_used_at=timezone.now())
        for uploaded in form.cleaned_data["attachments"]:
            if attachment_mode == MessageForm.MODE_MEDIA and form.cleaned_data["compress_images"]:
                uploaded = compress_image_upload(uploaded)
            MessageAttachment.objects.create(
                message=message,
                file=uploaded,
                kind=(
                    MessageAttachment.Kind.FILE
                    if send_as_file
                    else MessageAttachment.Kind.VOICE
                    if send_as_voice
                    else MessageAttachment.Kind.AUDIO
                    if send_as_audio
                    else attachment_kind(uploaded)
                ),
                original_name=Path(uploaded.name).name[:255],
                mime_type=(getattr(uploaded, "content_type", "") or "")[:127],
                size=uploaded.size,
                duration_ms=(
                    int(form.cleaned_data.get("voice_duration_ms") or 0)
                    if send_as_voice
                    else 0
                ),
                waveform=(
                    list(form.cleaned_data.get("voice_waveform") or [])
                    if send_as_voice
                    else []
                ),
            )
        touch_chat(chat)
        apply_archive_rules_on_new_message(chat, message)
        if sticker or request.POST.get("preserve_draft") == "1":
            # Queued text may arrive after the author has started a different
            # draft. Do not clear that draft on the server as a side effect.
            ChatParticipant.objects.filter(chat=chat, user=request.user).update(is_hidden=False)
        else:
            ChatParticipant.objects.filter(chat=chat, user=request.user).update(
                is_hidden=False,
                draft_text="",
                draft_updated_at=None,
                last_typing_at=None,
            )

    message = _base_message_queryset(chat).get(pk=message.pk)
    if wants_json:
        return JsonResponse({"ok": True, "message": _serialized_message(message, request.user, chat)})
    return redirect("messenger:chat", chat_id=chat.pk)


@login_required
@require_POST
@idempotent_send
@rate_limit("send_message")
def send_special_message(request, chat_id):
    chat = _chat_for_user(request.user, chat_id)
    membership = _membership(chat, request.user)
    special_type = request.POST.get("special_type", "").strip()

    try:
        raw_payload = json.loads(request.POST.get("payload", "{}"))
        special_data, search_text = _clean_special_payload(
            special_type,
            raw_payload,
        )
    except (json.JSONDecodeError, ValueError) as error:
        return JsonResponse(
            {"ok": False, "error": str(error)},
            status=400,
        )

    if chat.type == Chat.Type.PRIVATE and chat.direct_key != f"self:{request.user.pk}":
        recipient = other_user_for_chat(chat, request.user)
        if is_blocked_between(request.user, recipient):
            return JsonResponse(
                {"ok": False, "error": "Сообщение не отправлено: один из пользователей заблокировал другого."},
                status=403,
            )
        if not privacy_allows(recipient, request.user, "messages"):
            return JsonResponse(
                {"ok": False, "error": "Пользователь ограничил входящие личные сообщения."},
                status=403,
            )

    restriction = _posting_restriction(
        chat,
        membership,
        text=_special_restriction_text(special_type, special_data, search_text),
        has_attachments=False,
    )
    if restriction:
        response = JsonResponse(
            {"ok": False, "error": restriction[0]},
            status=403,
        )
        if restriction[1]:
            response["Retry-After"] = str(restriction[1])
        return response

    reply_to = None
    raw_reply = request.POST.get("reply_to", "").strip()
    if raw_reply:
        try:
            reply_id = int(raw_reply)
        except (TypeError, ValueError):
            reply_id = 0
        if reply_id:
            reply_to = _visible_message_queryset(
                chat,
                request.user,
            ).filter(
                pk=reply_id,
                is_deleted=False,
            ).first()

    with transaction.atomic():
        # Allocate IDs under the chat row lock so a later ID cannot become
        # visible to polling before an earlier send in the same chat commits.
        chat = Chat.objects.select_for_update().get(pk=chat.pk)
        membership = ChatParticipant.objects.filter(chat=chat, user=request.user, is_hidden=False).first()
        if membership is None:
            raise Http404
        restriction = _posting_restriction(chat, membership,
            text=_special_restriction_text(special_type, special_data, search_text))
        if restriction:
            response = JsonResponse({"ok": False, "error": restriction[0]}, status=403)
            if restriction[1]:
                response["Retry-After"] = str(restriction[1])
            return response
        message = Message.objects.create(
            chat=chat,
            sender=request.user,
            text=search_text,
            reply_to=reply_to,
            special_type=special_type,
            special_data=special_data,
            signature_name=(
                request.user.display_name
                if chat.type == Chat.Type.CHANNEL
                and chat.signatures_enabled
                else ""
            ),
        )
        touch_chat(chat)
        apply_archive_rules_on_new_message(chat, message)
        ChatParticipant.objects.filter(
            chat=chat,
            user=request.user,
        ).update(
            is_hidden=False,
            draft_text="",
            draft_updated_at=None,
            last_typing_at=None,
        )

    message = _base_message_queryset(chat).get(pk=message.pk)
    return JsonResponse(
        {
            "ok": True,
            "message": _serialized_message(
                message,
                request.user,
                chat,
            ),
        }
    )


@login_required
@require_POST
@transaction.atomic
def special_message_action(request, chat_id, message_id):
    chat = _chat_for_user(request.user, chat_id)
    chat = get_object_or_404(Chat.objects.select_for_update(), pk=chat.pk)
    get_object_or_404(ChatParticipant, chat=chat, user=request.user, is_hidden=False)
    membership = _membership(chat, request.user)
    action = request.POST.get("action", "").strip()

    with transaction.atomic():
        message = get_object_or_404(
            Message.objects.select_for_update().filter(
                chat=chat,
                pk=message_id,
                is_deleted=False,
            )
        )
        if not _visible_message_queryset(
            chat,
            request.user,
        ).filter(pk=message.pk).exists():
            raise Http404

        data = copy.deepcopy(message.special_data or {})

        if message.special_type == Message.SpecialType.POLL:
            if action == "close":
                if not (
                    message.sender_id == request.user.pk
                    or has_admin_right(membership, "edit_messages")
                ):
                    return JsonResponse(
                        {
                            "ok": False,
                            "error": "Завершить опрос может автор или администратор.",
                        },
                        status=403,
                    )
                data["closed"] = True
                message.special_data = data
                message.save(update_fields=("special_data", "updated_at"))
            elif action == "vote":
                if data.get("closed"):
                    return JsonResponse(
                        {"ok": False, "error": "Опрос уже завершён."},
                        status=400,
                    )
                try:
                    chosen = json.loads(request.POST.get("options", "[]"))
                except json.JSONDecodeError:
                    chosen = []
                if not isinstance(chosen, list):
                    chosen = []
                indexes = []
                for value in chosen:
                    try:
                        index = int(value)
                    except (TypeError, ValueError):
                        continue
                    if index not in indexes:
                        indexes.append(index)

                options = data.get("options") or []
                indexes = [
                    index
                    for index in indexes
                    if 0 <= index < len(options)
                ]
                if not indexes:
                    return JsonResponse(
                        {"ok": False, "error": "Выберите вариант ответа."},
                        status=400,
                    )
                if data.get("quiz") or not data.get("multiple"):
                    indexes = indexes[:1]

                if data.get("quiz"):
                    previous = [
                        index for index, option in enumerate(options)
                        if any(str(value) == str(request.user.pk) for value in option.get("voters") or [])
                    ]
                    if previous and previous != indexes:
                        return JsonResponse(
                            {"ok": False, "error": "Ответ в викторине нельзя изменить."},
                            status=409,
                        )

                for option in options:
                    cleaned = []
                    for user_id in option.get("voters") or []:
                        try:
                            normalized_user_id = int(user_id)
                        except (TypeError, ValueError):
                            continue
                        if normalized_user_id != request.user.pk:
                            cleaned.append(normalized_user_id)
                    option["voters"] = cleaned
                for index in indexes:
                    voters = options[index].setdefault("voters", [])
                    voters.append(request.user.pk)
                data["options"] = options
                message.special_data = data
                message.save(update_fields=("special_data", "updated_at"))
            else:
                return JsonResponse(
                    {"ok": False, "error": "Неизвестное действие опроса."},
                    status=400,
                )

        elif message.special_type == Message.SpecialType.TODO:
            tasks = data.get("tasks") or []
            is_author = message.sender_id == request.user.pk

            if action == "toggle":
                if not (
                    is_author
                    or bool(data.get("allow_others_mark", True))
                ):
                    return JsonResponse(
                        {
                            "ok": False,
                            "error": "Автор запретил другим отмечать задачи.",
                        },
                        status=403,
                    )
                try:
                    index = int(request.POST.get("index", "-1"))
                except (TypeError, ValueError):
                    index = -1
                if index < 0 or index >= len(tasks):
                    return JsonResponse(
                        {"ok": False, "error": "Задача не найдена."},
                        status=404,
                    )
                task = tasks[index]
                task["done"] = not bool(task.get("done", False))
                task["done_by"] = (
                    request.user.pk
                    if task["done"]
                    else None
                )
            elif action == "add":
                if not (
                    is_author
                    or bool(data.get("allow_others_add", False))
                ):
                    return JsonResponse(
                        {
                            "ok": False,
                            "error": "Автор запретил добавлять новые задачи.",
                        },
                        status=403,
                    )
                text_value = request.POST.get("text", "").strip()[:160]
                if not text_value:
                    return JsonResponse(
                        {"ok": False, "error": "Введите текст задачи."},
                        status=400,
                    )
                restriction = _posting_restriction(
                    chat, membership, text=text_value, check_slow_mode=False,
                )
                if restriction:
                    return JsonResponse(
                        {"ok": False, "error": restriction[0]},
                        status=403,
                    )
                if len(tasks) >= 30:
                    return JsonResponse(
                        {
                            "ok": False,
                            "error": "В списке уже максимальное число задач.",
                        },
                        status=400,
                    )
                tasks.append(
                    {
                        "text": text_value,
                        "done": False,
                        "done_by": None,
                    }
                )
            else:
                return JsonResponse(
                    {"ok": False, "error": "Неизвестное действие списка задач."},
                    status=400,
                )

            data["tasks"] = tasks
            message.special_data = data
            message.save(update_fields=("special_data", "updated_at"))
        elif message.special_type == Message.SpecialType.ARTICLE:
            if action != "edit":
                return JsonResponse(
                    {"ok": False, "error": "Неизвестное действие статьи."},
                    status=400,
                )
            can_edit = message.sender_id == request.user.pk
            if (
                not can_edit
                and chat.type != Chat.Type.PRIVATE
                and has_admin_right(membership, "edit_messages")
            ):
                can_edit = True
            if not can_edit:
                return JsonResponse(
                    {"ok": False, "error": "У вас нет права редактировать эту статью."},
                    status=403,
                )
            try:
                raw_payload = json.loads(request.POST.get("payload", "{}"))
                article_data, search_text = _clean_special_payload(
                    Message.SpecialType.ARTICLE,
                    raw_payload,
                )
            except (json.JSONDecodeError, ValueError) as error:
                return JsonResponse(
                    {"ok": False, "error": str(error)},
                    status=400,
                )
            restriction = _posting_restriction(
                chat, membership,
                text=_special_restriction_text(
                    Message.SpecialType.ARTICLE, article_data, search_text,
                ),
                check_slow_mode=False,
            )
            if restriction:
                return JsonResponse(
                    {"ok": False, "error": restriction[0]},
                    status=403,
                )
            message.special_data = article_data
            message.text = search_text
            message.edited_at = timezone.now()
            message.save(
                update_fields=(
                    "special_data",
                    "text",
                    "edited_at",
                    "updated_at",
                )
            )
            touch_chat(chat)
        else:
            return JsonResponse(
                {
                    "ok": False,
                    "error": "У этого сообщения нет интерактивных действий.",
                },
                status=400,
            )

    message = _base_message_queryset(chat).get(pk=message.pk)
    return JsonResponse(
        {
            "ok": True,
            "message": _serialized_message(
                message,
                request.user,
                chat,
            ),
        }
    )


@login_required
@require_POST
@transaction.atomic
def edit_message(request, chat_id, message_id):
    chat = _chat_for_user(request.user, chat_id)
    chat = get_object_or_404(Chat.objects.select_for_update(), pk=chat.pk)
    get_object_or_404(ChatParticipant, chat=chat, user=request.user, is_hidden=False)
    message = get_object_or_404(
        _visible_message_queryset(chat, request.user),
        pk=message_id,
        sender=request.user,
        is_deleted=False,
    )
    if message.attachments.filter(kind=MessageAttachment.Kind.STICKER).exists():
        return JsonResponse({"ok": False, "error": "Стикеры нельзя редактировать."}, status=400)
    if message.special_type:
        return JsonResponse(
            {
                "ok": False,
                "error": "Структурированные вложения редактируются через их собственные действия.",
            },
            status=400,
        )
    form = EditMessageForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"ok": False, "errors": form.errors.get_json_data()}, status=400)

    text = form.cleaned_data["text"]
    edit_restriction = _posting_restriction(
        chat,
        _membership(chat, request.user),
        text=text,
        has_attachments=message.attachments.exists(),
        check_slow_mode=False,
    )
    if edit_restriction:
        return JsonResponse(
            {"ok": False, "error": edit_restriction[0]},
            status=403,
        )
    if not text and not message.attachments.exists():
        return JsonResponse(
            {"ok": False, "errors": {"text": [{"message": "Текстовое сообщение не может быть пустым."}]}},
            status=400,
        )

    message.text = text
    message.edited_at = timezone.now()
    message.save(update_fields=("text", "edited_at", "updated_at"))
    message = _base_message_queryset(chat).get(pk=message.pk)
    return JsonResponse({"ok": True, "message": _serialized_message(message, request.user, chat)})


@login_required
@require_POST
@transaction.atomic
def delete_message(request, chat_id, message_id):
    account_id = request.POST.get("account_id")
    if account_id is not None and account_id != str(request.user.pk):
        return JsonResponse({"ok": False, "error": "Аккаунт изменился. Обновите страницу."}, status=409)
    chat = _chat_for_user(request.user, chat_id)
    chat = get_object_or_404(Chat.objects.select_for_update(), pk=chat.pk)
    get_object_or_404(ChatParticipant, chat=chat, user=request.user, is_hidden=False)
    membership = _membership(chat, request.user)
    message = get_object_or_404(
        _visible_message_queryset(chat, request.user),
        pk=message_id,
        is_deleted=False,
    )
    scope = request.POST.get("scope", "me").strip().lower()
    if scope not in {"me", "everyone"}:
        return JsonResponse({"ok": False, "error": "Некорректный режим удаления."}, status=400)

    if scope == "everyone":
        if not _can_delete_message_for_everyone(chat, membership, message):
            return JsonResponse(
                {
                    "ok": False,
                    "error": "У вас нет права удалить это сообщение для всех.",
                },
                status=403,
            )
        with transaction.atomic():
            delete_message_content(message)
            MessageHiddenForUser.objects.filter(message=message).delete()
        message = _base_message_queryset(chat).get(pk=message.pk)
        return JsonResponse(
            {
                "ok": True,
                "scope": "everyone",
                "message_id": message.pk,
                "message": _serialized_message(message, request.user, chat),
            }
        )

    if chat.type != Chat.Type.PRIVATE and not _can_delete_message_for_everyone(
        chat,
        membership,
        message,
    ):
        return JsonResponse(
            {
                "ok": False,
                "error": "В группах и каналах можно удалять только свои сообщения.",
            },
            status=403,
        )

    if chat.type == Chat.Type.PRIVATE:
        if chat.direct_key == f"self:{request.user.pk}":
            with transaction.atomic():
                delete_message_content(message)
                MessageHiddenForUser.objects.filter(message=message).delete()
            message = _base_message_queryset(chat).get(pk=message.pk)
            return JsonResponse(
                {
                    "ok": True,
                    "scope": "everyone",
                    "message_id": message.pk,
                    "message": _serialized_message(
                        message,
                        request.user,
                        chat,
                    ),
                }
            )

        MessageHiddenForUser.objects.get_or_create(
            message=message,
            user=request.user,
        )
        return JsonResponse(
            {
                "ok": True,
                "scope": "me",
                "message_id": message.pk,
            }
        )

    with transaction.atomic():
        delete_message_content(message)
        MessageHiddenForUser.objects.filter(message=message).delete()
    message = _base_message_queryset(chat).get(pk=message.pk)
    return JsonResponse(
        {
            "ok": True,
            "scope": "everyone",
            "message_id": message.pk,
            "message": _serialized_message(message, request.user, chat),
        }
    )


@login_required
@require_POST
@idempotent_send
@rate_limit("send_message")
def forward_message(request, chat_id, message_id):
    source_chat = _chat_for_user(request.user, chat_id)
    if source_chat.protect_content:
        return JsonResponse(
            {"ok": False, "error": "Пересылка запрещена для этой переписки."},
            status=403,
        )
    source = get_object_or_404(
        _visible_message_queryset(source_chat, request.user),
        pk=message_id,
        is_deleted=False,
    )
    # A forward is a new independent message, not a copy of other people's
    # voting identities or task-assignee metadata from the source chat.
    special_data = copy.deepcopy(source.special_data or {})
    if source.special_type == Message.SpecialType.POLL:
        if special_data.get("quiz") and source.sender_id != request.user.pk:
            if not serialize_special_content(source, request.user)["selected_indexes"]:
                return JsonResponse(
                    {"ok": False, "error": "Сначала ответьте на викторину, чтобы переслать её."},
                    status=403,
                )
        special_data["options"] = [
            {"text": option.get("text", ""), "voters": []}
            for option in special_data.get("options", [])
        ]
        special_data["closed"] = False
    elif source.special_type == Message.SpecialType.TODO:
        special_data["tasks"] = [
            {"text": task.get("text", ""), "done": bool(task.get("done")), "done_by": None}
            for task in special_data.get("tasks", [])
        ]
    hide_sender = request.POST.get("hide_sender") == "1"
    silent = request.POST.get("silent") == "1"
    raw_target = request.POST.get("target_chat_id", "").strip()

    if raw_target == "saved":
        target_chat = get_or_create_direct_chat(request.user, request.user)
    else:
        try:
            target_chat_id = int(raw_target)
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": "Выберите чат для пересылки."}, status=400)
        target_chat = _chat_for_user(request.user, target_chat_id)

    target_membership = _membership(target_chat, request.user)
    if target_chat.type == Chat.Type.PRIVATE and target_chat.direct_key != f"self:{request.user.pk}":
        recipient = other_user_for_chat(target_chat, request.user)
        if is_blocked_between(request.user, recipient):
            return JsonResponse(
                {"ok": False, "error": "Пересылка недоступна из-за блокировки."},
                status=403,
            )
        if not privacy_allows(recipient, request.user, "messages"):
            return JsonResponse(
                {"ok": False, "error": "Пользователь ограничил входящие личные сообщения."},
                status=403,
            )
        if (
            source.attachments.filter(
                kind=MessageAttachment.Kind.VOICE
            ).exists()
            and not privacy_allows(recipient, request.user, "voice_messages")
        ):
            return JsonResponse(
                {
                    "ok": False,
                    "error": "Пользователь ограничил входящие голосовые сообщения.",
                },
                status=403,
            )

    restriction = _posting_restriction(
        target_chat,
        target_membership,
        text=_special_restriction_text(
            source.special_type, source.special_data, source.text,
        ),
        has_attachments=source.attachments.exists(),
    )
    if restriction:
        response = JsonResponse({"ok": False, "error": restriction[0]}, status=403)
        if restriction[1]:
            response["Retry-After"] = str(restriction[1])
        return response

    if source.forwarded_from_name:
        # A second forward must not invent a new origin if the first forward
        # deliberately concealed the original sender.
        origin = source.forwarded_from
        origin_name = source.forwarded_from_name
        origin_username = source.forwarded_from_username
    else:
        origin = source
        origin_name = source.sender.display_name
        origin_username = source.sender.username

    if origin is None or not privacy_allows(origin.sender, request.user, "forwards"):
        origin_username = ""
    if hide_sender:
        # Keep an explicit anonymous forwarding marker so further forwards
        # cannot misattribute the original to the intermediate sender.
        origin = None
        origin_name = "Скрытый отправитель"
        origin_username = ""

    with transaction.atomic():
        target_chat = Chat.objects.select_for_update().get(pk=target_chat.pk)
        target_membership = ChatParticipant.objects.filter(chat=target_chat, user=request.user, is_hidden=False).first()
        if target_membership is None:
            raise Http404
        restriction = _posting_restriction(target_chat, target_membership,
            text=_special_restriction_text(source.special_type, source.special_data, source.text),
            has_attachments=source.attachments.exists())
        if restriction:
            response = JsonResponse({"ok": False, "error": restriction[0]}, status=403)
            if restriction[1]:
                response["Retry-After"] = str(restriction[1])
            return response
        forwarded = Message.objects.create(
            chat=target_chat,
            sender=request.user,
            text=source.text,
            special_type=source.special_type,
            special_data=special_data,
            silent=silent,
            forwarded_from=origin,
            forwarded_from_name=origin_name,
            forwarded_from_username=origin_username,
            signature_name=(
                request.user.display_name
                if target_chat.type == Chat.Type.CHANNEL
                and target_chat.signatures_enabled
                else ""
            ),
        )
        clone_attachments(source, forwarded)
        touch_chat(target_chat)
        apply_archive_rules_on_new_message(target_chat, forwarded)

    forwarded = _base_message_queryset(target_chat).get(pk=forwarded.pk)
    return JsonResponse(
        {
            "ok": True,
            "message": _serialized_message(forwarded, request.user, target_chat),
            "target_chat_id": target_chat.pk,
            "target_url": reverse("messenger:chat", args=[target_chat.pk]),
        }
    )


@login_required
@require_POST
@transaction.atomic
def pin_message(request, chat_id, message_id):
    chat = _chat_for_user(request.user, chat_id)
    chat = get_object_or_404(Chat.objects.select_for_update(), pk=chat.pk)
    get_object_or_404(ChatParticipant, chat=chat, user=request.user, is_hidden=False)
    membership = _membership(chat, request.user)
    if not can_pin_messages(chat, membership):
        return JsonResponse({"ok": False, "error": "Закрепление сообщений запрещено."}, status=403)
    message = get_object_or_404(
        _visible_message_queryset(chat, request.user),
        pk=message_id,
        is_deleted=False,
    )
    pin = PinnedMessage.objects.filter(chat=chat, message=message).first()
    if pin is None:
        PinnedMessage.objects.create(chat=chat, message=message, pinned_by=request.user)
        pinned = True
    else:
        pin.delete()
        pinned = False
    return JsonResponse({
        "ok": True,
        "pinned": pinned,
        "pins": _serialize_visible_pins(chat, request.user),
    })


def _message_search_condition(query):
    # Hashtags and mentions are literal whole tokens, not a partial word
    # or a PostgreSQL full-text query that discards punctuation.
    if re.fullmatch(r"#[\w]{1,119}", query):
        return Q(text__iregex=r"(^|[^\w#/@])" + re.escape(query) + r"(?!\w)")
    if re.fullmatch(r"@[\w.+-]{1,119}", query):
        return Q(text__iregex=r"(^|[^\w@.+/-])" + re.escape(query) + r"(?![\w+-]|\.[\w])")
    return None


@login_required
@require_POST
@rate_limit("markdown_preview")
def markdown_preview(request, chat_id):
    _chat_for_user(request.user, chat_id)
    text = request.POST.get("text", "")
    if len(text) > 4096:
        return JsonResponse({"ok": False, "error": "Сообщение слишком длинное."}, status=400)
    response = JsonResponse({
        "ok": True,
        "markdown_html": render_message_markdown(text, "composer-preview"),
    })
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_GET
@rate_limit("mention_candidates")
def mention_candidates(request, chat_id):
    chat = _chat_for_user(request.user, chat_id)
    query = request.GET.get("q", "").strip()[:150]
    if query and not re.fullmatch(r"[\w.+-]{1,150}", query):
        return JsonResponse({"ok": True, "results": []})
    candidates = (
        User.objects.filter(
            chat_memberships__chat=chat,
            chat_memberships__is_hidden=False,
            is_active=True,
        )
        .exclude(pk=request.user.pk)
        .filter(username__istartswith=query)
        .order_by("username")[:30]
    )
    return JsonResponse({
        "ok": True,
        "results": [
            {"username": candidate.username, "display_name": candidate.display_name}
            for candidate in candidates
            if re.fullmatch(r"[\w.+-]{1,150}", candidate.username)
            and not is_blocked_between(request.user, candidate)
        ][:8],
    })


@login_required
@require_POST
@rate_limit("message_reaction")
def message_reaction(request, chat_id, message_id):
    account_id = request.POST.get("account_id")
    if account_id is not None and account_id != str(request.user.pk):
        return JsonResponse({"ok": False, "error": "Аккаунт изменился."}, status=409)
    chat = _chat_for_user(request.user, chat_id)
    emoji = request.POST.get("emoji")
    if emoji is None or (emoji and emoji not in MessageReaction.Emoji.values):
        return JsonResponse({"ok": False, "error": "Неизвестная реакция."}, status=400)
    with transaction.atomic():
        # Serialize permission changes with reaction writes, using the same
        # lock order as community moderation (chat, membership, message).
        chat = get_object_or_404(Chat.objects.select_for_update(), pk=chat.pk)
        membership = ChatParticipant.objects.select_for_update().filter(
            chat=chat, user=request.user, is_hidden=False,
        ).first()
        if membership is None:
            raise Http404
        if emoji and emoji not in member_reaction_emojis(chat, membership):
            return JsonResponse({"ok": False, "error": "Эта реакция недоступна в сообществе."}, status=403)
        if emoji and chat.type == Chat.Type.PRIVATE and not _posting_capabilities(
            chat, membership, request.user,
        )["text"]:
            return JsonResponse({"ok": False, "error": "Нельзя реагировать в этой переписке."}, status=403)
        if not _visible_message_queryset(chat, request.user).filter(
            pk=message_id, is_deleted=False,
        ).exists():
            raise Http404
        # Lock a plain message row (no DISTINCT/outer joins) before updating.
        message = get_object_or_404(
            Message.objects.select_for_update(), pk=message_id, chat=chat, is_deleted=False,
        )
        previous = MessageReaction.objects.filter(message=message, user=request.user).first()
        changed = False
        if not emoji:
            if previous:
                previous.delete()
                changed = True
        elif previous is None:
            MessageReaction.objects.create(message=message, user=request.user, emoji=emoji)
            changed = True
        elif previous.emoji != emoji:
            previous.emoji = emoji
            previous.save(update_fields=["emoji"])
            changed = True
        if changed:
            message.reaction_version += 1
            message.reaction_changed_at = timezone.now()
            message.save(update_fields=["reaction_version", "reaction_changed_at"])
        return JsonResponse({
            "ok": True,
            "message_id": message.pk,
            "reaction_version": message.reaction_version,
            "reactions": serialize_reactions(message, request.user),
        })


@login_required
@require_GET
@rate_limit("message_reaction")
def message_reactors(request, chat_id, message_id):
    account_id = request.GET.get("account_id")
    if account_id is not None and account_id != str(request.user.pk):
        return JsonResponse({"ok": False, "error": "Аккаунт изменился."}, status=409)
    chat = _chat_for_user(request.user, chat_id)
    message = get_object_or_404(_visible_message_queryset(chat, request.user), pk=message_id, is_deleted=False)
    emoji = request.GET.get("emoji", "")
    if emoji and emoji not in MessageReaction.Emoji.values:
        return JsonResponse({"ok": False, "error": "Неизвестная реакция."}, status=400)
    try:
        after = int(request.GET.get("after", "0"))
        if not 0 <= after <= 9223372036854775807:
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        return JsonResponse({"ok": False, "error": "Некорректный курсор."}, status=400)

    counts = serialize_reactions(message, request.user)
    # Reactions to channel posts remain anonymous, including for admins.
    # In groups/direct chats reveal only current visible participants.
    anonymous = chat.type == Chat.Type.CHANNEL
    reactors = []
    next_after = None
    visible_total = 0
    if not anonymous:
        memberships = ChatParticipant.objects.filter(chat=chat, is_hidden=False, cleared_before_message_id__lt=message.pk)
        memberships = memberships.exclude(
            user_id__in=MessageHiddenForUser.objects.filter(message=message).values("user_id")
        )
        if chat.type == Chat.Type.GROUP and not chat.history_visible_to_new_members:
            memberships = memberships.filter(
                Q(can_see_pre_join_history=True) | Q(joined_at__lte=message.created_at)
            )
        query = MessageReaction.objects.filter(message=message, user_id__in=memberships.values("user_id"))
        if emoji:
            query = query.filter(emoji=emoji)
        visible_total = query.count()
        rows = list(query.filter(pk__gt=after).select_related("user").order_by("pk")[:51])
        more = len(rows) > 50
        rows = rows[:50]
        reactors = [{"name": row.user.display_name, "username": row.user.username, "emoji": row.emoji} for row in rows]
        next_after = rows[-1].pk if more else None
    response = JsonResponse({
        "ok": True, "account_id": request.user.pk,
        "anonymous": anonymous, "counts": counts, "reactors": reactors,
        "visible_total": visible_total, "next_after": next_after,
    })
    response["Cache-Control"] = "private, no-store"
    return response


def _search_before(request):
    try:
        before = int(request.GET.get("before", "0"))
        if not 0 <= before <= 9223372036854775807:
            raise ValueError
        return before
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Некорректный курсор поиска.") from None


def _search_text_condition(query):
    return _message_search_condition(query) or (
        Q(text__icontains=query) | Q(attachments__original_name__icontains=query)
    )


def _search_page(queryset, before, size):
    if before:
        queryset = queryset.filter(pk__lt=before)
    items = list(queryset.order_by("-pk")[:size + 1])
    has_more = len(items) > size
    items = items[:size]
    return items, items[-1].pk if has_more else None


@login_required
@require_GET
@rate_limit("search_messages")
def search_messages(request, chat_id):
    chat = _chat_for_user(request.user, chat_id)
    query = request.GET.get("q", "").strip()[:120]
    sender = request.GET.get("sender", "").strip().lstrip("@")
    kind = request.GET.get("kind", "").strip()
    raw_from = request.GET.get("date_from", "").strip()
    raw_to = request.GET.get("date_to", "").strip()
    try:
        before = _search_before(request)
        date_from = parse_date(raw_from) if raw_from else None
        date_to = parse_date(raw_to) if raw_to else None
        if (raw_from and date_from is None) or (raw_to and date_to is None):
            raise ValueError("Укажите корректную дату.")
        if date_from and date_to and date_from > date_to:
            raise ValueError("Начальная дата позже конечной.")
        if len(sender) > 150 or kind not in ("", "text", *MessageAttachment.Kind.values, *Message.SpecialType.values):
            raise ValueError("Некорректные фильтры поиска.")
    except (TypeError, ValueError, OverflowError) as error:
        return JsonResponse({"ok": False, "error": str(error)}, status=400)
    if not any((query, sender, kind, date_from, date_to)):
        return JsonResponse({"ok": True, "results": [], "next_before": None})

    base = _visible_message_queryset(chat, request.user).filter(is_deleted=False)
    if query:
        base = base.filter(_search_text_condition(query))
    if sender:
        base = base.filter(sender__username__iexact=sender)
    if date_from:
        base = base.filter(created_at__date__gte=date_from)
    if date_to:
        base = base.filter(created_at__date__lte=date_to)
    if kind == "text":
        base = base.filter(special_type="", attachments__isnull=True).exclude(text="")
    elif kind in MessageAttachment.Kind.values:
        base = base.filter(attachments__kind=kind)
    elif kind:
        base = base.filter(special_type=kind)
    results, next_before = _search_page(base, before, 50)
    return JsonResponse({
        "ok": True,
        "results": [
            {
                "id": message.pk,
                "sender_name": message.sender.display_name,
                "preview": message.preview[:220],
                "time": timezone.localtime(message.created_at).strftime("%d.%m.%Y %H:%M"),
                "url": f"{reverse('messenger:chat', args=[chat.pk])}?message={message.pk}#message-{message.pk}",
            }
            for message in results
        ],
        "next_before": next_before,
    })


@login_required
@require_POST
def chat_action(request, chat_id):
    if request.POST.get("account_id", str(request.user.pk)) != str(request.user.pk):
        return JsonResponse({"ok": False, "error": "Аккаунт изменился. Обновите страницу."}, status=409)
    chat = _chat_for_user(request.user, chat_id)
    membership = _membership(chat, request.user)
    action = request.POST.get("action", "")
    wants_json = _wants_json(request)

    def action_error(message, status=400):
        if wants_json:
            return JsonResponse({"ok": False, "error": message}, status=status)
        messages.error(request, message)
        return redirect(reverse("messenger:chat", args=[chat.pk]))

    def action_response(message, redirect_url=None, **extra):
        if wants_json:
            payload = {
                "ok": True,
                "message": message,
                **extra,
            }
            if redirect_url:
                payload["redirect_url"] = redirect_url
            return JsonResponse(payload)
        if message:
            messages.success(request, message)
        return redirect(
            redirect_url or reverse("messenger:chat", args=[chat.pk])
        )

    if action in ("mark_read", "mark_unread"):
        with transaction.atomic():
            locked = ChatParticipant.objects.select_for_update().get(pk=membership.pk)
            if locked.is_hidden:
                raise Http404
            if action == "mark_unread":
                locked.marked_unread_at = timezone.now()
                locked.save(update_fields=["marked_unread_at"])
            else:
                _mark_membership_read(locked, request.user)
        fallback = reverse("messenger:home")
        if membership.is_archived:
            fallback += "?archived=1"
        return action_response(
            "Чат отмечен непрочитанным." if action == "mark_unread" else "Чат отмечен прочитанным.",
            _safe_next(request, fallback),
            marked_unread=action == "mark_unread",
        )
    elif action == "pin":
        with transaction.atomic():
            User.objects.select_for_update().only("id").get(pk=request.user.pk)
            membership = ChatParticipant.objects.select_for_update().filter(pk=membership.pk, is_hidden=False).first()
            if membership is None:
                raise Http404
            raw = request.POST.get("pinned")
            if raw not in (None, "1", "0"):
                return action_error("Некорректное состояние закрепления.")
            set_membership_pinned(membership, not membership.is_pinned if raw is None else raw == "1")
        return action_response(
            "Чат закреплён." if membership.is_pinned else "Чат откреплён.",
            _safe_next(request, reverse("messenger:chat", args=[chat.pk])),
            is_pinned=membership.is_pinned,
        )
    elif action == "mute":
        duration = request.POST.get("duration")
        if duration is None:
            duration = "off" if membership.notifications_muted else "forever"

        mute_durations = {
            "1h": (timedelta(hours=1), "1 час"),
            "8h": (timedelta(hours=8), "8 часов"),
            "2d": (timedelta(days=2), "2 дня"),
        }
        if duration == "off":
            membership.is_muted = False
            membership.muted_until = None
            message = "Уведомления включены."
        elif duration == "forever":
            membership.is_muted = True
            membership.muted_until = None
            message = "Уведомления отключены навсегда."
        elif duration in mute_durations:
            delta, label = mute_durations[duration]
            membership.is_muted = True
            membership.muted_until = timezone.now() + delta
            message = f"Уведомления отключены на {label}."
        else:
            return action_error("Неизвестный срок отключения уведомлений.")

        membership.save(update_fields=("is_muted", "muted_until"))
        return action_response(
            message,
            is_muted=membership.notifications_muted,
            muted_until=(
                membership.muted_until.isoformat()
                if membership.notifications_muted and membership.muted_until
                else ""
            ),
            mute_duration=duration,
        )
    elif action == "auto_delete":
        if chat.type != Chat.Type.PRIVATE or chat.direct_key == f"self:{request.user.pk}":
            return action_error("Автоудаление доступно только в личной переписке.")
        try:
            seconds = int(request.POST.get("seconds", ""))
        except (ValueError, TypeError):
            seconds = -1
        if seconds not in AUTO_DELETE_CHOICES:
            return action_error("Неизвестный срок автоудаления.")
        chat.auto_delete_seconds = seconds
        chat.save(update_fields=("auto_delete_seconds",))
        return action_response("Настройки автоудаления обновлены.", auto_delete_seconds=seconds)
    elif action == "toggle_protection":
        if chat.type != Chat.Type.PRIVATE or chat.direct_key == f"self:{request.user.pk}":
            return action_error("Защита копирования доступна только в личной переписке.")
        protection = request.POST.get("enabled")
        if protection not in (None, "0", "1"):
            return action_error("Некорректное состояние защиты.")
        chat.protect_content = not chat.protect_content if protection is None else protection == "1"
        chat.save(update_fields=("protect_content",))
        return action_response(
            "Копирование запрещено." if chat.protect_content else "Копирование разрешено.",
            protect_content=chat.protect_content,
        )
    elif action == "archive":
        raw = request.POST.get("archived")
        if raw not in (None, "1", "0"):
            return action_error("Некорректное состояние архива.")
        with transaction.atomic():
            membership = ChatParticipant.objects.select_for_update().filter(pk=membership.pk, is_hidden=False).first()
            if membership is None:
                raise Http404
            set_membership_archived(membership, not membership.is_archived if raw is None else raw == "1")
        fallback = (
            reverse("messenger:home")
            if membership.is_archived
            else f"{reverse('messenger:home')}?archived=1"
        )
        return action_response(
            "Чат перенесён в архив." if membership.is_archived else "Чат возвращён из архива.",
            _safe_next(request, fallback),
            is_archived=membership.is_archived,
        )
    elif action == "leave":
        if chat.type == Chat.Type.PRIVATE:
            if wants_json:
                return JsonResponse(
                    {"ok": False, "error": "Личный чат нельзя покинуть."},
                    status=400,
                )
            messages.error(request, "Личный чат нельзя покинуть.")
            return redirect("messenger:chat", chat_id=chat.pk)
        if membership.role == ChatParticipant.Role.OWNER:
            if wants_json:
                return JsonResponse(
                    {
                        "ok": False,
                        "error": "Владелец не может выйти, пока права владельца не переданы.",
                    },
                    status=403,
                )
            messages.error(
                request,
                "Владелец не может выйти, пока права владельца не переданы.",
            )
            return redirect("messenger:chat", chat_id=chat.pk)
        membership.delete()
        return action_response(
            "Вы покинули канал."
            if chat.type == Chat.Type.CHANNEL
            else "Вы покинули группу.",
            reverse("messenger:home"),
            left=True,
        )
    elif action == "clear":
        scope = request.POST.get("scope", "me").strip().lower()
        is_saved = (
            chat.type == Chat.Type.PRIVATE
            and chat.direct_key == f"self:{request.user.pk}"
        )
        if is_saved:
            with transaction.atomic():
                for message in _base_message_queryset(chat).filter(
                    is_deleted=False
                ):
                    delete_message_content(message)
                MessageHiddenForUser.objects.filter(message__chat=chat).delete()
                latest_id = (
                    chat.messages.order_by("-id")
                    .values_list("id", flat=True)
                    .first()
                    or 0
                )
                ChatParticipant.objects.filter(chat=chat).update(
                    cleared_before_message_id=latest_id,
                    last_read_message=None,
                    marked_unread_at=None,
                    draft_text="",
                    draft_updated_at=None,
                    last_typing_at=None,
                )
                PinnedMessage.objects.filter(chat=chat).delete()
            return action_response(
                "Избранное очищено.",
                cleared=True,
                scope="everyone",
            )

        if scope == "everyone" and chat.type == Chat.Type.PRIVATE:
            with transaction.atomic():
                for message in _base_message_queryset(chat).filter(is_deleted=False):
                    delete_message_content(message)
                MessageHiddenForUser.objects.filter(message__chat=chat).delete()
                latest_id = (
                    chat.messages.order_by("-id")
                    .values_list("id", flat=True)
                    .first()
                    or 0
                )
                ChatParticipant.objects.filter(chat=chat).update(
                    cleared_before_message_id=latest_id,
                    last_read_message=None,
                    marked_unread_at=None,
                    draft_text="",
                    draft_updated_at=None,
                    last_typing_at=None,
                )
                PinnedMessage.objects.filter(chat=chat).delete()
            return action_response(
                "История переписки удалена у обоих.",
                cleared=True,
                scope="everyone",
            )

        _clear_history_for_user(chat, membership)
        return action_response(
            "История очищена у вас.",
            cleared=True,
            scope="me",
        )
    elif action == "delete_chat":
        scope = request.POST.get("scope", "me").strip().lower()
        if chat.type == Chat.Type.PRIVATE:
            is_saved = chat.direct_key == f"self:{request.user.pk}"
            if is_saved:
                _clear_history_for_user(chat, membership)
                return action_response(
                    "Избранное очищено.",
                    reverse("messenger:chat", args=[chat.pk]),
                    deleted=False,
                    scope="me",
                )

            if scope == "everyone":
                with transaction.atomic():
                    for message in _base_message_queryset(chat).filter(is_deleted=False):
                        delete_message_content(message)
                    MessageHiddenForUser.objects.filter(message__chat=chat).delete()
                    latest_id = (
                        chat.messages.order_by("-id")
                        .values_list("id", flat=True)
                        .first()
                        or 0
                    )
                    ChatParticipant.objects.filter(chat=chat).update(
                        is_hidden=True,
                        cleared_before_message_id=latest_id,
                        is_pinned=False,
                        pin_order=0,
                        is_archived=False,
                        draft_text="",
                        draft_updated_at=None,
                        last_typing_at=None,
                        last_read_message=None,
                        marked_unread_at=None,
                    )
                    PinnedMessage.objects.filter(chat=chat).delete()
                return action_response(
                    "Чат удалён у обоих.",
                    reverse("messenger:home"),
                    deleted=True,
                    scope="everyone",
                )

            with transaction.atomic():
                _clear_history_for_user(chat, membership)
                membership.is_hidden = True
                membership.is_pinned = False
                membership.pin_order = 0
                membership.is_archived = False
                membership.save(
                    update_fields=("is_hidden", "is_pinned", "pin_order", "is_archived")
                )
            return action_response(
                "Чат удалён у вас.",
                reverse("messenger:home"),
                deleted=True,
                scope="me",
            )

        if membership.role == ChatParticipant.Role.OWNER:
            label = "Канал удалён." if chat.type == Chat.Type.CHANNEL else "Группа удалена."
            with transaction.atomic():
                for message in _base_message_queryset(chat).filter(
                    is_deleted=False
                ):
                    delete_message_content(message)
                if chat.avatar:
                    chat.avatar.delete(save=False)
                chat.delete()
            return action_response(
                label,
                reverse("messenger:home"),
                deleted=True,
                scope="everyone",
            )

        membership.delete()
        return action_response(
            "Вы покинули канал."
            if chat.type == Chat.Type.CHANNEL
            else "Вы покинули группу.",
            reverse("messenger:home"),
            deleted=True,
            left=True,
        )
    else:
        messages.error(request, "Неизвестное действие с чатом.")

    return redirect("messenger:chat", chat_id=chat.pk)


@login_required
@require_POST
def save_draft(request, chat_id):
    account_id = request.POST.get("account_id")
    if account_id is not None and account_id != str(request.user.pk):
        return JsonResponse({"ok": False, "error": "Аккаунт изменился. Обновите страницу."}, status=409)
    chat = _chat_for_user(request.user, chat_id)
    text = request.POST.get("text", "")
    if len(text) > 4096:
        return JsonResponse({"ok": False, "error": "Черновик слишком длинный."}, status=400)
    ChatParticipant.objects.filter(chat=chat, user=request.user).update(
        draft_text=text,
        draft_updated_at=timezone.now() if text else None,
    )
    return JsonResponse({"ok": True})


@login_required
@require_POST
@rate_limit("typing")
def typing(request, chat_id):
    chat = _chat_for_user(request.user, chat_id)
    membership = _membership(chat, request.user)
    capabilities = _posting_capabilities(chat, membership, request.user)
    if not capabilities["text"]:
        ChatParticipant.objects.filter(
            chat=chat,
            user=request.user,
        ).update(last_typing_at=None)
        return JsonResponse(
            {
                "ok": False,
                "error": capabilities["reason"] or "Отправка текста здесь недоступна.",
            },
            status=403,
        )

    ChatParticipant.objects.filter(
        chat=chat,
        user=request.user,
    ).update(last_typing_at=timezone.now())
    return JsonResponse({"ok": True})


@login_required
@require_GET
def message_readers(request, chat_id, message_id):
    """Read cursor details for the author of a visible group message."""
    account_id = request.GET.get("account_id")
    if account_id is not None and account_id != str(request.user.pk):
        return JsonResponse({"ok": False, "error": "Аккаунт изменился."}, status=409)
    chat = _chat_for_user(request.user, chat_id)
    if chat.type != Chat.Type.GROUP:
        raise Http404
    message = get_object_or_404(
        _visible_message_queryset(chat, request.user),
        pk=message_id, sender=request.user, is_deleted=False,
    )
    try:
        after = int(request.GET.get("after", "0"))
        if not 0 <= after <= 9223372036854775807:
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        return JsonResponse({"ok": False, "error": "Некорректный курсор."}, status=400)
    readers = ChatParticipant.objects.filter(
        Q(read_through_id__gte=message.pk) | Q(last_read_message_id__gte=message.pk),
        chat=chat, is_hidden=False, cleared_before_message_id__lt=message.pk,
    ).exclude(user=request.user).exclude(
        user_id__in=MessageHiddenForUser.objects.filter(message=message).values("user_id")
    )
    if not chat.history_visible_to_new_members:
        readers = readers.filter(
            Q(can_see_pre_join_history=True) | Q(joined_at__lte=message.created_at)
        )
    total = readers.count()
    page = list(readers.filter(user_id__gt=after).select_related("user").order_by("user_id")[:51])
    more = len(page) > 50
    page = page[:50]
    response = JsonResponse({
        "ok": True, "account_id": request.user.pk, "total": total,
        "readers": [{"name": row.user.display_name, "username": row.user.username} for row in page],
        "next_after": page[-1].user_id if more else None,
    })
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_GET
def chat_gallery(request, chat_id):
    account_id = request.GET.get("account_id")
    if account_id is not None and account_id != str(request.user.pk):
        return JsonResponse({"ok": False, "error": "Аккаунт изменился."}, status=409)
    chat = _chat_for_user(request.user, chat_id)
    membership = _membership(chat, request.user)
    kind = request.GET.get("kind", "media")
    filters = {
        "media": [MessageAttachment.Kind.IMAGE, MessageAttachment.Kind.VIDEO],
        "files": [MessageAttachment.Kind.FILE],
        "audio": [MessageAttachment.Kind.AUDIO],
        "voice": [MessageAttachment.Kind.VOICE],
        "stickers": [MessageAttachment.Kind.STICKER],
    }
    if kind not in filters:
        return JsonResponse({"ok": False, "error": "Неизвестный раздел."}, status=400)
    try:
        before = _search_before(request)
    except ValueError:
        return JsonResponse({"ok": False, "error": "Некорректный курсор."}, status=400)
    query = visible_chat_attachments(chat, membership)
    counts = dict(query.order_by().values("kind").annotate(total=Count("pk")).values_list("kind", "total"))
    selected = query.filter(kind__in=filters[kind])
    if before:
        selected = selected.filter(pk__lt=before)
    rows = list(selected[:41])
    more = len(rows) > 40
    rows = rows[:40]
    response = JsonResponse({
        "ok": True, "account_id": request.user.pk,
        "kind": kind, "protected": chat.protect_content,
        "counts": {key: sum(counts.get(value, 0) for value in values) for key, values in filters.items()},
        "items": [shared_attachment_payload(row, chat) for row in rows],
        "next_before": rows[-1].pk if more else None,
    })
    response["Cache-Control"] = "private, no-store"
    return response


def _attachment_for_user(user, attachment_id):
    attachment = get_object_or_404(
        MessageAttachment.objects.select_related("message", "message__chat").filter(
            Q(message__expires_at__isnull=True) | Q(message__expires_at__gt=timezone.now())
        ),
        pk=attachment_id,
        message__chat__participants=user,
        message__is_deleted=False,
    )
    chat = attachment.message.chat
    membership = ChatParticipant.objects.get(chat=chat, user=user)
    if membership.is_hidden:
        raise Http404
    if (
        attachment.message_id <= membership.cleared_before_message_id
        or MessageHiddenForUser.objects.filter(
            message_id=attachment.message_id,
            user=user,
        ).exists()
    ):
        raise Http404
    if (
        chat.type != Chat.Type.PRIVATE
        and not chat.history_visible_to_new_members
        and not membership.can_see_pre_join_history
        and attachment.message.created_at < membership.joined_at
    ):
        raise Http404
    return attachment


INLINE_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".m4v": "video/x-m4v",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".opus": "audio/opus",
}


def _range_file_chunks(field_file, start, length, chunk_size=64 * 1024):
    field_file.open("rb")
    stream = field_file.file
    stream.seek(start)
    remaining = length
    try:
        while remaining > 0:
            chunk = stream.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
    finally:
        field_file.close()


def _inline_file_response(request, attachment, content_type):
    total_size = int(attachment.size or attachment.file.size or 0)
    range_header = (request.headers.get("Range") or "").strip()

    if range_header.startswith("bytes=") and "," not in range_header and total_size > 0:
        raw = range_header[6:]
        start_text, separator, end_text = raw.partition("-")
        if separator:
            try:
                if start_text:
                    start = int(start_text)
                    end = int(end_text) if end_text else total_size - 1
                elif end_text:
                    suffix = max(0, int(end_text))
                    start = max(0, total_size - suffix)
                    end = total_size - 1
                else:
                    raise ValueError
                end = min(end, total_size - 1)
                if start < 0 or start >= total_size or end < start:
                    raise ValueError
            except ValueError:
                response = StreamingHttpResponse(status=416)
                response["Content-Range"] = f"bytes */{total_size}"
                response["Accept-Ranges"] = "bytes"
                return response

            length = end - start + 1
            response = StreamingHttpResponse(
                _range_file_chunks(attachment.file, start, length),
                status=206,
                content_type=content_type,
            )
            response["Content-Length"] = str(length)
            response["Content-Range"] = f"bytes {start}-{end}/{total_size}"
            response["Accept-Ranges"] = "bytes"
            return response

    attachment.file.open("rb")
    response = FileResponse(
        attachment.file,
        as_attachment=False,
        filename=Path(attachment.original_name).name or "media",
        content_type=content_type,
    )
    response["Accept-Ranges"] = "bytes"
    if total_size > 0:
        response["Content-Length"] = str(total_size)
    return response


@login_required
@require_GET
def thumbnail_attachment(request, attachment_id):
    # Authorize even conditional requests: an ETag must not circumvent
    # revoked membership, cleared history, expiry, or per-user deletion.
    attachment = _attachment_for_user(request.user, attachment_id)
    if attachment.kind not in {MessageAttachment.Kind.IMAGE, MessageAttachment.Kind.STICKER}:
        raise Http404
    if not attachment.file or not attachment.file.storage.exists(attachment.file.name):
        raise Http404
    version = hashlib.sha256(
        f"{THUMBNAIL_VERSION}:{attachment.pk}:{attachment.file.name}:{attachment.size}".encode()
    ).hexdigest()
    etag = f'"{version}"'
    if etag in parse_etags(request.headers.get("If-None-Match", "")):
        response = HttpResponseNotModified()
    else:
        try:
            with attachment.file.open("rb") as source:
                content = make_thumbnail(source)
        except (OSError, ValueError, EOFError, SyntaxError, Image.DecompressionBombError):
            raise Http404("Миниатюра недоступна.") from None
        response = HttpResponse(content, content_type="image/webp")
    response["ETag"] = etag
    response["Cache-Control"] = "private, no-cache, must-revalidate"
    response["X-Content-Type-Options"] = "nosniff"
    patch_vary_headers(response, ["Cookie"])
    return response


@login_required
@require_GET
def view_attachment(request, attachment_id):
    attachment = _attachment_for_user(request.user, attachment_id)
    if attachment.kind not in {
        MessageAttachment.Kind.IMAGE,
        MessageAttachment.Kind.VIDEO,
        MessageAttachment.Kind.AUDIO,
        MessageAttachment.Kind.VOICE,
        MessageAttachment.Kind.STICKER,
    }:
        return JsonResponse({"ok": False, "error": "Вложение нельзя открыть inline."}, status=404)

    extension = Path(attachment.original_name).suffix.lower()
    if attachment.kind == MessageAttachment.Kind.VOICE:
        stored_type = (attachment.mime_type or "").split(";", 1)[0].strip().lower()
        if stored_type == "video/webm":
            stored_type = "audio/webm"
        content_type = (
            stored_type
            if stored_type in {
                "audio/webm",
                "audio/ogg",
                "audio/opus",
                "audio/mp4",
            }
            else {
                ".webm": "audio/webm",
                ".ogg": "audio/ogg",
                ".oga": "audio/ogg",
                ".opus": "audio/opus",
                ".m4a": "audio/mp4",
            }.get(extension)
        )
    else:
        content_type = INLINE_MEDIA_TYPES.get(extension)
    if content_type is None:
        return JsonResponse({"ok": False, "error": "Неподдерживаемый тип медиа."}, status=404)

    if not attachment.file or not attachment.file.storage.exists(attachment.file.name):
        raise Http404
    try:
        response = _inline_file_response(request, attachment, content_type)
    except FileNotFoundError:
        raise Http404 from None
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
@require_POST
def mark_voice_played(request, attachment_id):
    attachment = _attachment_for_user(request.user, attachment_id)
    if attachment.kind != MessageAttachment.Kind.VOICE:
        return JsonResponse(
            {"ok": False, "error": "Это вложение не является голосовым сообщением."},
            status=400,
        )

    VoiceMessagePlayback.objects.get_or_create(
        attachment=attachment,
        user=request.user,
    )
    return JsonResponse({"ok": True, "listened": True})


@login_required
@require_GET
def download_attachment(request, attachment_id):
    attachment = _attachment_for_user(request.user, attachment_id)
    if attachment.message.chat.protect_content:
        return HttpResponseForbidden(
            "Скачивание вложений отключено для этой переписки."
        )
    try:
        attachment.file.open("rb")
    except (FileNotFoundError, ValueError):
        raise Http404 from None
    response = FileResponse(
        attachment.file,
        as_attachment=True,
        filename=Path(attachment.original_name).name or "file",
        content_type="application/octet-stream",
    )
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_GET
def poll_messages(request, chat_id):
    account_id = request.GET.get("account_id")
    if account_id is not None and account_id != str(request.user.pk):
        return JsonResponse({"ok": False, "error": "Аккаунт изменился. Обновите страницу."}, status=409)
    # Only reconcile IDs already known to the requesting client. Returning
    # absent IDs (without any reason) does not disclose foreign messages.
    raw_known_ids = request.GET.get("known_ids", "")
    try:
        if len(raw_known_ids) > 2100:
            raise ValueError
        values = raw_known_ids.split(",") if raw_known_ids else []
        if len(values) > 100:
            raise ValueError
        known_ids = {int(value) for value in values}
        if any(not 0 < value <= 9223372036854775807 for value in known_ids):
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        return JsonResponse({"ok": False, "error": "Некорректные идентификаторы сообщений."}, status=400)

    # Clients optionally report compact revisions of their mounted window.
    # This repairs writes committed after a timestamp cursor already passed.
    known_versions = {}
    try:
        raw_versions = request.GET.get("known_versions", "")
        if len(raw_versions) > 3000:
            raise ValueError
        for row in raw_versions.split(",") if raw_versions else []:
            message_id, revision, reaction = map(int, row.split(":"))
            if (message_id not in known_ids or message_id in known_versions
                    or not 0 <= revision <= 9007199254740991
                    or not 0 <= reaction <= 9223372036854775807):
                raise ValueError
            known_versions[message_id] = (revision, reaction)
    except (ValueError, TypeError, OverflowError):
        return JsonResponse({"ok": False, "error": "Некорректные версии сообщений."}, status=400)

    chat = _chat_for_user(request.user, chat_id)
    membership = _membership(chat, request.user)
    try:
        after_id = max(0, min(int(request.GET.get("after", "0")), 9223372036854775807))
    except (TypeError, ValueError):
        after_id = 0

    now = timezone.now()
    try:
        since = parse_datetime(request.GET.get("since", ""))
    except (ValueError, TypeError, OverflowError):
        since = None
    if since is None:
        since = now
    elif timezone.is_naive(since):
        since = timezone.make_aware(since, timezone.get_current_timezone())
    try:
        after_update_id = max(0, min(int(request.GET.get("after_update_id", "0")), 9223372036854775807))
    except (TypeError, ValueError):
        after_update_id = 0

    base = _visible_message_queryset(chat, request.user)
    new_messages = [] if request.GET.get("skip_new") == "1" else list(
        base.filter(id__gt=after_id, is_deleted=False).order_by("id")[:100]
    )

    updated_messages = list(
        base.filter(id__lte=after_id)
        .filter(
            Q(updated_at__gt=since)
            | Q(updated_at=since, id__gt=after_update_id)
        )
        .order_by("updated_at", "id")[:100]
    )
    _hide_inaccessible_reply_previews(chat, request.user, new_messages)
    # Preserve the cursor of the timestamp page separately from repairs.
    cursor_messages = list(updated_messages)
    removed_ids = []
    visible_ids = set()
    repair_reaction_ids = set()
    if known_ids:
        mounted = list(
            base.filter(pk__in=known_ids, is_deleted=False)
            .select_related(None).prefetch_related(None)
            .only("pk", "updated_at", "reaction_version").order_by("pk")
        )
        visible_ids = {message.pk for message in mounted}
        removed_ids = sorted(known_ids - visible_ids)
        delivered_ids = {message.pk for message in new_messages + updated_messages}
        repair_ids = set()
        for message in mounted:
            version = known_versions.get(message.pk)
            if version is None or message.pk in delivered_ids:
                continue
            if message.sync_revision > version[0]:
                repair_ids.add(message.pk)
            elif message.reaction_version > version[1]:
                repair_reaction_ids.add(message.pk)
        if repair_ids:
            updated_messages.extend(base.filter(pk__in=repair_ids, is_deleted=False).order_by("pk"))
    _hide_inaccessible_reply_previews(chat, request.user, updated_messages)

    # Independent reaction cursor: changing an emoji must not rebuild media
    # or reset playback on the receiving client's existing message element.
    try:
        reaction_since = parse_datetime(request.GET.get("reaction_since", "")) or since
        if timezone.is_naive(reaction_since):
            reaction_since = timezone.make_aware(reaction_since, timezone.get_current_timezone())
        reaction_after_id = max(0, min(int(request.GET.get("reaction_after_id", "0")), 9223372036854775807))
    except (TypeError, ValueError, OverflowError):
        reaction_since, reaction_after_id = since, 0
    reaction_messages = list(
        base.prefetch_related(None).prefetch_related("reactions")
        .filter(id__lte=after_id, is_deleted=False)
        .filter(
            Q(reaction_changed_at__gt=reaction_since)
            | Q(reaction_changed_at=reaction_since, id__gt=reaction_after_id)
        )
        .order_by("reaction_changed_at", "id")[:100]
    )
    if len(reaction_messages) == 100:
        reaction_cursor_time = reaction_messages[-1].reaction_changed_at
        reaction_cursor_id = reaction_messages[-1].pk
    else:
        # Overlap a few seconds for writes that were in flight during a poll.
        # Clients discard duplicate revisions, so an overlap is harmless.
        reaction_cursor_time = max(reaction_since, now - timedelta(seconds=5))
        reaction_cursor_id = reaction_after_id if reaction_cursor_time == reaction_since else 0

    # Never move past a page of messages that was not delivered to the client.
    # Both new messages and edits may require multiple polling requests.
    # Only advance past messages actually returned, never past a concurrent send.
    high_watermark = new_messages[-1].pk if new_messages else after_id
    if len(cursor_messages) == 100:
        updates_cursor_time = cursor_messages[-1].updated_at
        updates_cursor_id = cursor_messages[-1].pk
    else:
        # Short overlap handles ordinary in-flight commits quickly.
        # Mounted-window reconciliation also repairs arbitrarily late writes.
        updates_cursor_time = max(since, now - timedelta(seconds=5))
        updates_cursor_id = after_update_id if updates_cursor_time == since else 0
    repair_reaction_ids.difference_update(message.pk for message in reaction_messages)
    if repair_reaction_ids:
        reaction_messages.extend(
            base.prefetch_related(None).prefetch_related("reactions")
            .filter(pk__in=repair_reaction_ids, is_deleted=False)
        )
    other_last_read_id = (
        _other_last_read_id(chat, request.user)
        if chat.type == Chat.Type.PRIVATE
        else 0
    )
    pinned_ids = set(
        _visible_pins_queryset(chat, request.user).values_list("message_id", flat=True)
    )

    typing_names = []
    other_last_seen_exact = False
    other_last_seen_at = ""
    other_is_online = False
    other_user_id = None
    other_user_avatar_url = ""
    other_user_initials = ""
    other_user_display_name = ""
    other_user_username = ""
    other_user_profile_url = ""
    is_saved_chat = (
        chat.type == Chat.Type.PRIVATE
        and chat.direct_key == f"self:{request.user.pk}"
    )
    chat_avatar_url = chat.avatar.url if chat.type != Chat.Type.PRIVATE and chat.avatar else ""
    chat_avatar_text = (
        "★" if is_saved_chat
        else "К" if chat.type == Chat.Type.CHANNEL
        else "Г" if chat.type == Chat.Type.GROUP
        else ""
    )
    chat_title = (
        "Избранное" if is_saved_chat
        else chat.title or ("Канал" if chat.type == Chat.Type.CHANNEL else "Группа")
    )
    chat_username = chat.username or "" if chat.type != Chat.Type.PRIVATE else ""
    if chat.type == Chat.Type.PRIVATE:
        other_membership = _other_membership(chat, request.user)
        other_user = other_user_for_chat(chat, request.user)
        other_can_type = bool(
            other_membership
            and _posting_capabilities(
                chat,
                other_membership,
                other_user,
            )["text"]
        )
        other_typing = bool(
            other_can_type
            and other_membership.last_typing_at
            and other_membership.last_typing_at >= now - timedelta(seconds=5)
        )
        is_saved = chat.direct_key == f"self:{request.user.pk}"
        other_status = "Личное облако" if is_saved else _presence_text(other_user, request.user)
        if not is_saved:
            other_user_id = other_user.pk
            other_user_display_name = contact_display_name(request.user, other_user)
            other_user_username = other_user.username
            other_user_initials = other_user.initials
            other_user_profile_url = reverse(
                "accounts:public_profile", args=[other_user.username],
            )
            chat_title = other_user_display_name
            chat_username = other_user.username
            chat_avatar_text = other_user.initials
            if other_user.avatar and privacy_allows(other_user, request.user, "profile_photo"):
                other_user_avatar_url = other_user.avatar_url
        if not is_saved and privacy_allows(other_user, request.user, "last_seen"):
            other_last_seen_exact = True
            other_last_seen_at = (
                other_user.last_seen_at.isoformat() if other_user.last_seen_at else ""
            )
            other_is_online = bool(other_user.is_online)
    else:
        other_typing = False
        if chat.type == Chat.Type.GROUP:
            # Limit work to recently active members; re-check posting rights,
            # since a member may have been restricted while typing.
            active_typists = (
                ChatParticipant.objects.filter(
                    chat=chat, is_hidden=False, last_typing_at__gte=now - timedelta(seconds=5)
                ).exclude(user=request.user).select_related("user").order_by("-last_typing_at")[:12]
            )
            for typist in active_typists:
                if len(typing_names) == 3:
                    break
                if not is_blocked_between(request.user, typist.user) and _posting_capabilities(chat, typist, typist.user)["text"]:
                    typing_names.append(typist.user.display_name)
            other_typing = bool(typing_names)
        _decorate_chat_ui(chat, request.user)
        other_status = chat.status_ui

    return JsonResponse(
        {
            "ok": True,
            "messages": [
                serialize_message(
                    message,
                    request.user,
                    other_last_read_id=other_last_read_id,
                    pinned_ids=pinned_ids,
                )
                for message in new_messages
            ],
            "updates": [
                serialize_message(
                    message,
                    request.user,
                    other_last_read_id=other_last_read_id,
                    pinned_ids=pinned_ids,
                )
                for message in updated_messages
            ],
            "removed_ids": removed_ids,
            "comments_enabled": chat.type == Chat.Type.CHANNEL and chat.comments_enabled,
            "discussion_counts": discussion_counts(
                visible_ids | {message.pk for message in new_messages + updated_messages if not message.is_deleted}
            ) if chat.type == Chat.Type.CHANNEL and chat.comments_enabled else {},
            "reaction_updates": [
                {
                    "message_id": message.pk,
                    "reaction_version": message.reaction_version,
                    "reactions": serialize_reactions(message, request.user),
                }
                for message in reaction_messages
            ],
            "reaction_cursor_time": reaction_cursor_time.isoformat(),
            "reaction_cursor_id": reaction_cursor_id,
            "high_watermark": high_watermark,
            "updates_cursor_time": updates_cursor_time.isoformat(),
            "updates_cursor_id": updates_cursor_id,
            "other_last_read_id": other_last_read_id,
            "own_last_read_id": max(membership.read_through_id, membership.last_read_message_id or 0),
            "other_typing": other_typing,
            "typing_names": typing_names,
            "other_status": other_status,
            "other_last_seen_exact": other_last_seen_exact,
            "other_last_seen_at": other_last_seen_at,
            "other_is_online": other_is_online,
            "other_user_id": other_user_id,
            "other_user_avatar_url": other_user_avatar_url,
            "other_user_initials": other_user_initials,
            "other_user_display_name": other_user_display_name,
            "other_user_username": other_user_username,
            "other_user_profile_url": other_user_profile_url,
            "chat_id": chat.pk,
            "chat_type": chat.type,
            "allowed_reactions": member_reaction_emojis(chat, membership)
                if chat.type != Chat.Type.PRIVATE or _posting_capabilities(chat, membership, request.user)["text"] else [],
            "protect_content": chat.protect_content,
            "is_muted": membership.notifications_muted,
            "muted_until": (
                membership.muted_until.isoformat()
                if membership.notifications_muted and membership.muted_until
                else ""
            ),
            "chat_title": chat_title,
            "chat_username": chat_username,
            "chat_avatar_url": chat_avatar_url,
            "chat_avatar_text": chat_avatar_text,
            "pins": _serialize_visible_pins(chat, request.user),
            "server_time": now.isoformat(),
        }
    )
