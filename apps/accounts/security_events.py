"""Private account security history and rate-limited sign-in email alerts."""
import logging
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.db import transaction
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .models import SecurityEvent, User

logger = logging.getLogger(__name__)
HISTORY_LIMIT = 100
ALERT_COOLDOWN = timedelta(minutes=15)


def _send_login_alert(user_id, email, occurred_at):
    user = User.objects.filter(pk=user_id, email=email, email_verified_at__isnull=False,
        is_active=True, platform_suspended_at__isnull=True).first()
    if not user:
        return
    try:
        send_mail(
            "Sovietgram — новый вход в аккаунт",
            f"Выполнен вход в аккаунт @{user.username}.\n"
            f"Время (UTC): {occurred_at:%d.%m.%Y %H:%M:%S}.\n\n"
            "Если это были не вы, самостоятельно откройте Sovietgram, "
            "проверьте активные сеансы, завершите незнакомые и измените пароль. "
            "Рекомендуем включить двухфакторную защиту.\n",
            settings.DEFAULT_FROM_EMAIL, [email], fail_silently=False,
        )
    except Exception:
        logger.warning("Failed to send Sovietgram sign-in security alert")


def record_event(request, user, kind):
    if kind not in SecurityEvent.Kind.values:
        raise ValueError("Unknown security event")
    with transaction.atomic():
        locked = User.objects.select_for_update().filter(pk=user.pk).first()
        if locked is None:
            return
        now = timezone.now()
        notify = (
            kind == SecurityEvent.Kind.LOGIN and bool(locked.email_verified_at)
            and (not locked.last_login_alert_at or now - locked.last_login_alert_at >= ALERT_COOLDOWN)
        )
        event = SecurityEvent.objects.create(
            user=locked, kind=kind,
            device=(request.META.get("HTTP_USER_AGENT") or "")[:240],
        )
        obsolete = list(SecurityEvent.objects.filter(user=locked)
                        .values_list("pk", flat=True)[HISTORY_LIMIT:])
        if obsolete:
            SecurityEvent.objects.filter(user=locked, pk__in=obsolete).delete()
        if notify:
            locked.last_login_alert_at = now
            locked.save(update_fields=["last_login_alert_at"])
            transaction.on_commit(
                lambda: _send_login_alert(locked.pk, locked.email, event.created_at),
                robust=True,
            )


@login_required
@never_cache
@require_GET
def security_history(request):
    events = SecurityEvent.objects.filter(user=request.user)[:HISTORY_LIMIT]
    return render(request, "accounts/security_history.html", {"events": events})
