import secrets
from datetime import datetime, time, timedelta
import json

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.accounts.privacy import is_blocked_between, privacy_allows

from .forms import IMAGE_FORMATS, MEDIA_CONTENT_TYPES, _validate_inline_image
from .models import (
    Chat,
    ChatAdminLog,
    ChatInviteLink,
    ChatJoinRequest,
    ChatMemberModeration,
    ChatParticipant,
    ChannelPostView,
    Message,
    MessageAttachment,
    MessageReaction,
)
from .services import visible_chat_attachments, shared_attachment_payload, invited_membership_defaults, set_membership_archived
from .ratelimit import rate_limit
from .community_permissions import (
    ADMIN_RIGHTS, MEMBER_DENIALS, MEDIA_KINDS, group_media_kinds, active_sanctions, admin_rights,
    can_add_members, can_moderate, has_admin_right, is_banned, allowed_reaction_emojis, available_member_denials,
)

User = get_user_model()

SLOW_MODE_VALUES = {0, 10, 30, 60, 300, 900, 3600}


class CommunityProfileForm(forms.Form):
    VISIBILITY_PUBLIC = "public"
    VISIBILITY_PRIVATE = "private"

    title = forms.CharField(max_length=120)
    description = forms.CharField(required=False, max_length=500)
    username = forms.CharField(required=False, max_length=64)
    visibility = forms.ChoiceField(
        required=False,
        choices=((VISIBILITY_PUBLIC, "Публичный"), (VISIBILITY_PRIVATE, "Частный")),
    )
    avatar = forms.ImageField(required=False)
    remove_avatar = forms.BooleanField(required=False)

    def __init__(self, *args, chat, **kwargs):
        self.chat = chat
        super().__init__(*args, **kwargs)

    def clean_title(self):
        return self.cleaned_data["title"].strip()

    def clean_description(self):
        return self.cleaned_data.get("description", "").strip()

    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")
        if avatar is None:
            return None
        if avatar.size > 5 * 1024 * 1024:
            raise forms.ValidationError("Аватар должен быть не больше 5 МБ.")
        extension = avatar.name.rsplit(".", 1)[-1].lower() if "." in avatar.name else ""
        extension = f".{extension}" if extension else ""
        if extension not in IMAGE_FORMATS:
            raise forms.ValidationError("Поддерживаются PNG, JPEG и WebP.")
        content_type = (getattr(avatar, "content_type", "") or "").lower()
        if content_type not in MEDIA_CONTENT_TYPES.get(extension, set()):
            raise forms.ValidationError("MIME-тип аватара не соответствует расширению.")
        _validate_inline_image(avatar, extension)
        return avatar

    def clean_username(self):
        return _clean_public_username(self.chat, self.cleaned_data.get("username", ""))

    def clean(self):
        cleaned = super().clean()
        visibility = cleaned.get("visibility") or (
            self.VISIBILITY_PUBLIC if self.chat.username else self.VISIBILITY_PRIVATE
        )
        if visibility == self.VISIBILITY_PUBLIC and not cleaned.get("username"):
            self.add_error("username", "У публичного сообщества должен быть @адрес.")
        if visibility == self.VISIBILITY_PRIVATE:
            cleaned["username"] = ""
        cleaned["visibility"] = visibility
        return cleaned


def _ensure_collective_owner(chat):
    if ChatParticipant.objects.filter(
        chat=chat,
        role=ChatParticipant.Role.OWNER,
    ).exists():
        return

    with transaction.atomic():
        Chat.objects.select_for_update().get(pk=chat.pk)
        if ChatParticipant.objects.filter(
            chat=chat,
            role=ChatParticipant.Role.OWNER,
        ).exists():
            return

        candidates = ChatParticipant.objects.filter(chat=chat)
        successor = (
            candidates.filter(role=ChatParticipant.Role.ADMIN)
            .order_by("joined_at", "id")
            .first()
            or candidates.order_by("joined_at", "id").first()
        )
        if successor is None:
            return

        successor.role = ChatParticipant.Role.OWNER
        successor.save(update_fields=("role",))
        _log(
            chat,
            None,
            "owner_repair",
            f"Права владельца восстановлены для {successor.user.display_name}.",
            target_user=successor.user,
        )


def _collective_chat_for_user(user, chat_id):
    chat = get_object_or_404(
        Chat.objects.filter(
            pk=chat_id,
            type__in=(Chat.Type.GROUP, Chat.Type.CHANNEL),
            participants=user,
        ).distinct()
    )
    _ensure_collective_owner(chat)
    return chat


def _membership(chat, user):
    return get_object_or_404(ChatParticipant, chat=chat, user=user)


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
    delta = timezone.now() - user.last_seen_at
    if not exact:
        return "был(а) недавно" if delta < timedelta(days=3) else "был(а) давно"
    seen = timezone.localtime(user.last_seen_at)
    if delta.total_seconds() < 15 * 60:
        return "был(а) недавно"
    if seen.date() == timezone.localdate():
        return f"был(а) сегодня в {seen:%H:%M}"
    return f"был(а) {seen:%d.%m.%Y} в {seen:%H:%M}"


def _can_manage(membership):
    return membership.role in {
        ChatParticipant.Role.OWNER,
        ChatParticipant.Role.ADMIN,
    }


def _can_add_members(chat, membership):
    return can_add_members(chat, membership)


def _clean_public_username(chat, raw):
    username = (raw or "").strip().lstrip("@").lower()
    if not username:
        return ""
    if chat.platform_public_restricted:
        raise forms.ValidationError("Публичный адрес запрещён администрацией платформы.")
    if len(username) < 5 or not username.replace("_", "").isalnum():
        raise forms.ValidationError(
            "Адрес: минимум 5 символов, только буквы, цифры и подчёркивание."
        )
    if Chat.objects.filter(username__iexact=username).exclude(pk=chat.pk).exists():
        raise forms.ValidationError("Этот адрес уже занят другим чатом.")
    if User.objects.filter(username__iexact=username).exists():
        raise forms.ValidationError("Этот адрес уже занят пользователем.")
    return username


def _post_bool(request, key):
    return request.POST.get(key, "").lower() in {"1", "true", "on", "yes"}


