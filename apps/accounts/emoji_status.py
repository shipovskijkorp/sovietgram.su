"""Bounded opt-in emoji status, separate from presence and login state."""
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from apps.messenger.ratelimit import rate_limit
from .models import User
from .privacy import privacy_allows

# Explicit allowlist prevents invisible controls, arbitrary text or fake labels.
EMOJI_CHOICES = (
    ("", "Без статуса"), ("😀", "Отличное настроение"), ("😎", "На стиле"),
    ("🔥", "В огне"), ("❤️", "Любовь"), ("⭐", "Звезда"), ("🌙", "Отдыхаю"),
    ("💻", "Работаю"), ("📚", "Учусь"), ("🎮", "Играю"), ("🎧", "Слушаю музыку"),
    ("☕", "Перерыв"), ("🏖️", "В отпуске"), ("🚀", "В процессе"),
    ("🤔", "Думаю"), ("😴", "Сплю"), ("🎉", "Праздную"), ("💡", "Есть идея"),
    ("🛠️", "Занят"), ("🌿", "На природе"), ("❄️", "Зимнее настроение"),
    ("☀️", "Солнечно"), ("🐱", "Котик"), ("🐺", "Волк"),
    ("🫡", "На связи"), ("💤", "Не беспокоить"),
)
DURATIONS = (("0", "До удаления"), ("3600", "1 час"), ("28800", "8 часов"),
             ("86400", "1 день"), ("604800", "1 неделя"))


def visible_status(owner, viewer):
    if owner.platform_suspended_at and not (viewer and viewer.is_authenticated and viewer.pk == owner.pk):
        return {"emoji": "", "until": ""}
    if not owner.emoji_status or (owner.emoji_status_until and owner.emoji_status_until <= timezone.now()):
        return {"emoji": "", "until": ""}
    # Status is part of the bio/profile information and respects that rule.
    if not privacy_allows(owner, viewer, "bio"):
        return {"emoji": "", "until": ""}
    return {"emoji": owner.emoji_status,
            "until": owner.emoji_status_until.isoformat() if owner.emoji_status_until else ""}


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
@rate_limit("profile_status")
def settings_view(request):
    if request.method == "GET":
        return render(request, "accounts/emoji_status.html", {
            "choices": EMOJI_CHOICES, "durations": DURATIONS,
            "status": visible_status(request.user, request.user),
        })
    ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
    emoji = request.POST.get("emoji", "")
    duration = request.POST.get("duration", "0")
    error = ""
    if request.POST.get("account_id") != str(request.user.pk):
        error = "Аккаунт изменился. Обновите страницу."
    elif emoji not in dict(EMOJI_CHOICES) or duration not in dict(DURATIONS):
        error = "Некорректный статус или срок."
    if error:
        return JsonResponse({"ok": False, "error": error}, status=400) if ajax else HttpResponseBadRequest(error)
    with transaction.atomic():
        owner = User.objects.select_for_update().get(pk=request.user.pk)
        owner.emoji_status = emoji
        owner.emoji_status_until = timezone.now() + timedelta(seconds=int(duration)) if emoji and duration != "0" else None
        owner.save(update_fields=["emoji_status", "emoji_status_until"])
        status = visible_status(owner, owner)
    if ajax:
        return JsonResponse({"ok": True, "emoji_status": status})
    messages.success(request, "Статус сохранён.")
    return redirect(reverse("messenger:home") + "?profile=" + owner.username)
