"""One-use, expiring email verification links for newly registered accounts.

No SMTP credentials or raw verification secrets are stored in this module.
Django's signed payload is bound to the recipient and to the latest send time.
"""

from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.core.mail import send_mail
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models import User


VERIFICATION_SALT = "sovietgram.email-verification.v1"
VERIFICATION_LIFETIME_SECONDS = 24 * 60 * 60
RESEND_COOLDOWN_SECONDS = 120


def verification_token(user):
    if not user.email_verification_sent_at:
        raise ValueError("Email verification was not issued for this account.")
    return signing.dumps(
        {
            "user_id": user.pk,
            "email": user.email.casefold(),
            "sent_at": user.email_verification_sent_at.isoformat(),
        },
        salt=VERIFICATION_SALT,
        compress=False,
    )


def get_pending_verification(token):
    try:
        payload = signing.loads(
            token, salt=VERIFICATION_SALT,
            max_age=VERIFICATION_LIFETIME_SECONDS,
        )
        if not isinstance(payload, dict):
            return None
        user_id = payload.get("user_id")
        if not isinstance(user_id, int) or isinstance(user_id, bool):
            return None
        user = User.objects.filter(
            pk=user_id, is_active=False, email_verified_at__isnull=True,
        ).first()
        if (
            user is None
            or not user.email_verification_sent_at
            or user.email.casefold() != payload.get("email")
            or user.email_verification_sent_at.isoformat() != payload.get("sent_at")
        ):
            return None
        return user
    except (signing.BadSignature, ValueError, TypeError):
        return None


def send_verification_email(request, user):
    verification_path = reverse(
        "accounts:verify_email", kwargs={"token": verification_token(user)},
    )
    public_url = getattr(settings, "SOVIETGRAM_PUBLIC_URL", "").rstrip("/")
    link = (
        f"{public_url}{verification_path}"
        if public_url
        else request.build_absolute_uri(verification_path)
    )
    count = send_mail(
        "Sovietgram — подтверждение почты",
        (
            f"Здравствуйте!\n\n"
            f"Для подтверждения адреса почты аккаунта @{user.username} "
            f"откройте ссылку:\n\n{link}\n\n"
            "Ссылка действует 24 часа и становится недействительной после "
            "подтверждения или повторной отправки письма.\n\n"
            "Если вы не регистрировались в Sovietgram, проигнорируйте это письмо.\n"
        ),
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False,
    )
    if count != 1:
        raise RuntimeError("SMTP backend did not accept the verification message.")


def confirm_verification(token):
    """Atomically consume a token. Concurrent double submissions cannot re-activate."""
    user = get_pending_verification(token)
    if user is None:
        return False
    return bool(
        User.objects.filter(
            pk=user.pk,
            email=user.email,
            is_active=False,
            email_verified_at__isnull=True,
            email_verification_sent_at=user.email_verification_sent_at,
        ).update(
            is_active=True,
            email_verified_at=timezone.now(),
            email_verification_sent_at=None,
        )
    )


def reserve_resend(email):
    """Reserve one mail per pending account per cooldown, even across workers."""
    if not isinstance(email, str) or not email or len(email) > 254:
        return None
    with transaction.atomic():
        user = User.objects.select_for_update().filter(
            email__iexact=email,
            is_active=False,
            email_verified_at__isnull=True,
        ).first()
        if user is None:
            return None
        now = timezone.now()
        if (
            user.email_verification_sent_at
            and now - user.email_verification_sent_at
            < timedelta(seconds=RESEND_COOLDOWN_SECONDS)
        ):
            return None
        user.email_verification_sent_at = now
        user.save(update_fields=["email_verification_sent_at"])
        return user
