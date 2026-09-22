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
        messages.success(request, "Фотография профиля удалена.")
    return redirect("accounts:profile")


def public_profile(request, username):
    from apps.messenger.models import Contact

    profile_user = get_object_or_404(User, username__iexact=username, is_active=True)
    is_contact = False
    if request.user.is_authenticated and request.user.pk != profile_user.pk:
        is_contact = Contact.objects.filter(owner=request.user, user=profile_user).exists()

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        if profile_user.is_online:
            status = "в сети"
        elif profile_user.last_seen_at:
            seen = timezone.localtime(profile_user.last_seen_at)
            if seen.date() == timezone.localdate():
                status = f"был(а) сегодня в {seen:%H:%M}"
            elif seen.date() == timezone.localdate() - timezone.timedelta(days=1):
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
                "initials": profile_user.initials,
                "is_contact": is_contact,
                "is_self": bool(
                    request.user.is_authenticated
                    and request.user.pk == profile_user.pk
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
