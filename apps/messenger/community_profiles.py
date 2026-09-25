from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .forms import IMAGE_FORMATS, MEDIA_CONTENT_TYPES, _validate_inline_image
from .models import Chat, ChatParticipant, MessageAttachment
from .services import attachment_url

User = get_user_model()


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
        if self.chat.type != Chat.Type.CHANNEL:
            return self.chat.username or ""
        username = self.cleaned_data.get("username", "").strip().lstrip("@").lower()
        if not username:
            return ""
        if len(username) < 5 or not username.replace("_", "").isalnum():
            raise forms.ValidationError(
                "Адрес: минимум 5 символов, только буквы, цифры и подчёркивание."
            )
        if Chat.objects.filter(username__iexact=username).exclude(pk=self.chat.pk).exists():
            raise forms.ValidationError("Этот адрес уже занят другим чатом.")
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Этот адрес уже занят пользователем.")
        return username

    def clean(self):
        cleaned = super().clean()
        if self.chat.type != Chat.Type.CHANNEL:
            cleaned["visibility"] = self.VISIBILITY_PRIVATE
            cleaned["username"] = self.chat.username or ""
            return cleaned
        visibility = cleaned.get("visibility") or (
            self.VISIBILITY_PUBLIC if self.chat.username else self.VISIBILITY_PRIVATE
        )
        if visibility == self.VISIBILITY_PUBLIC and not cleaned.get("username"):
            self.add_error("username", "У публичного канала должен быть @адрес.")
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

    attachments = list(
        MessageAttachment.objects.filter(
            message__chat=chat,
            message__is_deleted=False,
        )
        .select_related("message")
        .order_by("-id")[:90]
    )
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
        "can_add_members": can_manage,
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

    with transaction.atomic():
        chat.title = form.cleaned_data["title"]
        chat.description = form.cleaned_data["description"]
        if chat.type == Chat.Type.CHANNEL:
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

    chat.refresh_from_db()
    return JsonResponse({"ok": True, "profile": _profile_payload(request, chat)})


@login_required
@require_GET
def community_member_candidates(request, chat_id):
    chat = _collective_chat_for_user(request.user, chat_id)
    actor = _membership(chat, request.user)
    if not _can_manage(actor):
        return _json_error("Добавлять участников могут только администраторы.", status=403)

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
    if not _can_manage(actor):
        return _json_error("Управлять участниками могут только администраторы.", status=403)

    action = request.POST.get("action", "").strip()
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
    elif action == "role":
        if actor.role != ChatParticipant.Role.OWNER:
            return _json_error("Менять администраторов может только владелец.", status=403)
        if target is None:
            return _json_error("Пользователь не состоит здесь.")
        if target.role == ChatParticipant.Role.OWNER:
            return _json_error("Роль владельца здесь не изменяется.", status=403)
        role = request.POST.get("role", "")
        if role not in {ChatParticipant.Role.ADMIN, ChatParticipant.Role.MEMBER}:
            return _json_error("Неизвестная роль.")
        target.role = role
        target.save(update_fields=("role",))
    else:
        return _json_error("Неизвестное действие с участником.")

    chat.refresh_from_db()
    return JsonResponse({"ok": True, "profile": _profile_payload(request, chat)})


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
        membership.delete()
        return JsonResponse(
            {
                "ok": True,
                "left": True,
                "redirect_url": reverse("messenger:home"),
            }
        )
    else:
        return _json_error("Неизвестное действие с сообществом.")

    chat.refresh_from_db()
    return JsonResponse({"ok": True, "profile": _profile_payload(request, chat)})
