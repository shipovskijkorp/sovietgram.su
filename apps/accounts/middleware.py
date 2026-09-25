from datetime import timedelta

from django.contrib.auth import get_user_model, logout
from django.core.cache import cache
from django.shortcuts import redirect
from django.utils import timezone


def _purge_inactive_accounts(now, exclude_user_id=None):
    if not cache.add("sovietgram:privacy:inactive-purge", 1, timeout=3600):
        return
    User = get_user_model()
    candidates = User.objects.filter(is_active=True).only(
        "id",
        "last_seen_at",
        "date_joined",
        "delete_after_inactive_days",
    )
    if exclude_user_id:
        candidates = candidates.exclude(pk=exclude_user_id)

    for user in candidates.iterator():
        base = user.last_seen_at or user.date_joined
        days = int(user.delete_after_inactive_days or 365)
        if base and base <= now - timedelta(days=days):
            user.delete()


def _purge_expired_messages():
    if not cache.add("sovietgram:privacy:message-expiry", 1, timeout=30):
        return
    from apps.messenger.services import purge_expired_messages

    # Bound work per request; the next request continues if a large backlog exists.
    purge_expired_messages(limit=100)


class UserActivityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        now = timezone.now()
        current_user_id = None

        if getattr(request, "user", None) is not None and request.user.is_authenticated:
            current_user_id = request.user.pk
            base = request.user.last_seen_at or request.user.date_joined
            days = int(request.user.delete_after_inactive_days or 365)
            if base and base <= now - timedelta(days=days):
                expired = request.user
                logout(request)
                expired.delete()
                return redirect("accounts:login")

            previous = request.session.get("sovietgram_activity_touch", 0)
            if now.timestamp() - previous >= 45:
                get_user_model().objects.filter(pk=request.user.pk).update(last_seen_at=now)
                request.user.last_seen_at = now
                request.session["sovietgram_activity_touch"] = int(now.timestamp())

        _purge_inactive_accounts(now, exclude_user_id=current_user_id)
        _purge_expired_messages()
        return self.get_response(request)
