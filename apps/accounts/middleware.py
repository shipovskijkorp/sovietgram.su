from django.contrib.auth import get_user_model
from django.utils import timezone


class UserActivityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(request, "user", None) is not None and request.user.is_authenticated:
            now = timezone.now()
            previous = request.session.get("sovietgram_activity_touch", 0)
            if now.timestamp() - previous >= 45:
                get_user_model().objects.filter(pk=request.user.pk).update(last_seen_at=now)
                request.user.last_seen_at = now
                request.session["sovietgram_activity_touch"] = int(now.timestamp())
        return self.get_response(request)
