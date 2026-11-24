"""Credential recovery and email ownership changes.

Bearer tokens are random, stored only as digests, purpose-bound and consumed
in the same transaction as the credential update. The database enforces the
per-account resend cooldown across Gunicorn workers.
"""
import hashlib
import logging
import re
import secrets
from datetime import timedelta
from ipaddress import ip_address

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods

from .models import AccountSecurityRequest, User
from .lifecycle import delete_user_account
from .multiaccount import remove_current_account
from .privacy import account_expired_for_inactivity

logger = logging.getLogger(__name__)
RESET = AccountSecurityRequest.Purpose.PASSWORD_RESET
CHANGE = AccountSecurityRequest.Purpose.EMAIL_CHANGE
COOLDOWN = timedelta(seconds=120)
LIFETIME = {RESET: timedelta(hours=1), CHANGE: timedelta(hours=24)}
TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{43}\Z")


class RecoveryForm(forms.Form):
    email = forms.EmailField(
        label="Электронная почта", max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}),
    )


class EmailChangeForm(RecoveryForm):
    email = forms.EmailField(
        label="Новая или текущая неподтверждённая почта", max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}),
    )
    password = forms.CharField(
        label="Текущий пароль", strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )


def _digest(token):
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _state(user):
    # Changing either credential or verification status invalidates old links.
    return salted_hmac(
        "sovietgram.account-security.state.v1",
        f"{user.pk}|{user.password}|{user.email}|{user.email_verified_at}",
        algorithm="sha256",
    ).hexdigest()


def _eligible(user):
    return bool(
        user and user.is_active and user.has_usable_password()
        and not account_expired_for_inactivity(user)
    )


def _email_available(user, email):
    return not User.objects.exclude(pk=user.pk).filter(
        Q(email__iexact=email) | Q(username__iexact=email)
    ).exists()


def _limited(scope, key, limit, window=300):
    # Supplemental abuse control; the database cooldown remains authoritative
    # for sends even when using Django's per-process default cache.
    cache_key = "sovietgram:account-security:" + scope + ":" + hashlib.sha256(
        str(key).encode()
    ).hexdigest()
    if cache.add(cache_key, 1, timeout=window):
        return False
    try:
        return cache.incr(cache_key) > limit
    except ValueError:
        return not cache.add(cache_key, 1, timeout=window)


def _client_key(request):
    raw = request.META.get("REMOTE_ADDR", "")
    try:
        address = ip_address(raw)
        # The bundled Nginx config overwrites X-Real-IP; Gunicorn is bound
        # to loopback. Do not trust forwarded addresses from direct clients.
        if address.is_loopback:
            forwarded = request.META.get("HTTP_X_REAL_IP")
            if forwarded:
                return str(ip_address(forwarded))
        return str(address)
    except ValueError:
        return raw


def _reserve(user, purpose, email):
    """Caller holds a row lock on user; all writers use the same lock order."""
    now = timezone.now()
    previous = AccountSecurityRequest.objects.filter(user=user, purpose=purpose).first()
    if previous and now - previous.issued_at < COOLDOWN:
        return None
    token = secrets.token_urlsafe(32)
    digest = _digest(token)
    AccountSecurityRequest.objects.update_or_create(
        user=user, purpose=purpose,
        defaults={
            "token_digest": digest, "email": email, "account_state": _state(user),
            "issued_at": now, "expires_at": now + LIFETIME[purpose],
        },
    )
    return token


def _send(request, user, purpose, email, token):
    route = "accounts:password_reset_confirm" if purpose == RESET else "accounts:email_change_confirm"
    path = reverse(route, args=[token])
    origin = settings.SOVIETGRAM_PUBLIC_URL.rstrip("/")
    link = f"{origin}{path}" if origin else request.build_absolute_uri(path)
    subject, action, lifetime = (
        ("Восстановление пароля", "установить новый пароль", "1 час")
        if purpose == RESET else
        ("Подтверждение адреса почты", "подтвердить адрес", "24 часа")
    )
    try:
        count = send_mail(
            f"Sovietgram — {subject}",
            f"Для аккаунта @{user.username}: чтобы {action}, откройте ссылку:\n\n"
            f"{link}\n\nСсылка действует {lifetime} и используется один раз.\n"
            "Если вы не запрашивали это действие, проигнорируйте письмо.",
            settings.DEFAULT_FROM_EMAIL, [email], fail_silently=False,
        )
        if count != 1:
            raise RuntimeError("SMTP backend did not accept the message")
        return True
    except Exception:
        # Do not log bearer tokens, passwords or recipient addresses.
        logger.warning("Failed to send account security mail (purpose=%s)", purpose)
        AccountSecurityRequest.objects.filter(
            user=user, purpose=purpose, token_digest=_digest(token),
        ).update(token_digest=None)
        return False


