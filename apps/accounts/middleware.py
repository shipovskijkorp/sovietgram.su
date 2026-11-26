from django.conf import settings
from django.contrib.auth import get_user_model, logout
from django.core.cache import cache
from django.shortcuts import redirect
from django.utils import timezone

from .lifecycle import delete_user_account
from .maintenance import purge_inactive_accounts
from .privacy import account_expired_for_inactivity


def _purge_inactive_accounts(now, exclude_user_id=None):
    if cache.add("sovietgram:privacy:inactive-purge", 1, timeout=3600):
        purge_inactive_accounts(now=now, exclude_user_id=exclude_user_id, limit=25)


def _purge_expired_messages():
    if not cache.add("sovietgram:privacy:message-expiry", 1, timeout=30):
        return
    from apps.messenger.services import purge_expired_messages

    purge_expired_messages(limit=100)


class UserActivityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Public PWA resources must not update presence, sessions, or run cleanup.
        if request.path_info in {"/healthz/", "/manifest.webmanifest", "/sw.js", "/offline/", "/app-icon/192.png", "/app-icon/512.png"}:
            return self.get_response(request)
        now = timezone.now()
        current_user_id = None

        if getattr(request, "user", None) is not None and request.user.is_authenticated:
            current_user_id = request.user.pk
            if account_expired_for_inactivity(request.user, now):
                expired = request.user
                logout(request)
                delete_user_account(expired, inactive_at=now)
                return redirect("accounts:login")

            previous = request.session.get("sovietgram_activity_touch", 0)
            # Background notification polling must not keep the user online.
            if request.path_info != "/notifications/poll/" and now.timestamp() - previous >= 45:
                get_user_model().objects.filter(pk=request.user.pk).update(last_seen_at=now)
                request.user.last_seen_at = now
                request.session["sovietgram_activity_touch"] = int(now.timestamp())

        # Preserve the old installation's cleanup until its independent
        # maintenance service has actually been enabled.
        if not settings.SOVIETGRAM_BACKGROUND_MAINTENANCE:
            _purge_inactive_accounts(now, exclude_user_id=current_user_id)
            _purge_expired_messages()
        return self.get_response(request)