def _log(chat, actor, action, description, target_user=None):
    ChatAdminLog.objects.create(
        chat=chat,
        actor=actor,
        action=action,
        target_user=target_user,
        description=description[:255],
    )


def _member_payload(actor, membership):
    user = membership.user
    actor_is_owner = actor.role == ChatParticipant.Role.OWNER
    removable = can_moderate(actor, membership)
    changeable = (
        actor_is_owner
        and user.pk != actor.user_id
        and membership.role != ChatParticipant.Role.OWNER
    )
    transferable = (
        actor_is_owner
        and user.pk != actor.user_id
        and membership.role != ChatParticipant.Role.OWNER
    )
    return {
        "id": membership.pk,
        "user_id": user.pk,
        "display_name": user.display_name,
        "username": user.username,
        "initials": user.initials,
        "avatar_url": (
            user.avatar_url
            if user.avatar and privacy_allows(user, actor.user, "profile_photo")
            else ""
        ),
        "presence": _presence_text(user, actor.user),
        "role": membership.role,
        "role_label": membership.get_role_display(),
        "profile_url": reverse("accounts:public_profile", args=[user.username]),
        "is_self": user.pk == actor.user_id,
        "can_remove": removable,
        "can_ban": removable,
        "can_restrict": removable and membership.role == ChatParticipant.Role.MEMBER and actor.chat.type in {Chat.Type.GROUP, Chat.Type.CHANNEL},
        "can_edit_admin_rights": actor_is_owner and membership.role == ChatParticipant.Role.ADMIN,
        "admin_rights": admin_rights(membership) if actor_is_owner or actor.user_id == user.pk else [],
        "can_change_role": changeable,
        "can_transfer_owner": transferable,
    }


def _profile_payload(request, chat):
    actor = _membership(chat, request.user)
    can_manage = _can_manage(actor)
    memberships = list(
        ChatParticipant.objects.filter(chat=chat)
        .select_related("user")
        .order_by("joined_at", "id")
    )
    rank = {
        ChatParticipant.Role.OWNER: 0,
        ChatParticipant.Role.ADMIN: 1,
        ChatParticipant.Role.MEMBER: 2,
    }
    memberships.sort(
        key=lambda item: (
            rank.get(item.role, 3),
            item.user.display_name.lower(),
            item.user.username.lower(),
        )
    )
    members_visible = chat.type == Chat.Type.GROUP or can_manage
    member_items = [
        _member_payload(actor, item)
        for item in memberships
    ] if members_visible else []

    attachment_query = visible_chat_attachments(chat, actor)
    media_types = [MessageAttachment.Kind.IMAGE, MessageAttachment.Kind.VIDEO]
    media_count = attachment_query.filter(kind__in=media_types).count()
    file_count = attachment_query.exclude(kind__in=media_types).count()
    attachment_items = [shared_attachment_payload(item, chat) for item in attachment_query[:90]]
    count = len(memberships)
    noun = "подписчиков" if chat.type == Chat.Type.CHANNEL else "участников"
    return {
        "id": chat.pk,
        "type": chat.type,
        "type_label": "Канал" if chat.type == Chat.Type.CHANNEL else "Группа",
        "title": chat.title or ("Канал" if chat.type == Chat.Type.CHANNEL else "Группа"),
        "description": chat.description or "",
        "username": chat.username or "",
        "is_public": bool(chat.username),
        "avatar_url": chat.avatar.url if chat.avatar else "",
        "avatar_fallback": (chat.title or ("К" if chat.type == Chat.Type.CHANNEL else "Г"))[:2].upper(),
        "status": f"{count} {noun}",
        "member_count": count,
        "members_visible": members_visible,
        "members": member_items,
        "viewer_role": actor.role,
        "viewer_role_label": actor.get_role_display(),
        "can_manage": can_manage,
        "can_edit_info": has_admin_right(actor, "change_info"),
        "can_add_members": _can_add_members(chat, actor),
        "can_leave": actor.role != ChatParticipant.Role.OWNER,
        "is_muted": actor.notifications_muted,
        "is_archived": actor.is_archived,
        "created_at": timezone.localtime(chat.created_at).strftime("%d.%m.%Y"),
        "attachments": attachment_items,
        "media_count": media_count,
        "file_count": file_count,
        "protect_content": chat.protect_content,
        "urls": {
            "chat": reverse("messenger:chat", args=[chat.pk]),
            "profile": reverse("messenger:community_profile", args=[chat.pk]),
            "update": reverse("messenger:community_profile_update", args=[chat.pk]),
            "member_action": reverse("messenger:community_member_action", args=[chat.pk]),
            "member_candidates": reverse("messenger:community_member_candidates", args=[chat.pk]),
            "action": reverse("messenger:community_profile_action", args=[chat.pk]),
            "settings": reverse("messenger:community_settings", args=[chat.pk]),
            "invite_action": reverse("messenger:community_invite_action", args=[chat.pk]),
            "join_request_action": reverse("messenger:community_join_request_action", args=[chat.pk]),
            "moderation": reverse("messenger:community_moderation", args=[chat.pk]),
        },
    }


def _invite_payload(invite):
    return {
        "id": invite.pk,
        "name": invite.name or "Ссылка-приглашение",
        "token": invite.token,
        "url": reverse("messenger:join_invite", args=[invite.token]),
        "creator": invite.creator.display_name if invite.creator else "",
        "created_at": timezone.localtime(invite.created_at).strftime("%d.%m.%Y %H:%M"),
        "expires_at": timezone.localtime(invite.expires_at).strftime("%d.%m.%Y %H:%M") if invite.expires_at else "",
        "usage_limit": invite.usage_limit,
        "usage_count": invite.usage_count,
        "requires_approval": invite.requires_approval,
        "is_active": invite.is_active,
        "revoked": invite.revoked_at is not None,
    }


