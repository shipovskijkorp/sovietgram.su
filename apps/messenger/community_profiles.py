import secrets
from datetime import timedelta

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .forms import IMAGE_FORMATS, MEDIA_CONTENT_TYPES, _validate_inline_image
from .models import (
    Chat,
    ChatAdminLog,
    ChatInviteLink,
    ChatParticipant,
    MessageAttachment,
)
from .services import attachment_url

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


def _collective_chat_for_user(user, chat_id):
    return get_object_or_404(
        Chat.objects.filter(
            pk=chat_id,
            type__in=(Chat.Type.GROUP, Chat.Type.CHANNEL),
            participants=user,
        ).distinct()
    )


def _membership(chat, user):
    return get_object_or_404(ChatParticipant, chat=chat, user=user)


def _presence_text(user):
    if user.is_online:
        return "в сети"
    if not user.last_seen_at:
        return "был(а) давно"
    delta = timezone.now() - user.last_seen_at
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
    return _can_manage(membership) or (
        chat.type == Chat.Type.GROUP and chat.members_can_add_members
    )


def _clean_public_username(chat, raw):
    username = (raw or "").strip().lstrip("@").lower()
    if not username:
        return ""
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
    actor_is_admin = actor.role == ChatParticipant.Role.ADMIN
    removable = (
        user.pk != actor.user_id
        and membership.role != ChatParticipant.Role.OWNER
        and (
            actor_is_owner
            or (actor_is_admin and membership.role == ChatParticipant.Role.MEMBER)
        )
    )
    changeable = (
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
        "avatar_url": user.avatar.url if user.avatar else "",
        "presence": _presence_text(user),
        "role": membership.role,
        "role_label": membership.get_role_display(),
        "profile_url": reverse("accounts:public_profile", args=[user.username]),
        "is_self": user.pk == actor.user_id,
        "can_remove": removable,
        "can_change_role": changeable,
    }


def _visible_attachments(chat, membership):
    query = MessageAttachment.objects.filter(
        message__chat=chat,
        message__is_deleted=False,
    )
    if (
        not chat.history_visible_to_new_members
        and not membership.can_see_pre_join_history
    ):
        query = query.filter(message__created_at__gte=membership.joined_at)
    return query.select_related("message").order_by("-id")


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

    attachments = list(_visible_attachments(chat, actor)[:90])
    attachment_items = [
        {
            "id": item.pk,
            "kind": item.kind,
            "name": item.original_name,
            "size": item.size,
            "url": attachment_url(item),
            "created_at": timezone.localtime(item.created_at).strftime("%d.%m.%Y %H:%M"),
            "message_url": f"{reverse('messenger:chat', args=[chat.pk])}?message={item.message_id}#message-{item.message_id}",
        }
        for item in attachments
    ]
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
        "can_add_members": _can_add_members(chat, actor),
        "can_leave": actor.role != ChatParticipant.Role.OWNER,
        "is_muted": actor.is_muted,
        "is_archived": actor.is_archived,
        "created_at": timezone.localtime(chat.created_at).strftime("%d.%m.%Y"),
        "attachments": attachment_items,
        "media_count": sum(item.kind in {MessageAttachment.Kind.IMAGE, MessageAttachment.Kind.VIDEO} for item in attachments),
        "file_count": sum(item.kind not in {MessageAttachment.Kind.IMAGE, MessageAttachment.Kind.VIDEO} for item in attachments),
        "urls": {
            "chat": reverse("messenger:chat", args=[chat.pk]),
            "profile": reverse("messenger:community_profile", args=[chat.pk]),
            "update": reverse("messenger:community_profile_update", args=[chat.pk]),
            "member_action": reverse("messenger:community_member_action", args=[chat.pk]),
            "member_candidates": reverse("messenger:community_member_candidates", args=[chat.pk]),
            "action": reverse("messenger:community_profile_action", args=[chat.pk]),
            "settings": reverse("messenger:community_settings", args=[chat.pk]),
            "invite_action": reverse("messenger:community_invite_action", args=[chat.pk]),
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
    ]
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
        "can_delete": actor.role == ChatParticipant.Role.OWNER,
        "history_visible_to_new_members": chat.history_visible_to_new_members,
        "permissions": {
            "send_messages": chat.members_can_send_messages,
            "send_media": chat.members_can_send_media,
            "send_links": chat.members_can_send_links,
            "add_members": chat.members_can_add_members,
            "pin_messages": chat.members_can_pin_messages,
            "slow_mode_seconds": chat.slow_mode_seconds,
            "restriction_count": sum(restrictions),
            "restriction_total": len(restrictions),
        },
        "signatures_enabled": chat.signatures_enabled,
        "member_count": len(memberships),
        "admin_count": len(admins),
        "admins": admins,
        "members": [_member_payload(actor, item) for item in memberships],
        "invite_links": links,
        "active_invite_count": sum(item["is_active"] for item in links),
        "recent_actions": logs,
        "urls": {
            "settings": reverse("messenger:community_settings", args=[chat.pk]),
            "invite_action": reverse("messenger:community_invite_action", args=[chat.pk]),
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
def community_profile(request, chat_id):
    chat = _collective_chat_for_user(request.user, chat_id)
    return JsonResponse({"ok": True, "profile": _profile_payload(request, chat)})


@login_required
@require_POST
def community_profile_update(request, chat_id):
    chat = _collective_chat_for_user(request.user, chat_id)
    membership = _membership(chat, request.user)
    if not _can_manage(membership):
        return _json_error("Изменять информацию могут только администраторы.", status=403)

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
def community_settings(request, chat_id):
    chat = _collective_chat_for_user(request.user, chat_id)
    membership = _membership(chat, request.user)
    if not _can_manage(membership):
        return _json_error("Управление доступно только администраторам.", status=403)

    if request.method == "GET":
        return JsonResponse({"ok": True, "settings": _settings_payload(request, chat)})

    section = request.POST.get("section", "").strip()
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
            "members_can_send_links",
            "members_can_add_members",
            "members_can_pin_messages",
            "slow_mode_seconds",
            "history_visible_to_new_members",
            "updated_at",
        ))
        _log(chat, request.user, "permissions", "Изменены права участников группы.")

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
def community_invite_action(request, chat_id):
    chat = _collective_chat_for_user(request.user, chat_id)
    membership = _membership(chat, request.user)
    if not _can_manage(membership):
        return _json_error("Управлять ссылками могут только администраторы.", status=403)

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
        )
        _log(chat, request.user, "invite_create", f"Создана ссылка «{invite.name or 'Ссылка-приглашение'}».")
    elif action == "revoke":
        try:
            invite_id = int(request.POST.get("invite_id", "0"))
        except (TypeError, ValueError):
            return _json_error("Некорректная ссылка.")
        invite = get_object_or_404(ChatInviteLink, pk=invite_id, chat=chat)
        if invite.revoked_at is None:
            invite.revoked_at = timezone.now()
            invite.save(update_fields=("revoked_at",))
            _log(chat, request.user, "invite_revoke", f"Отозвана ссылка «{invite.name or 'Ссылка-приглашение'}».")
    else:
        return _json_error("Неизвестное действие со ссылкой.")

    return JsonResponse({"ok": True, "settings": _settings_payload(request, chat)})


