"""Enrollment and recovery management; never expose stored TOTP secrets."""
import base64
from io import BytesIO

import pyotp
import qrcode
from cryptography.fernet import InvalidToken
from django.contrib.auth import HASH_SESSION_KEY, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from .account_security import _limited
from .models import User
from .multiaccount import remember_current_account
from .two_factor import decrypt_secret, encrypt_secret, matching_step, new_recovery_codes, verify_factor_locked

PENDING = "sovietgram_totp_pending_v1"


def pending_secret(request, user):
    pending = request.session.get(PENDING)
    if not isinstance(pending, dict):
        return None
    try:
        if (
            pending["user"] != user.pk
            or not constant_time_compare(pending["hash"], user.get_session_auth_hash())
            or not 0 <= timezone.now().timestamp() - pending["created"] <= 600
            or user.two_factor_enabled
        ):
            raise ValueError
        return decrypt_secret(pending["secret"])
    except (KeyError, InvalidToken, TypeError, ValueError):
        request.session.pop(PENDING, None)
        return None


def render_security(request, *, error="", codes=None, status=200):
    user = request.user
    secret = None if codes else pending_secret(request, user)
    qr = ""
    if secret:
        uri = pyotp.TOTP(secret).provisioning_uri(name=user.username, issuer_name="Sovietgram")
        image = qrcode.make(uri)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        qr = base64.b64encode(buffer.getvalue()).decode("ascii")
    response = render(request, "accounts/two_factor.html", {
        "error": error, "enabled": user.two_factor_enabled,
        "secret": secret, "qr": qr, "codes": codes,
        "recovery_remaining": len(user.two_factor_recovery_hashes or []),
    }, status=status)
    response["Referrer-Policy"] = "same-origin"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


@login_required
@never_cache
@sensitive_post_parameters("password", "otp")
@ensure_csrf_cookie
@require_http_methods(["GET", "POST"])
def two_factor_settings(request):
    if request.method == "GET":
        return render_security(request)
    if request.POST.get("account_id") != str(request.user.pk):
        return render_security(request, error="Аккаунт изменился. Откройте настройки заново.", status=409)
    action = request.POST.get("action")
    if action == "cancel":
        request.session.pop(PENDING, None)
        return redirect("accounts:two_factor")

    error = ""
    codes = None
    rotate = False
    started = False
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=request.user.pk)
        if not constant_time_compare(
            str(request.session.get(HASH_SESSION_KEY, "")), user.get_session_auth_hash()
        ):
            return redirect("accounts:login")
        request.user = user
        if action == "start":
            if user.two_factor_enabled:
                error = "Двухфакторная защита уже включена."
            elif _limited("totp-start", user.pk, 5, 300):
                error = "Слишком много попыток. Повторите через пять минут."
            elif not user.check_password(request.POST.get("password", "")):
                error = "Неверный пароль."
            else:
                request.session[PENDING] = {
                    "user": user.pk, "hash": user.get_session_auth_hash(),
                    "created": timezone.now().timestamp(), "attempts": 0,
                    "secret": encrypt_secret(pyotp.random_base32()),
                }
                started = True
        elif action == "enable":
            secret = pending_secret(request, user)
            if not secret:
                error = "Настройка истекла. Начните заново."
            else:
                step = matching_step(secret, request.POST.get("otp"))
                if step is None:
                    pending = dict(request.session[PENDING])
                    pending["attempts"] += 1
                    if pending["attempts"] >= 5:
                        request.session.pop(PENDING, None)
                        error = "Слишком много попыток. Начните настройку заново."
                    else:
                        request.session[PENDING] = pending
                        error = "Неверный код приложения."
                else:
                    codes, hashes = new_recovery_codes()
                    user.two_factor_secret = encrypt_secret(secret)
                    user.two_factor_recovery_hashes = hashes
                    user.two_factor_last_step = step
                    user.two_factor_failures = 0
                    user.two_factor_failure_window = None
                    user.security_version += 1
                    user.save(update_fields=[
                        "two_factor_secret", "two_factor_recovery_hashes", "two_factor_last_step",
                        "two_factor_failures", "two_factor_failure_window", "security_version",
                    ])
                    rotate = True
        elif action in {"disable", "regenerate"}:
            if not user.two_factor_enabled:
                error = "Двухфакторная защита не включена."
            elif _limited("totp-manage", user.pk, 10, 300):
                error = "Слишком много попыток. Повторите позже."
            elif not user.check_password(request.POST.get("password", "")):
                error = "Неверный пароль."
            elif not verify_factor_locked(user, request.POST.get("otp")):
                error = "Неверный или уже использованный код. После пяти ошибок подождите пять минут."
            else:
                if action == "disable":
                    user.two_factor_secret = ""
                    user.two_factor_recovery_hashes = []
                    user.two_factor_last_step = -1
                else:
                    codes, user.two_factor_recovery_hashes = new_recovery_codes()
                user.security_version += 1
                user.save(update_fields=[
                    "two_factor_secret", "two_factor_recovery_hashes", "two_factor_last_step", "security_version",
                ])
                rotate = True
        else:
            error = "Неизвестное действие."

    if rotate:
        update_session_auth_hash(request, user)
        request.user = user
        remember_current_account(request)
        request.session.pop(PENDING, None)
    if started or (rotate and codes is None):
        return redirect("accounts:two_factor")
    return render_security(request, error=error, codes=codes, status=400 if error else 200)