def _settings_payload(request, chat):
    actor = _membership(chat, request.user)
    if not _can_manage(actor):
        return None

    memberships = list(
        ChatParticipant.objects.filter(chat=chat)
        .select_related("user")
        .order_by("joined_at", "id")
    )
    admins = [
        _member_payload(actor, item)
        for item in memberships
        if item.role in {ChatParticipant.Role.OWNER, ChatParticipant.Role.ADMIN}
    ]
    links = [
        _invite_payload(item)
        for item in ChatInviteLink.objects.filter(chat=chat)
        .select_related("creator")[:50]
    ] if has_admin_right(actor, "invite_users") else []
    logs = [
        {
            "id": item.pk,
            "action": item.action,
            "description": item.description,
            "actor_name": item.actor.display_name if item.actor else "Система",
            "actor_username": item.actor.username if item.actor else "",
            "time": timezone.localtime(item.created_at).strftime("%d.%m.%Y %H:%M"),
        }
        for item in ChatAdminLog.objects.filter(chat=chat)
        .select_related("actor", "target_user")[:80]
    ]
    pending = ChatJoinRequest.objects.filter(chat=chat, status=ChatJoinRequest.Status.PENDING).select_related("user", "invite")
    pending = pending.exclude(user_id__in=ChatParticipant.objects.filter(chat=chat).values("user_id"))
    if not has_admin_right(actor, "invite_users"):
        pending = pending.none()
    pending_count = pending.count()
    join_requests = [
        {"id": row.pk, "name": row.user.display_name, "username": row.user.username,
         "invite_name": row.invite.name or "Ссылка-приглашение", "invite_active": row.invite.is_active,
         "created_at": timezone.localtime(row.created_at).strftime("%d.%m.%Y %H:%M"),
         "revision": row.created_at.isoformat()}
        for row in pending[:100]
    ]
    moderation_rows = []
    moderation_count = 0
    if has_admin_right(actor, "moderate_members"):
        sanctions = list(active_sanctions(chat).select_related("user"))
        moderation_count = len(sanctions)
        moderation_rows = [
            {"id": row.pk, "user_id": row.user_id, "name": row.user.display_name,
             "username": row.user.username, "banned": row.banned, "permissions": row.denied_permissions,
             "expires_at": row.expires_at.isoformat() if row.expires_at else "",
             "reason": row.reason}
            for row in sanctions
        ]
    restrictions = [
        not chat.members_can_send_messages,
        not chat.members_can_send_media,
        not chat.members_can_send_links,
        not chat.members_can_add_members,
        not chat.members_can_pin_messages,
    ]
    return {
        "id": chat.pk,
        "type": chat.type,
        "title": chat.title,
        "username": chat.username or "",
        "is_public": bool(chat.username),
        "viewer_role": actor.role,
        "admin_rights": admin_rights(actor),
        "admin_right_labels": ADMIN_RIGHTS,
        "member_denial_labels": available_member_denials(chat),
        "can_add_members": _can_add_members(chat, actor),
        "moderation": moderation_rows,
        "moderation_count": moderation_count,
        "can_delete": actor.role == ChatParticipant.Role.OWNER,
        "history_visible_to_new_members": chat.history_visible_to_new_members,
        "permissions": {
            "send_messages": chat.members_can_send_messages,
            "send_media": chat.members_can_send_media,
            "media_kinds": group_media_kinds(chat),
            "send_links": chat.members_can_send_links,
            "add_members": chat.members_can_add_members,
            "pin_messages": chat.members_can_pin_messages,
            "slow_mode_seconds": chat.slow_mode_seconds,
            "restriction_count": sum(restrictions),
            "restriction_total": len(restrictions),
        },
        "signatures_enabled": chat.signatures_enabled,
        "comments_enabled": chat.comments_enabled,
        "allowed_reactions": allowed_reaction_emojis(chat),
        "reaction_choices": [{"emoji": emoji, "label": label} for emoji, label in MessageReaction.Emoji.choices],
        "member_count": len(memberships),
        "admin_count": len(admins),
        "admins": admins,
        "members": [_member_payload(actor, item) for item in memberships],
        "invite_links": links,
        "join_requests": join_requests,
        "pending_join_count": pending_count,
        "active_invite_count": sum(item["is_active"] for item in links),
        "recent_actions": logs,
        "urls": {
            "settings": reverse("messenger:community_settings", args=[chat.pk]),
            "statistics": reverse("messenger:community_statistics", args=[chat.pk]),
            "invite_action": reverse("messenger:community_invite_action", args=[chat.pk]),
            "join_request_action": reverse("messenger:community_join_request_action", args=[chat.pk]),
            "moderation": reverse("messenger:community_moderation", args=[chat.pk]),
            "member_action": reverse("messenger:community_member_action", args=[chat.pk]),
            "member_candidates": reverse("messenger:community_member_candidates", args=[chat.pk]),
            "profile": reverse("messenger:community_profile", args=[chat.pk]),
            "action": reverse("messenger:community_profile_action", args=[chat.pk]),
        },
    }


def _json_error(message, status=400, errors=None):
    payload = {"ok": False, "error": message}
    if errors is not None:
        payload["errors"] = errors
    return JsonResponse(payload, status=status)


