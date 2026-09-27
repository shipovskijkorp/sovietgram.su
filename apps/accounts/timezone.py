from urllib.parse import unquote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone


TIMEZONE_COOKIE = "sovietgram_timezone"


class ClientTimezoneMiddleware:
    """Activate the browser's IANA timezone for the duration of a request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        raw = unquote(
            (request.COOKIES.get(TIMEZONE_COOKIE, "") or "").strip()[:120]
        )
        try:
            client_timezone = ZoneInfo(raw) if raw else None
        except (ZoneInfoNotFoundError, ValueError):
            client_timezone = None

        if client_timezone is not None:
            timezone.activate(client_timezone)
        else:
            timezone.deactivate()

        try:
            return self.get_response(request)
        finally:
            timezone.deactivate()
