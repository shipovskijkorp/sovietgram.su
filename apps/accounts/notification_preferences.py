"""Account-wide notification preferences; browser permission is device-local."""
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .models import User

KEYS = ("sound", "message", "mention", "reply", "badge")
TONES = ("classic", "soft", "chime", "short")
PREVIEWS = ("hidden", "sender", "text")
CHOICES = {
    "tone_message": TONES, "tone_mention": TONES, "tone_reply": TONES,
    "preview": PREVIEWS,
}


def normalized(value):
    value = value if isinstance(value, dict) else {}
    return {
        **{key: value.get(key) is not False for key in KEYS},
        **{key: value.get(key) if value.get(key) in choices else choices[0]
           for key, choices in CHOICES.items()},
    }


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def notification_preferences(request):
    data = request.POST if request.method == "POST" else request.GET
    if data.get("account_id") != str(request.user.pk):
        return JsonResponse({"ok": False, "error": "Аккаунт изменился."}, status=409)
    if request.method == "POST":
        key, value = data.get("key"), data.get("value")
        initializing = data.get("initialize") == "1"
        if initializing:
            if any(data.get(k) not in {"0", "1"} for k in KEYS):
                return JsonResponse({"ok": False, "error": "Некорректные настройки."}, status=400)
        elif not ((key in KEYS and value in {"0", "1"})
                  or (key in CHOICES and value in CHOICES[key])):
            return JsonResponse({"ok": False, "error": "Некорректная настройка."}, status=400)
        # Lock and update one setting at a time to preserve concurrent edits
        # to different preferences made by different devices.
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=request.user.pk)
            preferences = normalized(user.notification_preferences)
            if initializing:
                if not user.notification_preferences:
                    preferences = normalized({k: data[k] == "1" for k in KEYS})
            else:
                preferences[key] = value == "1" if key in KEYS else value
            if not user.notification_preferences or not initializing:
                user.notification_preferences = preferences
                user.save(update_fields=["notification_preferences"])
    else:
        preferences = normalized(request.user.notification_preferences)
    return JsonResponse({"ok": True, "account_id": request.user.pk, "preferences": preferences})