@login_required
@require_GET
@rate_limit("community_moderation")
def community_statistics(request, chat_id):
    """Aggregate retained history, never message text or reader identities."""
    account_id = request.GET.get("account_id")
    if account_id is not None and account_id != str(request.user.pk):
        return _json_error("Аккаунт изменился.", status=409)
    actor = get_object_or_404(
        ChatParticipant.objects.select_related("chat"),
        chat_id=chat_id, user=request.user, is_hidden=False,
        chat__type__in=(Chat.Type.GROUP, Chat.Type.CHANNEL),
    )
    if not has_admin_right(actor, "manage_permissions"):
        return _json_error("Недостаточно прав для просмотра статистики.", status=403)
    if is_banned(actor.chat, request.user.pk):
        return _json_error("Сообщество недоступно.", status=403)
    try:
        days = int(request.GET.get("days", "7"))
        if days not in {7, 30}:
            raise ValueError
    except (TypeError, ValueError):
        return _json_error("Выберите 7 или 30 дней.")

    now = timezone.now()
    tz = timezone.get_current_timezone()
    today = timezone.localdate(now, timezone=tz)
    first = today - timedelta(days=days - 1)
    start = timezone.make_aware(datetime.combine(first, time.min), timezone=tz)
    history = Message.objects.filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now),
        chat_id=chat_id, is_deleted=False, created_at__gte=start, created_at__lte=now,
    )
    members = ChatParticipant.objects.filter(chat_id=chat_id, is_hidden=False)
    arrivals = members.filter(joined_at__gte=start, joined_at__lte=now)
    message_counts = dict(
        history.order_by().annotate(day=TruncDate("created_at", tzinfo=tz))
        .values("day").annotate(total=Count("pk")).values_list("day", "total")
    )
    member_counts = dict(
        arrivals.order_by().annotate(day=TruncDate("joined_at", tzinfo=tz))
        .values("day").annotate(total=Count("pk")).values_list("day", "total")
    )
    # Count first unique views during the selected calendar period, even
    # on older retained posts. Never fabricate dates for pre-migration views.
    channel_stats = None
    view_counts = {}
    if actor.chat.type == Chat.Type.CHANNEL:
        retained_views = ChannelPostView.objects.filter(
            Q(post__expires_at__isnull=True) | Q(post__expires_at__gt=now),
            post__chat_id=chat_id, post__is_deleted=False,
        )
        period_views = retained_views.filter(viewed_at__gte=start, viewed_at__lte=now)
        view_counts = dict(
            period_views.order_by().annotate(day=TruncDate("viewed_at", tzinfo=tz))
            .values("day").annotate(total=Count("pk")).values_list("day", "total")
        )
        published_views = retained_views.filter(post__in=history).count()
        published_count = sum(message_counts.values())
        channel_stats = {
            "views": sum(view_counts.values()),
            "reach": period_views.order_by().values("user_id").distinct().count(),
            "published_views": published_views,
            "average_views": round(published_views / published_count, 1) if published_count else 0,
            "undated_views": retained_views.filter(viewed_at__isnull=True).count(),
        }
    series = []
    for offset in range(days):
        day = first + timedelta(days=offset)
        series.append({
            "date": day.isoformat(),
            "messages": message_counts.get(day, 0),
            "new_members": member_counts.get(day, 0),
            "views": view_counts.get(day, 0),
        })
    response = JsonResponse({
        "ok": True, "account_id": request.user.pk, "days": days,
        "timezone": timezone.get_current_timezone_name(),
        "members": members.count(),
        "new_members": sum(member_counts.values()),
        "messages": sum(message_counts.values()),
        "active_authors": history.order_by().values("sender_id").distinct().count(),
        "reactions": MessageReaction.objects.filter(message__in=history).count(),
        "series": series,
        "channel_stats": channel_stats,
    })
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_GET
def community_profile(request, chat_id):
    chat = _collective_chat_for_user(request.user, chat_id)
    return JsonResponse({"ok": True, "profile": _profile_payload(request, chat)})


