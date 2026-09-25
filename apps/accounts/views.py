import json
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import (
    IdentifierAuthenticationForm,
    OverlayProfileForm,
    ProfileForm,
    RegisterForm,
    UserSettingsForm,
)
from .models import User, UserBlock
from .multiaccount import (
    activate_account,
    add_authenticated_account,
    remember_current_account,
    remove_current_account,
)
from .privacy import (
    AUTO_DELETE_CHOICES,
    INACTIVITY_CHOICES,
    active_sessions_payload,
    auto_delete_label,
    blocked_users_payload,
    inactivity_label,
    is_blocked_between,
    privacy_allows,
    privacy_rule_payload,
    remember_session_device,
    set_privacy_rule,
    terminate_sessions,
)


def _subscriber_label(count):
    count = int(count or 0)
    mod10 = count % 10
    mod100 = count % 100
    if mod10 == 1 and mod100 != 11:
        word = "подписчик"
    elif mod10 in {2, 3, 4} and mod100 not in {12, 13, 14}:
        word = "подписчика"
    else:
        word = "подписчиков"
    return f"{count} {word}"


def _personal_channel_payload(channel, viewer=None):
    # Telegram only allows a creator-owned public broadcast channel here.
    # Do not expose legacy/private selections in a public profile payload.
    if channel is None or not channel.username:
        return None

    last_message = (
        channel.messages.filter(is_deleted=False)
        .select_related("sender")
        .prefetch_related("attachments")
        .order_by("-id")
        .first()
    )
    if last_message:
        created = timezone.localtime(last_message.created_at)
        if created.date() == timezone.localdate():
            last_message_time = f"{created:%H:%M}"
        else:
            last_message_time = f"{created:%d.%m.%Y}"
        preview = last_message.preview
    else:
        last_message_time = ""
        preview = channel.description.strip() or "Публикаций пока нет"

    subscriber_count = channel.memberships.count()

    is_member = bool(
        viewer
        and getattr(viewer, "is_authenticated", False)
        and channel.memberships.filter(user=viewer).exists()
    )
    if is_member:
        open_url = reverse("messenger:chat", args=[channel.pk])
        open_method = "get"
    elif channel.username and viewer and getattr(viewer, "is_authenticated", False):
        open_url = reverse("messenger:join_public_chat", args=[channel.username])
        open_method = "post"
    else:
        open_url = ""
        open_method = ""

    return {
        "id": channel.pk,
        "title": channel.title,
        "username": channel.username or "",
        "avatar_url": channel.avatar.url if channel.avatar else "",
        "last_message_preview": preview,
        "last_message_time": last_message_time,
        "subscriber_count": subscriber_count,
        "subscriber_text": _subscriber_label(subscriber_count),
        "open_url": open_url,
        "open_method": open_method,
    }


class SovietgramLoginView(LoginView):
    authentication_form = IdentifierAuthenticationForm
    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        remember_current_account(self.request)
        remember_session_device(self.request)
        return response


class SovietgramLogoutView:
    @classmethod
    def as_view(cls):
        @login_required
        @require_POST
        def view(request):
            switched = remove_current_account(request)
            if switched is not None:
                messages.success(request, f"Переключено на @{switched.username}.")
                return redirect("messenger:home")
            logout(request)
            return redirect("accounts:login")

        return view


class SovietgramPasswordChangeView(LoginRequiredMixin, PasswordChangeView):
    template_name = "accounts/password_change.html"

    def get_success_url(self):
        return f"{reverse('messenger:home')}?settings=privacy"

    def get(self, request, *args, **kwargs):
        return redirect(f"{reverse('messenger:home')}?settings=password")

    def form_valid(self, form):
        user = form.save()
        update_session_auth_hash(self.request, user)
        if self.request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"ok": True})
        messages.success(self.request, "Пароль изменён.")
        return redirect(self.get_success_url())

    def form_invalid(self, form):
        if self.request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse(
                {"ok": False, "errors": form.errors.get_json_data()},
                status=400,
            )
        return super().form_invalid(form)


def register(request):
    if request.user.is_authenticated:
        return redirect("messenger:home")

    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user, backend="apps.accounts.backends.EmailOrUsernameBackend")
        remember_current_account(request)
        remember_session_device(request)
        messages.success(request, "Учётная запись создана.")
        return redirect("messenger:home")

    return render(request, "accounts/register.html", {"form": form})