def _candidate(token, purpose, lock=False):
    if not TOKEN_RE.fullmatch(token):
        return None, None
    digest = _digest(token)
    match = AccountSecurityRequest.objects.filter(
        token_digest=digest, purpose=purpose,
    ).values_list("user_id", flat=True).first()
    if match is None:
        return None, None
    users = User.objects.select_for_update() if lock else User.objects
    user = users.filter(pk=match).first()
    if not _eligible(user):
        return None, None
    requests = AccountSecurityRequest.objects.select_for_update() if lock else AccountSecurityRequest.objects
    pending = requests.filter(user=user, purpose=purpose, token_digest=digest).first()
    if not pending or pending.expires_at <= timezone.now():
        return None, None
    if not constant_time_compare(pending.account_state, _state(user)):
        return None, None
    if purpose == RESET and (not user.email_verified_at or pending.email != user.email):
        return None, None
    return user, pending


def _consume(pending):
    pending.token_digest = None
    pending.save(update_fields=["token_digest"])


def _page(request, *, title, heading, description, form=None, submit="", back=None,
          back_label="Вернуться", status=200):
    if back is None:
        back = reverse("messenger:home") if request.user.is_authenticated else reverse("accounts:login")
    response = render(request, "accounts/account_security.html", {
        "title": title, "heading": heading, "description": description,
        "form": form, "submit": submit, "back_url": back, "back_label": back_label,
    }, status=status)
    # Preserve HTTPS CSRF fallback without leaking token URLs off-site.
    response["Referrer-Policy"] = "same-origin"
    return response


@never_cache
@ensure_csrf_cookie
@require_http_methods(["GET", "POST"])
def password_reset_request(request):
    form = RecoveryForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        if not _limited("reset-ip", _client_key(request), 20):
            email = form.cleaned_data["email"].strip()
            token = None
            with transaction.atomic():
                user = User.objects.select_for_update().filter(
                    email__iexact=email, is_active=True, email_verified_at__isnull=False,
                ).first()
                if _eligible(user):
                    token = _reserve(user, RESET, user.email)
            if token:
                _send(request, user, RESET, user.email, token)
        # Identical redirect and response for unknown, inactive, unverified,
        # throttled, and SMTP-failed accounts.
        return redirect("accounts:password_reset_sent")
    return _page(request, title="Восстановление пароля", heading="Забыли пароль?",
                 description="Укажите подтверждённую почту аккаунта.",
                 form=form, submit="Отправить ссылку")


@never_cache
@require_GET
def password_reset_sent(request):
    return _page(request, title="Восстановление пароля", heading="Проверьте почту",
                 description="Если адрес подтверждён и связан с активным аккаунтом, "
                 "мы отправили ссылку для восстановления. Проверьте папку «Спам». "
                 "Повторный запрос возможен через две минуты.",
                 back=reverse("accounts:password_reset"), back_label="Запросить снова")


@never_cache
@ensure_csrf_cookie
@require_http_methods(["GET", "POST"])
def password_reset_confirm(request, token):
    with transaction.atomic():
        user, pending = _candidate(token, RESET, lock=request.method == "POST")
        if pending:
            form = SetPasswordForm(user, request.POST if request.method == "POST" else None)
            if request.method == "POST" and form.is_valid():
                user = form.save(commit=False)
                user.save(update_fields=["password"])
                _consume(pending)
                # Password-derived session hashes invalidate existing Django
                # sessions and stored multi-account slots. Do not auto-login.
                messages.success(request, "Пароль изменён. Войдите с новым паролем.")
                if request.user.is_authenticated and request.user.pk != user.pk:
                    return redirect("accounts:add_account")
                return redirect("accounts:login")
            return _page(request, title="Новый пароль", heading="Установите новый пароль",
                         description="После смены пароля прежние сеансы аккаунта завершатся.",
                         form=form, submit="Сохранить пароль",
                         back=reverse("accounts:password_reset"), back_label="Запросить новую ссылку")
    return _invalid(request, RESET)


@login_required
@never_cache
@ensure_csrf_cookie
@require_http_methods(["GET", "POST"])
def email_change_request(request):
    form = EmailChangeForm(
        request.POST if request.method == "POST" else None,
        initial={"email": request.user.email if not request.user.email_verified_at else ""},
    )
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].strip().lower()
        token = None
        if _limited("change-user", request.user.pk, 10):
            form.add_error(None, "Слишком много попыток. Повторите позже.")
        else:
            with transaction.atomic():
                user = User.objects.select_for_update().get(pk=request.user.pk)
                if not _eligible(user) or not user.check_password(form.cleaned_data["password"]):
                    form.add_error("password", "Неверный пароль.")
                elif user.email_verified_at and email == user.email.casefold():
                    form.add_error("email", "Этот адрес уже подтверждён.")
                elif not _email_available(user, email):
                    form.add_error("email", "Этот адрес недоступен.")
                else:
                    token = _reserve(user, CHANGE, email)
                    if not token:
                        form.add_error(None, "Подождите две минуты перед повторной отправкой.")
            if token:
                if _send(request, user, CHANGE, email, token):
                    messages.success(request, "Ссылка отправлена. Текущий адрес сохранится до подтверждения.")
                    return redirect("accounts:email_change")
                form.add_error(None, "Не удалось отправить письмо. Повторите через две минуты.")
    return _page(request, title="Электронная почта", heading="Подтвердить или изменить почту",
                 description=f"Текущий адрес: {request.user.email}. "
                 "Введите пароль. Новый адрес начнёт действовать только после подтверждения.",
                 form=form, submit="Отправить ссылку",
                 back=f"{reverse('messenger:home')}?settings=privacy", back_label="Назад к настройкам")