@login_required
@require_POST
@transaction.atomic
def community_profile_update(request, chat_id):
    chat = _collective_chat_for_user(request.user, chat_id)
    chat = get_object_or_404(Chat.objects.select_for_update(), pk=chat.pk)
    membership = get_object_or_404(ChatParticipant, chat=chat, user=request.user, is_hidden=False)
    if not has_admin_right(membership, "change_info"):
        return _json_error("Недостаточно прав для изменения информации.", status=403)

    form = CommunityProfileForm(request.POST, request.FILES, chat=chat)
    if not form.is_valid():
        return _json_error(
            "Проверьте заполненные поля.",
            status=400,
            errors=form.errors.get_json_data(),
        )

    old_title = chat.title
    old_username = chat.username or ""
    with transaction.atomic():
        chat.title = form.cleaned_data["title"]
        chat.description = form.cleaned_data["description"]
        chat.username = form.cleaned_data["username"] or None

        avatar = form.cleaned_data.get("avatar")
        remove_avatar = form.cleaned_data.get("remove_avatar")
        if remove_avatar and chat.avatar:
            chat.avatar.delete(save=False)
            chat.avatar = ""
        if avatar is not None:
            if chat.avatar:
                chat.avatar.delete(save=False)
            chat.avatar = avatar
        chat.save()
        changes = []
        if old_title != chat.title:
            changes.append("название")
        if old_username != (chat.username or ""):
            changes.append("тип/адрес")
        if changes or avatar is not None or remove_avatar:
            _log(
                chat,
                request.user,
                "edit_info",
                f"Изменена информация: {', '.join(changes) if changes else 'профиль'}",
            )

    chat.refresh_from_db()
    return JsonResponse({
        "ok": True,
        "profile": _profile_payload(request, chat),
        "settings": _settings_payload(request, chat),
    })


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def community_settings(request, chat_id):
    account_id = (request.POST if request.method == "POST" else request.GET).get("account_id")
    if account_id is not None and account_id != str(request.user.pk):
        return _json_error("Аккаунт изменился. Обновите страницу.", status=409)
    chat = _collective_chat_for_user(request.user, chat_id)
    if request.method == "POST":
        chat = get_object_or_404(Chat.objects.select_for_update(), pk=chat.pk)
    membership = get_object_or_404(ChatParticipant, chat=chat, user=request.user, is_hidden=False)
    if not _can_manage(membership):
        return _json_error("Управление доступно только администраторам.", status=403)

    if request.method == "GET":
        return JsonResponse({"ok": True, "settings": _settings_payload(request, chat)})

    section = request.POST.get("section", "").strip()
    right = {"type": "change_info", "permissions": "manage_permissions", "signatures": "change_info", "reactions": "manage_permissions", "comments": "manage_permissions"}.get(section)
    if right and not has_admin_right(membership, right):
        return _json_error("Недостаточно прав для изменения этих настроек.", status=403)
    if section == "type":
        visibility = request.POST.get("visibility", "private")
        raw_username = request.POST.get("username", "")
        if visibility not in {"public", "private"}:
            return _json_error("Неизвестный тип сообщества.")
        try:
            username = _clean_public_username(chat, raw_username) if visibility == "public" else ""
        except forms.ValidationError as error:
            return _json_error(error.messages[0])
        if visibility == "public" and not username:
            return _json_error("Для публичного сообщества нужен @адрес.")
        old = chat.username or ""
        chat.username = username or None
        chat.save(update_fields=("username", "updated_at"))
        if old != (chat.username or ""):
            _log(
                chat,
                request.user,
                "type",
                "Сообщество стало публичным." if chat.username else "Сообщество стало частным.",
            )

    elif section == "permissions":
        if chat.type != Chat.Type.GROUP:
            return _json_error("Права участников доступны только для групп.", status=400)
        try:
            slow_mode = int(request.POST.get("slow_mode_seconds", "0"))
        except (TypeError, ValueError):
            return _json_error("Некорректное значение медленного режима.")
        if slow_mode not in SLOW_MODE_VALUES:
            return _json_error("Некорректное значение медленного режима.")
        if "media_kinds" in request.POST:
            try:
                kinds = json.loads(request.POST["media_kinds"])
                if not isinstance(kinds, list) or any(type(kind) is not str or kind not in MEDIA_KINDS for kind in kinds):
                    raise ValueError
            except (TypeError, ValueError):
                return _json_error("Некорректные типы медиа.")
            selected = [kind for kind in MEDIA_KINDS if kind in kinds]
            chat.members_allowed_media = None if selected == list(MEDIA_KINDS) else selected
        chat.members_can_send_messages = _post_bool(request, "send_messages")
        chat.members_can_send_media = _post_bool(request, "send_media")
        chat.members_can_send_links = _post_bool(request, "send_links")
        chat.members_can_add_members = _post_bool(request, "add_members")
        chat.members_can_pin_messages = _post_bool(request, "pin_messages")
        chat.slow_mode_seconds = slow_mode
        chat.history_visible_to_new_members = _post_bool(request, "history_visible")
        chat.save(update_fields=(
            "members_can_send_messages",
            "members_can_send_media",
            "members_allowed_media",
            "members_can_send_links",
            "members_can_add_members",
            "members_can_pin_messages",
            "slow_mode_seconds",
            "history_visible_to_new_members",
            "updated_at",
        ))
        _log(chat, request.user, "permissions", "Изменены права участников группы.")

    elif section == "reactions":
        try:
            selected = json.loads(request.POST.get("reactions", ""))
            if not isinstance(selected, list) or any(
                type(emoji) is not str or emoji not in MessageReaction.Emoji.values for emoji in selected
            ):
                raise ValueError
        except (ValueError, TypeError):
            return _json_error("Некорректный набор реакций.")
        selected = [emoji for emoji in MessageReaction.Emoji.values if emoji in selected]
        new_value = None if selected == list(MessageReaction.Emoji.values) else selected
        if chat.allowed_reactions != new_value:
            chat.allowed_reactions = new_value
            chat.save(update_fields=("allowed_reactions", "updated_at"))
            _log(chat, request.user, "reactions", "Изменены доступные реакции: " + (" ".join(selected) or "отключены"))

    elif section == "comments":
        if chat.type != Chat.Type.CHANNEL:
            return _json_error("Обсуждения доступны только для каналов.")
        enabled = _post_bool(request, "enabled")
        if chat.comments_enabled != enabled:
            chat.comments_enabled = enabled
            chat.save(update_fields=("comments_enabled", "updated_at"))
            _log(chat, request.user, "comments", "Комментарии включены." if enabled else "Комментарии отключены.")

    elif section == "signatures":
        if chat.type != Chat.Type.CHANNEL:
            return _json_error("Подписи сообщений доступны только для каналов.", status=400)
        chat.signatures_enabled = _post_bool(request, "enabled")
        chat.save(update_fields=("signatures_enabled", "updated_at"))
        _log(
            chat,
            request.user,
            "signatures",
            "Подписи сообщений включены." if chat.signatures_enabled else "Подписи сообщений выключены.",
        )

    else:
        return _json_error("Неизвестный раздел настроек.")

    chat.refresh_from_db()
    return JsonResponse({
        "ok": True,
        "settings": _settings_payload(request, chat),
        "profile": _profile_payload(request, chat),
    })


@login_required
@require_POST
@transaction.atomic
def community_invite_action(request, chat_id):
    chat = _collective_chat_for_user(request.user, chat_id)
    chat = Chat.objects.select_for_update().get(pk=chat.pk)
    membership = get_object_or_404(ChatParticipant.objects.select_for_update(), chat=chat, user=request.user)
    if not has_admin_right(membership, "invite_users"):
        return _json_error("Недостаточно прав для управления приглашениями.", status=403)

    action = request.POST.get("action", "").strip()
    if action == "create":
        name = request.POST.get("name", "").strip()[:64]
        try:
            expires_hours = int(request.POST.get("expires_hours", "0") or 0)
            usage_limit = int(request.POST.get("usage_limit", "0") or 0)
        except (TypeError, ValueError):
            return _json_error("Проверьте срок действия и лимит использования.")
        if expires_hours not in {0, 1, 24, 168, 720}:
            return _json_error("Некорректный срок действия.")
        if usage_limit < 0 or usage_limit > 100000:
            return _json_error("Лимит использования должен быть от 0 до 100000.")
        invite = ChatInviteLink.objects.create(
            chat=chat,
            creator=request.user,
            token=secrets.token_urlsafe(24),
            name=name,
            expires_at=timezone.now() + timedelta(hours=expires_hours) if expires_hours else None,
            usage_limit=usage_limit or None,
            requires_approval=_post_bool(request, "requires_approval"),
        )
        _log(chat, request.user, "invite_create", f"Создана ссылка «{invite.name or 'Ссылка-приглашение'}».")
    elif action == "revoke":
        try:
            invite_id = int(request.POST.get("invite_id", "0"))
        except (TypeError, ValueError):
            return _json_error("Некорректная ссылка.")
        invite = get_object_or_404(ChatInviteLink.objects.select_for_update(), pk=invite_id, chat=chat)
        if invite.revoked_at is None:
            invite.revoked_at = timezone.now()
            invite.save(update_fields=("revoked_at",))
            ChatJoinRequest.objects.filter(invite=invite, status=ChatJoinRequest.Status.PENDING).update(
                status=ChatJoinRequest.Status.REJECTED, decided_at=invite.revoked_at, decided_by=request.user,
            )
            _log(chat, request.user, "invite_revoke", f"Отозвана ссылка «{invite.name or 'Ссылка-приглашение'}».")
    else:
        return _json_error("Неизвестное действие со ссылкой.")

    return JsonResponse({"ok": True, "settings": _settings_payload(request, chat)})