@login_required
def add_account(request):
    mode = request.POST.get("mode") or request.GET.get("mode") or "login"
    mode = "register" if mode == "register" else "login"
    backend = "apps.accounts.backends.EmailOrUsernameBackend"

    login_form = IdentifierAuthenticationForm(
        request=request,
        data=request.POST if request.method == "POST" and mode == "login" else None,
    )
    register_form = RegisterForm(
        request.POST if request.method == "POST" and mode == "register" else None
    )

    if request.method == "POST" and mode == "login" and login_form.is_valid():
        user = login_form.get_user()
        add_authenticated_account(request, user, backend)
        remember_session_device(request)
        messages.success(request, f"Аккаунт @{user.username} добавлен.")
        return redirect("messenger:home")

    if request.method == "POST" and mode == "register" and register_form.is_valid():
        user = register_form.save()
        add_authenticated_account(request, user, backend)
        remember_session_device(request)
        messages.success(request, f"Аккаунт @{user.username} создан и добавлен.")
        return redirect("messenger:home")

    return render(
        request,
        "accounts/add_account.html",
        {
            "mode": mode,
            "form": login_form if mode == "login" else register_form,
            "login_form": login_form,
            "register_form": register_form,
        },
    )


@login_required
@require_POST
def switch_account(request, user_id):
    user = activate_account(request, user_id)
    if user is None:
        messages.error(request, "Сеанс этого аккаунта истёк. Войдите в него снова.")
        return redirect("accounts:add_account")
    return redirect("messenger:home")