@login_required
@require_GET
def join_invite(request, token):
    with transaction.atomic():
        invite = (
            ChatInviteLink.objects.select_for_update()
            .select_related("chat")
            .filter(token=token)
            .first()
        )
        if invite is None or not invite.is_active:
            messages.error(request, "Ссылка-приглашение недействительна или устарела.")
            return redirect("messenger:home")

        chat = invite.chat
        membership, created = ChatParticipant.objects.get_or_create(
            chat=chat,
            user=request.user,
            defaults={
                "role": ChatParticipant.Role.MEMBER,
                "can_see_pre_join_history": chat.history_visible_to_new_members,
            },
        )
        if created:
            invite.usage_count += 1
            invite.save(update_fields=("usage_count",))
            _log(
                chat,
                request.user,
                "join_invite",
                f"{request.user.display_name} вступил(а) по ссылке-приглашению.",
                target_user=request.user,
            )
    return redirect("messenger:chat", chat_id=chat.pk)


@login_required
@require_GET
def community_member_candidates(request, chat_id):
    chat = _collective_chat_for_user(request.user, chat_id)
    actor = _membership(chat, request.user)
    if not _can_add_members(chat, actor):
        return _json_error("Добавлять участников здесь запрещено.", status=403)

    query = request.GET.get("q", "").strip().lstrip("@")[:150]
    existing_ids = ChatParticipant.objects.filter(chat=chat).values_list("user_id", flat=True)
    users = User.objects.filter(is_active=True).exclude(pk__in=existing_ids)
    if query:
        users = users.filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
        )
    users = list(users.order_by("-last_seen_at", "username")[:40])
    return JsonResponse(
        {
            "ok": True,
            "results": [
                {
                    "display_name": user.display_name,
                    "username": user.username,
                    "initials": user.initials,
                    "avatar_url": user.avatar.url if user.avatar else "",
                    "presence": _presence_text(user),
                }
                for user in users
            ],
        }
    )


@login_required
@require_POST
def community_member_action(request, chat_id):
    chat = _collective_chat_for_user(request.user, chat_id)
    actor = _membership(chat, request.user)
    action = request.POST.get("action", "").strip()

    if action == "add":
        if not _can_add_members(chat, actor):
            return _json_error("Добавлять участников здесь запрещено.", status=403)
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
        ChatParticipant.objects.create(
            chat=chat,
            user=target_user,
            role=ChatParticipant.Role.MEMBER,
            can_see_pre_join_history=chat.history_visible_to_new_members,
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
        target.role = new_role
        target.save(update_fields=("role",))
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
        membership.is_muted = not membership.is_muted
        membership.save(update_fields=("is_muted",))
    elif action == "archive":
        membership.is_archived = not membership.is_archived
        membership.save(update_fields=("is_archived",))
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