@login_required
@require_http_methods(["GET", "POST"])
@rate_limit("join_invite")
def join_invite(request, token):
    invite = ChatInviteLink.objects.select_related("chat").filter(token=token).first()
    if invite is None or not invite.is_active:
        messages.error(request, "Ссылка-приглашение недействительна или устарела.")
        return redirect("messenger:home")
    chat = invite.chat
    if is_banned(chat, request.user.pk):
        messages.error(request, "Вы заблокированы в этом сообществе.")
        return redirect("messenger:home")
    if request.method == "GET":
        if ChatParticipant.objects.filter(chat=chat, user=request.user, is_hidden=False).exists():
            return redirect("messenger:chat", chat_id=chat.pk)
        pending = ChatJoinRequest.objects.filter(chat=chat, user=request.user, status=ChatJoinRequest.Status.PENDING).exists()
        return render(request, "messenger/join_invite.html", {
            "invite": invite, "chat": chat, "member_count": chat.memberships.count(),
            "request_pending": pending,
        })
    if request.POST.get("account_id", str(request.user.pk)) != str(request.user.pk):
        messages.error(request, "Аккаунт изменился. Обновите страницу.")
        return redirect("messenger:home")

    with transaction.atomic():
        User.objects.select_for_update().only("id").get(pk=request.user.pk)
        chat = get_object_or_404(Chat.objects.select_for_update(), pk=chat.pk,
                                 type__in=(Chat.Type.GROUP, Chat.Type.CHANNEL))
        invite = ChatInviteLink.objects.select_for_update().filter(pk=invite.pk, chat=chat).first()
        if invite is None or not invite.is_active:
            messages.error(request, "Ссылка-приглашение недействительна или устарела.")
            return redirect("messenger:home")
        if is_banned(chat, request.user.pk):
            messages.error(request, "Вы заблокированы в этом сообществе.")
            return redirect("messenger:home")
        membership = ChatParticipant.objects.select_for_update().filter(chat=chat, user=request.user).first()
        if membership is None and invite.requires_approval:
            pending = ChatJoinRequest.objects.select_for_update().filter(chat=chat, user=request.user).first()
            if pending and pending.status == ChatJoinRequest.Status.PENDING:
                return redirect("messenger:my_join_requests")
            if pending and pending.status == ChatJoinRequest.Status.REJECTED and pending.decided_at and (
                pending.decided_at > timezone.now() - timedelta(minutes=10)
            ):
                messages.error(request, "После отклонения повторную заявку можно отправить через 10 минут.")
                return redirect("messenger:my_join_requests")
            if (ChatJoinRequest.objects.filter(user=request.user, status=ChatJoinRequest.Status.PENDING).count() >= 20
                    or ChatJoinRequest.objects.filter(chat=chat, status=ChatJoinRequest.Status.PENDING).count() >= 500):
                messages.error(request, "Достигнут лимит заявок. Попробуйте позже.")
                return redirect("messenger:my_join_requests")
            ChatJoinRequest.objects.update_or_create(chat=chat, user=request.user, defaults={
                "invite": invite, "status": ChatJoinRequest.Status.PENDING,
                "created_at": timezone.now(), "decided_at": None, "decided_by": None,
            })
            messages.success(request, "Заявка отправлена. Дождитесь одобрения администратора.")
            return redirect("messenger:my_join_requests")
        if membership is None:
            ChatParticipant.objects.create(chat=chat, user=request.user, role=ChatParticipant.Role.MEMBER,
                                           can_see_pre_join_history=chat.history_visible_to_new_members)
            invite.usage_count += 1
            invite.save(update_fields=("usage_count",))
            _log(chat, request.user, "join_invite", f"{request.user.display_name} вступил(а) по ссылке-приглашению.",
                 target_user=request.user)
        elif membership.is_hidden:
            ChatParticipant.objects.filter(pk=membership.pk).update(is_hidden=False)
        ChatJoinRequest.objects.filter(chat=chat, user=request.user, status=ChatJoinRequest.Status.PENDING).update(
            status=ChatJoinRequest.Status.APPROVED, decided_at=timezone.now(),
        )
    return redirect("messenger:chat", chat_id=chat.pk)


@login_required
@require_POST
@rate_limit("join_request_action")
def community_join_request_action(request, chat_id):
    if request.POST.get("account_id") != str(request.user.pk):
        return _json_error("Аккаунт изменился. Обновите страницу.", status=409)
    chat = _collective_chat_for_user(request.user, chat_id)
    action = request.POST.get("action")
    if action not in {"approve", "reject"}:
        return _json_error("Неизвестное действие.")
    try:
        request_id = int(request.POST.get("request_id", ""))
        if not 0 < request_id <= 9223372036854775807:
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        return _json_error("Некорректная заявка.")
    with transaction.atomic():
        chat = Chat.objects.select_for_update().get(pk=chat.pk)
        actor = get_object_or_404(ChatParticipant.objects.select_for_update(), chat=chat, user=request.user, is_hidden=False)
        if not has_admin_right(actor, "invite_users"):
            return _json_error("Недостаточно прав для рассмотрения заявок.", status=403)
        row = get_object_or_404(ChatJoinRequest.objects.select_for_update(), pk=request_id, chat=chat)
        if request.POST.get("revision") != row.created_at.isoformat():
            return _json_error("Заявка изменилась. Обновите список.", status=409)
        desired = ChatJoinRequest.Status.APPROVED if action == "approve" else ChatJoinRequest.Status.REJECTED
        if row.status == desired:
            return JsonResponse({"ok": True, "settings": _settings_payload(request, chat), "replayed": True})
        if row.status != ChatJoinRequest.Status.PENDING:
            return _json_error("Заявка уже рассмотрена или отменена.", status=409)
        if action == "approve":
            if is_banned(chat, row.user_id):
                return _json_error("Пользователь заблокирован в сообществе.", status=403)
            invite = ChatInviteLink.objects.select_for_update().filter(pk=row.invite_id, chat=chat).first()
            if invite is None or not invite.is_active:
                return _json_error("Ссылка больше не действует. Отклоните заявку или предложите новую ссылку.", status=409)
            if not row.user.is_active:
                return _json_error("Аккаунт пользователя недоступен.", status=409)
            membership, created = ChatParticipant.objects.get_or_create(
                chat=chat, user_id=row.user_id,
                defaults={"role": ChatParticipant.Role.MEMBER,
                          "can_see_pre_join_history": chat.history_visible_to_new_members},
            )
            if created:
                invite.usage_count += 1
                invite.save(update_fields=["usage_count"])
            elif membership.is_hidden:
                membership.is_hidden = False
                membership.save(update_fields=["is_hidden"])
        row.status = desired
        row.decided_at = timezone.now()
        row.decided_by = request.user
        row.save(update_fields=["status", "decided_at", "decided_by"])
        _log(chat, request.user, "join_request_" + action,
             ("Одобрена заявка: " if action == "approve" else "Отклонена заявка: ") + row.user.display_name,
             target_user=row.user)
    return JsonResponse({"ok": True, "settings": _settings_payload(request, chat)})


