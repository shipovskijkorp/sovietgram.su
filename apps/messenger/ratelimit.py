from functools import wraps

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse


DEFAULT_RATE_LIMITS = {
    "send_message": {"limit": 30, "window": 60},
    "search_messages": {"limit": 60, "window": 60},
    "global_search": {"limit": 90, "window": 60},
    "typing": {"limit": 120, "window": 60},
}


def _limit_config(scope):
    configured = getattr(settings, "SOVIETGRAM_RATE_LIMITS", {})
    values = DEFAULT_RATE_LIMITS[scope].copy()
    values.update(configured.get(scope, {}))
    return max(1, int(values["limit"])), max(1, int(values["window"]))


def rate_limit(scope):
    if scope not in DEFAULT_RATE_LIMITS:
        raise ValueError(f"Unknown rate-limit scope: {scope}")

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            limit, window = _limit_config(scope)
            identity = getattr(request.user, "pk", None) or request.META.get(
                "REMOTE_ADDR", "anonymous"
            )
            key = f"sovietgram:rate:{scope}:{identity}"

            if cache.add(key, 1, timeout=window):
                count = 1
            else:
                try:
                    count = cache.incr(key)
                except ValueError:
                    cache.set(key, 1, timeout=window)
                    count = 1

            if count > limit:
                response = JsonResponse(
                    {
                        "ok": False,
                        "error": "Слишком много запросов. Попробуйте немного позже.",
                        "rate_limited": True,
                    },
                    status=429,
                )
                response["Retry-After"] = str(window)
                return response

            return view(request, *args, **kwargs)

        return wrapped

    return decorator