@login_required
def profile(request):
    old_avatar_name = request.user.avatar.name if request.user.avatar else ""
    old_avatar_storage = request.user.avatar.storage if request.user.avatar else None
    wants_json = request.headers.get("x-requested-with") == "XMLHttpRequest"

    if wants_json and request.method == "POST":
        form = OverlayProfileForm(request.POST, request.FILES, instance=request.user)
        if not form.is_valid():
            return JsonResponse(
                {"ok": False, "errors": form.errors.get_json_data()},
                status=400,
            )
        user = form.save()
        if request.FILES.get("avatar") and old_avatar_name and old_avatar_storage:
            if old_avatar_name != user.avatar.name:
                old_avatar_storage.delete(old_avatar_name)
        return JsonResponse(
            {
                "ok": True,
                "display_name": user.display_name,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "username": user.username,
                "bio": user.bio,
                "avatar_url": user.avatar.url if user.avatar else "",
                "initials": user.initials,
                "birthday": user.birthday.isoformat() if user.birthday else "",
                "birthday_display": user.birthday.strftime("%d.%m.%Y") if user.birthday else "",
                "personal_channel": _personal_channel_payload(user.personal_channel, request.user),
                "profile_url": reverse("accounts:public_profile", args=[user.username]),
                "remove_avatar_url": reverse("accounts:remove_avatar"),
            }
        )

    form = ProfileForm(request.POST or None, request.FILES or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        if request.FILES.get("avatar") and old_avatar_name and old_avatar_storage:
            if old_avatar_name != user.avatar.name:
                old_avatar_storage.delete(old_avatar_name)
        messages.success(request, "Профиль сохранён.")
        return redirect("accounts:profile")

    return render(request, "accounts/profile.html", {"form": form})


_BOOLEAN_SETTINGS = {
    "enter_to_send",
    "keep_archived_chats",
    "archive_unknown_chats",
    "archive_in_main_menu",
}


def _parse_boolean_setting(value):
    normalized = str(value or "").strip().lower()
    if normalized in {"1", "true", "on", "yes"}:
        return True
    if normalized in {"0", "false", "off", "no"}:
        return False
    raise ValueError("Некорректное значение настройки.")


def _parse_id_list(raw):
    try:
        values = json.loads(raw or "[]")
    except json.JSONDecodeError:
        values = []
    if not isinstance(values, list):
        return []
    result = []
    for value in values:
        try:
            result.append(int(value))
        except (TypeError, ValueError):
            continue
    return result


@login_required
def settings_view(request):
    wants_json = request.headers.get("x-requested-with") == "XMLHttpRequest"

    if request.method == "GET" and wants_json:
        action = request.GET.get("action", "").strip()
        if action == "privacy_state":
            return JsonResponse(
                {
                    "ok": True,
                    "rules": privacy_rule_payload(request.user),
                    "blocked": blocked_users_payload(request.user),
                    "sessions": active_sessions_payload(
                        request.user,
                        request.session.session_key or "",
                    ),
                    "delete_after_inactive_days": request.user.delete_after_inactive_days,
                    "delete_after_inactive_label": inactivity_label(
                        request.user.delete_after_inactive_days
                    ),
                    "default_auto_delete_seconds": request.user.default_auto_delete_seconds,
                    "default_auto_delete_label": auto_delete_label(
                        request.user.default_auto_delete_seconds
                    ),
                }
            )

    if request.method == "GET" and not wants_json:
        section = request.GET.get("section", "main")
        allowed = {
            "main",
            "privacy",
            "chat",
            "archive",
            "password",
            "blocked",
            "sessions",
            "privacy-rule",
            "privacy-exceptions",
            "inactive",
            "auto-delete",
        }
        if section not in allowed:
            section = "main"
        return redirect(f"{reverse('messenger:home')}?settings={section}")

    if request.method == "POST" and wants_json:
        action = request.POST.get("action", "").strip()

        if action == "privacy_rule":
            key = request.POST.get("key", "").strip()
            option = request.POST.get("option", "").strip()
            try:
                rule = set_privacy_rule(
                    request.user,
                    key,
                    option,
                    always=_parse_id_list(request.POST.get("always")),
                    never=_parse_id_list(request.POST.get("never")),
                )
            except ValueError as error:
                return JsonResponse({"ok": False, "error": str(error)}, status=400)
            return JsonResponse(
                {
                    "ok": True,
                    "key": key,
                    "rule": privacy_rule_payload(request.user)[key],
                }
            )

        if action in {"block", "unblock"}:
            username = request.POST.get("username", "").strip().lstrip("@")
            target = get_object_or_404(User, username__iexact=username, is_active=True)
            if target.pk == request.user.pk:
                return JsonResponse(
                    {"ok": False, "error": "Нельзя заблокировать самого себя."},
                    status=400,
                )
            if action == "block":
                UserBlock.objects.get_or_create(blocker=request.user, blocked=target)
            else:
                UserBlock.objects.filter(blocker=request.user, blocked=target).delete()
            return JsonResponse(
                {
                    "ok": True,
                    "blocked": blocked_users_payload(request.user),
                }
            )

        if action == "terminate_session":
            token = request.POST.get("token", "").strip()
            terminate_sessions(
                request.user,
                request.session.session_key or "",
                token=token or None,
            )
            return JsonResponse(
                {
                    "ok": True,
                    "sessions": active_sessions_payload(
                        request.user,
                        request.session.session_key or "",
                    ),
                }
            )

        if action == "terminate_other_sessions":
            terminate_sessions(
                request.user,
                request.session.session_key or "",
                others=True,
            )
            return JsonResponse(
                {
                    "ok": True,
                    "sessions": active_sessions_payload(
                        request.user,
                        request.session.session_key or "",
                    ),
                }
            )

        setting = request.POST.get("setting", "").strip()
        raw_value = request.POST.get("value", "")

        if setting == "theme":
            allowed_themes = {value for value, _label in User.Theme.choices}
            if raw_value not in allowed_themes:
                return JsonResponse(
                    {"ok": False, "error": "Неизвестная тема оформления."},
                    status=400,
                )
            value = raw_value
        elif setting in _BOOLEAN_SETTINGS:
            try:
                value = _parse_boolean_setting(raw_value)
            except ValueError as error:
                return JsonResponse(
                    {"ok": False, "error": str(error)},
                    status=400,
                )
        elif setting == "delete_after_inactive_days":
            try:
                value = int(raw_value)
            except (TypeError, ValueError):
                value = 0
            if value not in INACTIVITY_CHOICES:
                return JsonResponse(
                    {"ok": False, "error": "Неизвестный срок неактивности."},
                    status=400,
                )
        elif setting == "default_auto_delete_seconds":
            try:
                value = int(raw_value)
            except (TypeError, ValueError):
                value = -1
            if value not in AUTO_DELETE_CHOICES:
                return JsonResponse(
                    {"ok": False, "error": "Неизвестный срок автоудаления."},
                    status=400,
                )
        else:
            return JsonResponse(
                {"ok": False, "error": "Неизвестная настройка."},
                status=400,
            )

        setattr(request.user, setting, value)
        request.user.save(update_fields=[setting])
        return JsonResponse(
            {
                "ok": True,
                "setting": setting,
                "value": value,
                "label": (
                    inactivity_label(value)
                    if setting == "delete_after_inactive_days"
                    else auto_delete_label(value)
                    if setting == "default_auto_delete_seconds"
                    else ""
                ),
            }
        )

    form = UserSettingsForm(request.POST or None, instance=request.user)
    if request.method == "POST":
        if form.is_valid():
            form.save()
            messages.success(request, "Настройки сохранены.")
        else:
            for field_errors in form.errors.values():
                for error in field_errors:
                    messages.error(request, error)
        return redirect(f"{reverse('messenger:home')}?settings=main")
    return redirect(f"{reverse('messenger:home')}?settings=main")


@login_required
@require_POST
def remove_avatar(request):
    if request.user.avatar:
        request.user.avatar.delete(save=False)
        request.user.avatar = ""
        request.user.save(update_fields=["avatar"])

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse(
            {
                "ok": True,
                "avatar_url": "",
                "initials": request.user.initials,
            }
        )

    messages.success(request, "Фотография профиля удалена.")
    return redirect("accounts:profile")


def public_profile(request, username):
    from apps.messenger.models import Contact

    profile_user = get_object_or_404(User, username__iexact=username, is_active=True)
    viewer = request.user if request.user.is_authenticated else None
    is_self = bool(viewer and viewer.pk == profile_user.pk)
    is_contact = False
    if viewer and not is_self:
        is_contact = Contact.objects.filter(owner=viewer, user=profile_user).exists()

    if request.user.is_authenticated and request.headers.get("x-requested-with") != "XMLHttpRequest":
        return redirect(f"{reverse('messenger:home')}?profile={profile_user.username}")

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        last_seen_visible = privacy_allows(profile_user, viewer, "last_seen")
        if is_self or last_seen_visible:
            if profile_user.is_online:
                status = "в сети"
            elif profile_user.last_seen_at:
                seen = timezone.localtime(profile_user.last_seen_at)
                if seen.date() == timezone.localdate():
                    status = f"был(а) сегодня в {seen:%H:%M}"
                elif seen.date() == timezone.localdate() - timedelta(days=1):
                    status = f"был(а) вчера в {seen:%H:%M}"
                else:
                    status = f"был(а) {seen:%d.%m.%Y}"
            else:
                status = "был(а) давно"
        elif profile_user.last_seen_at and timezone.now() - profile_user.last_seen_at < timedelta(days=3):
            status = "был(а) недавно"
        else:
            status = "был(а) давно"

        photo_visible = is_self or privacy_allows(profile_user, viewer, "profile_photo")
        bio_visible = is_self or privacy_allows(profile_user, viewer, "bio")
        birthday_visible = is_self or privacy_allows(profile_user, viewer, "birthday")
        blocked = bool(viewer and not is_self and is_blocked_between(viewer, profile_user))
        messages_allowed = bool(
            viewer
            and not is_self
            and not blocked
            and privacy_allows(profile_user, viewer, "messages")
        )

        return JsonResponse(
            {
                "ok": True,
                "display_name": profile_user.display_name,
                "username": profile_user.username,
                "bio": profile_user.bio if bio_visible else "",
                "status": status,
                "avatar_url": (
                    profile_user.avatar.url
                    if profile_user.avatar and photo_visible
                    else ""
                ),
                "birthday": (
                    profile_user.birthday.isoformat()
                    if profile_user.birthday and birthday_visible
                    else ""
                ),
                "birthday_display": (
                    profile_user.birthday.strftime("%d.%m.%Y")
                    if profile_user.birthday and birthday_visible
                    else ""
                ),
                "personal_channel": _personal_channel_payload(
                    profile_user.personal_channel,
                    viewer,
                ),
                "initials": profile_user.initials,
                "is_contact": is_contact,
                "is_self": is_self,
                "is_blocked": blocked,
                "first_name": profile_user.first_name,
                "last_name": profile_user.last_name,
                "edit_url": reverse("accounts:profile") if is_self else "",
                "owned_channels": (
                    [
                        {
                            "id": membership.chat_id,
                            "title": membership.chat.title,
                            "username": membership.chat.username or "",
                            "avatar_url": membership.chat.avatar.url if membership.chat.avatar else "",
                        }
                        for membership in profile_user.chat_memberships.select_related("chat")
                        .filter(
                            role="owner",
                            chat__type="channel",
                            chat__username__isnull=False,
                        )
                        .exclude(chat__username="")
                        .order_by("chat__title", "chat_id")
                    ]
                    if is_self
                    else []
                ),
                "start_chat_url": (
                    reverse("messenger:start_chat", args=[profile_user.username])
                    if messages_allowed
                    else ""
                ),
                "add_contact_url": (
                    reverse("messenger:add_contact", args=[profile_user.username])
                    if viewer and not is_self
                    else ""
                ),
                "remove_contact_url": (
                    reverse("messenger:remove_contact", args=[profile_user.username])
                    if viewer and not is_self
                    else ""
                ),
                "profile_url": reverse(
                    "accounts:public_profile",
                    args=[profile_user.username],
                ),
                "remove_avatar_url": reverse("accounts:remove_avatar") if is_self else "",
            }
        )

    return render(
        request,
        "accounts/public_profile.html",
        {
            "profile_user": profile_user,
            "is_contact": is_contact,
            "profile_avatar_visible": privacy_allows(
                profile_user,
                viewer,
                "profile_photo",
            ),
            "profile_bio_visible": privacy_allows(
                profile_user,
                viewer,
                "bio",
            ),
            "profile_messages_allowed": privacy_allows(
                profile_user,
                viewer,
                "messages",
            ),
        },
    )