@never_cache
@ensure_csrf_cookie
@require_http_methods(["GET", "POST"])
def email_change_confirm(request, token):
    old_email = None
    try:
        with transaction.atomic():
            user, pending = _candidate(token, CHANGE, lock=request.method == "POST")
            if not pending or not _email_available(user, pending.email):
                return _invalid(request, CHANGE)
            if request.method == "GET":
                # Email scanners must not consume the link or change credentials.
                return _page(request, title="Подтверждение почты", heading="Подтвердить адрес?",
                             description=f"Подтвердите адрес {pending.email} для @{user.username}.",
                             form=forms.Form(), submit="Подтвердить почту")
            if user.email_verified_at and user.email.casefold() != pending.email.casefold():
                old_email = user.email
            user.email = pending.email
            user.email_verified_at = timezone.now()
            user.email_verification_sent_at = None
            user.save(update_fields=["email", "email_verified_at", "email_verification_sent_at"])
            _consume(pending)
    except IntegrityError:
        # Another account may have claimed the address since issuance.
        return _invalid(request, CHANGE)
    if old_email:
        try:
            send_mail(
                "Sovietgram — адрес почты изменён",
                f"Адрес почты аккаунта @{user.username} был изменён. "
                "Если это сделали не вы, обратитесь к администрации.",
                settings.DEFAULT_FROM_EMAIL, [old_email], fail_silently=False,
            )
        except Exception:
            logger.warning("Failed to send email-change security alert")
    messages.success(request, "Почта подтверждена.")
    if request.user.is_authenticated and request.user.pk == user.pk:
        return redirect(f"{reverse('messenger:home')}?settings=privacy")
    if request.user.is_authenticated:
        return redirect("accounts:add_account")
    return redirect("accounts:login")


def _invalid(request, purpose):
    back = reverse("accounts:password_reset" if purpose == RESET else "accounts:email_change")
    return _page(request, title="Недействительная ссылка", heading="Ссылка недействительна",
                 description="Ссылка уже использована, устарела или настройки аккаунта изменились. "
                 "Запросите новую ссылку.", back=back, back_label="Запросить новую ссылку",
                 status=400 if request.method == "POST" else 200)


class DeleteAccountForm(forms.Form):
    account_id = forms.IntegerField(widget=forms.HiddenInput())
    username = forms.CharField(
        label="Введите имя пользователя для подтверждения", max_length=150,
        widget=forms.TextInput(attrs={"autocomplete": "off", "spellcheck": "false"}),
    )
    password = forms.CharField(
        label="Текущий пароль", strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )
    confirm = forms.BooleanField(
        label="Я понимаю, что удаление необратимо.", required=True,
    )


@login_required
@never_cache
@ensure_csrf_cookie
@require_http_methods(["GET", "POST"])
def delete_account(request):
    """Explicit, password-confirmed use of the existing account lifecycle."""
    form = DeleteAccountForm(
        request.POST if request.method == "POST" else None,
        initial={"account_id": request.user.pk},
    )
    if request.method == "POST" and form.is_valid():
        if form.cleaned_data["account_id"] != request.user.pk:
            form.add_error(None, "Аккаунт изменился. Откройте настройки заново.")
        elif _limited("delete-account", request.user.pk, 5):
            form.add_error(None, "Слишком много попыток. Повторите через пять минут.")
        else:
            deleted = False
            with transaction.atomic():
                user = User.objects.select_for_update().filter(pk=request.user.pk).first()
                if not user or not user.is_active:
                    form.add_error(None, "Аккаунт недоступен.")
                elif form.cleaned_data["username"] != user.username:
                    form.add_error("username", "Имя пользователя не совпадает.")
                elif not user.check_password(form.cleaned_data["password"]):
                    form.add_error("password", "Неверный пароль.")
                else:
                    delete_user_account(user)
                    deleted = True
            if deleted:
                # Keep other valid accounts in this browser, but remove the
                # deleted account's slot. Other sessions cannot authenticate.
                switched = remove_current_account(request)
                if switched is not None:
                    messages.success(request, "Аккаунт удалён. Выполнено переключение на другой аккаунт.")
                    return redirect("messenger:home")
                logout(request)
                messages.success(request, "Аккаунт удалён.")
                return redirect("accounts:login")
    return _page(
        request, title="Удаление аккаунта", heading="Удалить аккаунт навсегда?",
        description=(
            f"@{request.user.username}: профиль, избранное, личные переписки "
            "и их вложения будут удалены у обоих собеседников. Ваши сообщения "
            "в группах и каналах будут удалены. Если в вашем сообществе есть "
            "другие участники, права владельца будут переданы им; пустые "
            "сообщества будут удалены. Восстановить данные нельзя."
        ),
        form=form, submit="Удалить аккаунт навсегда",
        back=f"{reverse('messenger:home')}?settings=privacy",
        back_label="Отмена — вернуться к настройкам",
    )
