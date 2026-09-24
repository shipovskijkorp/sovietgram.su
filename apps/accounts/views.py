from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import (
    IdentifierAuthenticationForm,
    OverlayProfileForm,
    ProfileForm,
    RegisterForm,
    UserSettingsForm,
)
from .models import User
from .multiaccount import (
    activate_account,
    add_authenticated_account,
    remember_current_account,
    remove_current_account,
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
    if channel is None:
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


class StalingramLoginView(LoginView):
    authentication_form = IdentifierAuthenticationForm
    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        remember_current_account(self.request)
        return response


class StalingramLogoutView:
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


class StalingramPasswordChangeView(LoginRequiredMixin, PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:profile")

    def form_valid(self, form):
        messages.success(self.request, "Пароль изменён.")
        return super().form_valid(form)


def register(request):
    if request.user.is_authenticated:
        return redirect("messenger:home")

    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user, backend="apps.accounts.backends.EmailOrUsernameBackend")
        messages.success(request, "Учётная запись создана.")
        return redirect("messenger:home")

    return render(request, "accounts/register.html", {"form": form})


@login_required
def add_account(request):
    form = IdentifierAuthenticationForm(request=request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        backend = "apps.accounts.backends.EmailOrUsernameBackend"
        add_authenticated_account(request, user, backend)
        messages.success(request, f"Аккаунт @{user.username} добавлен.")
        return redirect("messenger:home")
    return render(request, "accounts/add_account.html", {"form": form})


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


@login_required
def settings_view(request):
    form = UserSettingsForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Настройки сохранены.")
        return redirect("accounts:settings")
    return render(request, "accounts/settings.html", {"form": form})


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
    is_contact = False
    if request.user.is_authenticated and request.user.pk != profile_user.pk:
        is_contact = Contact.objects.filter(owner=request.user, user=profile_user).exists()

    if request.user.is_authenticated and request.headers.get("x-requested-with") != "XMLHttpRequest":
        return redirect(f"{reverse('messenger:home')}?profile={profile_user.username}")

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
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

        return JsonResponse(
            {
                "ok": True,
                "display_name": profile_user.display_name,
                "username": profile_user.username,
                "bio": profile_user.bio,
                "status": status,
                "avatar_url": profile_user.avatar.url if profile_user.avatar else "",
                "birthday": profile_user.birthday.isoformat() if profile_user.birthday else "",
                "birthday_display": (
                    profile_user.birthday.strftime("%d.%m.%Y")
                    if profile_user.birthday
                    else ""
                ),
                "personal_channel": _personal_channel_payload(
                    profile_user.personal_channel,
                    request.user if request.user.is_authenticated else None,
                ),
                "initials": profile_user.initials,
                "is_contact": is_contact,
                "is_self": bool(
                    request.user.is_authenticated
                    and request.user.pk == profile_user.pk
                ),
                "first_name": profile_user.first_name,
                "last_name": profile_user.last_name,
                "edit_url": (
                    reverse("accounts:profile")
                    if request.user.is_authenticated
                    and request.user.pk == profile_user.pk
                    else ""
                ),
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
                        )
                        .order_by("chat__title", "chat_id")
                    ]
                    if request.user.is_authenticated
                    and request.user.pk == profile_user.pk
                    else []
                ),
                "start_chat_url": (
                    reverse("messenger:start_chat", args=[profile_user.username])
                    if request.user.is_authenticated
                    and request.user.pk != profile_user.pk
                    else ""
                ),
                "add_contact_url": (
                    reverse("messenger:add_contact", args=[profile_user.username])
                    if request.user.is_authenticated
                    and request.user.pk != profile_user.pk
                    else ""
                ),
                "remove_contact_url": (
                    reverse("messenger:remove_contact", args=[profile_user.username])
                    if request.user.is_authenticated
                    and request.user.pk != profile_user.pk
                    else ""
                ),
                "profile_url": reverse(
                    "accounts:public_profile",
                    args=[profile_user.username],
                ),
                "remove_avatar_url": (
                    reverse("accounts:remove_avatar")
                    if request.user.is_authenticated
                    and request.user.pk == profile_user.pk
                    else ""
                ),
            }
        )

    return render(
        request,
        "accounts/public_profile.html",
        {
            "profile_user": profile_user,
            "is_contact": is_contact,
        },
    )