@login_required
@require_http_methods(["GET", "POST"])
@rate_limit("join_request_action")
def my_join_requests(request):
    if request.method == "POST":
        if request.POST.get("account_id") != str(request.user.pk):
            messages.error(request, "Аккаунт изменился. Обновите страницу.")
            return redirect("messenger:my_join_requests")
        try:
            request_id = int(request.POST.get("request_id", ""))
            if not 0 < request_id <= 9223372036854775807:
                raise ValueError
        except (ValueError, TypeError, OverflowError):
            return redirect("messenger:my_join_requests")
        if request.POST.get("action") != "cancel":
            return redirect("messenger:my_join_requests")
        with transaction.atomic():
            row = ChatJoinRequest.objects.select_for_update().filter(pk=request_id, user=request.user, status=ChatJoinRequest.Status.PENDING).first()
            if row and request.POST.get("revision") == row.created_at.isoformat():
                row.status = ChatJoinRequest.Status.CANCELED
                row.decided_at = timezone.now()
                row.decided_by = request.user
                row.save(update_fields=["status", "decided_at", "decided_by"])
                messages.success(request, "Заявка отменена.")
        return redirect("messenger:my_join_requests")
    own = ChatJoinRequest.objects.filter(user=request.user).select_related("chat", "invite")
    pending = list(own.filter(status=ChatJoinRequest.Status.PENDING))
    decided = list(own.exclude(status=ChatJoinRequest.Status.PENDING).order_by("-decided_at", "-pk")[:100])
    joined_ids = set(ChatParticipant.objects.filter(user=request.user, is_hidden=False).values_list("chat_id", flat=True))
    response = render(request, "messenger/join_requests.html", {
        "join_rows": pending + decided, "joined_ids": joined_ids,
    })
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_GET
def community_member_candidates(request, chat_id):
    chat = _collective_chat_for_user(request.user, chat_id)
    actor = _membership(chat, request.user)
    if not _can_add_members(chat, actor):
        return _json_error("Добавлять участников здесь запрещено.", status=403)

    query = request.GET.get("q", "").strip().lstrip("@")[:150]
    existing_ids = ChatParticipant.objects.filter(chat=chat).values_list("user_id", flat=True)
    banned_ids = active_sanctions(chat).filter(banned=True).values_list("user_id", flat=True)
    users = User.objects.filter(is_active=True).exclude(pk__in=existing_ids).exclude(pk__in=banned_ids)
    if query:
        users = users.filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
        )
    users = list(users.order_by("-last_seen_at", "username")[:80])
    users = [
        user
        for user in users
        if not is_blocked_between(request.user, user)
        and privacy_allows(user, request.user, "invites")
    ][:40]
    return JsonResponse(
        {
            "ok": True,
            "results": [
                {
                    "id": user.pk,
                    "display_name": user.display_name,
                    "username": user.username,
                    "initials": user.initials,
                    "avatar_url": (
                        user.avatar_url
                        if user.avatar and privacy_allows(user, request.user, "profile_photo")
                        else ""
                    ),
                    "presence": _presence_text(user, request.user),
                }
                for user in users
            ],
        }
    )


@login_required
@require_POST
@transaction.atomic
def community_member_action(request, chat_id):
    chat = _collective_chat_for_user(request.user, chat_id)
    chat = Chat.objects.select_for_update().get(pk=chat.pk)
    actor = get_object_or_404(ChatParticipant.objects.select_for_update(), chat=chat, user=request.user, is_hidden=False)
    action = request.POST.get("action", "").strip()

    if action == "add":
        if not _can_add_members(chat, actor):
            return _json_error("Добавлять участников здесь запрещено.", status=403)
    elif action == "remove":
        if not has_admin_right(actor, "moderate_members"):
            return _json_error("Недостаточно прав для удаления участников.", status=403)
    elif not _can_manage(actor):
        return _json_error("Управлять участниками могут только администраторы.", status=403)

    username = request.POST.get("username", "").strip().lstrip("@")[:150]
    if not username:
        return _json_error("Укажите пользователя.")

    target_user = User.objects.filter(username__iexact=username, is_active=True).first()
    if target_user is None:
        return _json_error("Пользователь не найден.", status=404)
    target = ChatParticipant.objects.filter(chat=chat, user=target_user).first()

    if action == "add":
        if target is not None:
            return _json_error("Пользователь уже состоит здесь.")
        if is_banned(chat, target_user.pk):
            return _json_error("Пользователь заблокирован в сообществе.", status=403)
        if is_blocked_between(request.user, target_user):
            return _json_error("Пользователь недоступен из-за блокировки.", status=403)
        if not privacy_allows(target_user, request.user, "invites"):
            return _json_error(
                "Пользователь запретил добавлять себя в группы и каналы.",
                status=403,
            )
        with transaction.atomic():
            chat = Chat.objects.select_for_update().get(pk=chat.pk)
            if ChatParticipant.objects.filter(chat=chat, user=target_user).exists():
                return _json_error("Пользователь уже состоит здесь.")
            ChatParticipant.objects.create(
                chat=chat,
                user=target_user,
                role=ChatParticipant.Role.MEMBER,
                can_see_pre_join_history=chat.history_visible_to_new_members,
                **invited_membership_defaults(request.user, target_user),
            )
            ChatJoinRequest.objects.filter(chat=chat, user=target_user, status=ChatJoinRequest.Status.PENDING).update(
                status=ChatJoinRequest.Status.APPROVED, decided_at=timezone.now(), decided_by=request.user,
            )
        _log(
            chat,
            request.user,
            "member_add",
            f"Добавлен участник {target_user.display_name}.",
            target_user=target_user,
        )
    elif action == "remove":
        if target is None:
            return _json_error("Пользователь уже не состоит здесь.")
        if target.user_id == request.user.pk:
            return _json_error("Для выхода используйте действие «Покинуть».")
        if target.role == ChatParticipant.Role.OWNER:
            return _json_error("Владельца нельзя удалить из сообщества.", status=403)
        if actor.role == ChatParticipant.Role.ADMIN and target.role != ChatParticipant.Role.MEMBER:
            return _json_error("Администратор не может удалить другого администратора.", status=403)
        target.delete()
        _log(
            chat,
            request.user,
            "member_remove",
            f"Удалён участник {target_user.display_name}.",
            target_user=target_user,
        )
    elif action == "transfer_owner":
        if actor.role != ChatParticipant.Role.OWNER:
            return _json_error("Передать права владельца может только владелец.", status=403)
        if target is None:
            return _json_error("Пользователь не состоит здесь.")
        if target.user_id == request.user.pk:
            return _json_error("Нельзя передать права владельца самому себе.")
        if target.role == ChatParticipant.Role.OWNER:
            return _json_error("Этот пользователь уже владелец.", status=400)

        with transaction.atomic():
            locked_actor = ChatParticipant.objects.select_for_update().get(pk=actor.pk)
            locked_target = ChatParticipant.objects.select_for_update().get(pk=target.pk)
            if locked_actor.role != ChatParticipant.Role.OWNER:
                return _json_error("Права владельца уже были переданы.", status=409)
            if locked_target.role == ChatParticipant.Role.OWNER:
                return _json_error("Этот пользователь уже владелец.", status=409)

            locked_target.role = ChatParticipant.Role.OWNER
            locked_target.admin_permissions = None
            locked_target.save(update_fields=("role", "admin_permissions"))
            locked_actor.role = ChatParticipant.Role.ADMIN
            locked_actor.admin_permissions = None
            locked_actor.save(update_fields=("role", "admin_permissions"))
            ChatMemberModeration.objects.filter(chat=chat, user=target_user).delete()
            _log(
                chat,
                request.user,
                "owner_transfer",
                f"Права владельца переданы {target_user.display_name}.",
                target_user=target_user,
            )
        actor.role = ChatParticipant.Role.ADMIN
        target.role = ChatParticipant.Role.OWNER
    elif action == "role":
        if actor.role != ChatParticipant.Role.OWNER:
            return _json_error("Менять администраторов может только владелец.", status=403)
        if target is None:
            return _json_error("Пользователь не состоит здесь.")
        if target.role == ChatParticipant.Role.OWNER:
            return _json_error("Роль владельца здесь не изменяется.", status=403)
        new_role = request.POST.get("role", "")
        if new_role not in {ChatParticipant.Role.ADMIN, ChatParticipant.Role.MEMBER}:
            return _json_error("Неизвестная роль.")
        if target.role != new_role:
            target.role = new_role
            target.admin_permissions = None
            target.save(update_fields=("role", "admin_permissions"))
        if new_role == ChatParticipant.Role.ADMIN:
            ChatMemberModeration.objects.filter(chat=chat, user=target_user).delete()
        _log(
            chat,
            request.user,
            "role",
            (
                f"{target_user.display_name} назначен(а) администратором."
                if new_role == ChatParticipant.Role.ADMIN
                else f"{target_user.display_name} больше не администратор."
            ),
            target_user=target_user,
        )
    else:
        return _json_error("Неизвестное действие с участником.")

    chat.refresh_from_db()
    return JsonResponse({
        "ok": True,
        "profile": _profile_payload(request, chat),
        "settings": _settings_payload(request, chat) if _can_manage(actor) else None,
    })


@login_required
@require_POST
def community_profile_action(request, chat_id):
    chat = _collective_chat_for_user(request.user, chat_id)
    membership = _membership(chat, request.user)
    action = request.POST.get("action", "").strip()

    if action == "mute":
        membership.is_muted = not membership.notifications_muted
        membership.muted_until = None
        membership.save(update_fields=("is_muted", "muted_until"))
    elif action == "archive":
        with transaction.atomic():
            membership = ChatParticipant.objects.select_for_update().get(pk=membership.pk)
            set_membership_archived(membership, not membership.is_archived)
    elif action == "leave":
        if membership.role == ChatParticipant.Role.OWNER:
            return _json_error(
                "Владелец не может выйти, пока права владельца не переданы.",
                status=403,
            )
        _log(
            chat,
            request.user,
            "leave",
            f"{request.user.display_name} покинул(а) сообщество.",
            target_user=request.user,
        )
        membership.delete()
        return JsonResponse(
            {
                "ok": True,
                "left": True,
                "redirect_url": reverse("messenger:home"),
            }
        )
    elif action == "delete":
        if membership.role != ChatParticipant.Role.OWNER:
            return _json_error("Удалить сообщество может только владелец.", status=403)
        with transaction.atomic():
            for attachment in MessageAttachment.objects.filter(message__chat=chat):
                if attachment.file:
                    attachment.file.delete(save=False)
            if chat.avatar:
                chat.avatar.delete(save=False)
            chat.delete()
        return JsonResponse(
            {
                "ok": True,
                "deleted": True,
                "redirect_url": reverse("messenger:home"),
            }
        )
    else:
        return _json_error("Неизвестное действие с сообществом.")

    chat.refresh_from_db()
    return JsonResponse({"ok": True, "profile": _profile_payload(request, chat)})
