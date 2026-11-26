"""Per-account media inventory and a non-destructive data-saving preference."""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import BigIntegerField, Count, Sum
from django.db.models.functions import Length
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from apps.messenger.models import MessageAttachment, Sticker
from .models import User


class StoragePreferenceForm(forms.Form):
    account_id = forms.IntegerField(widget=forms.HiddenInput())
    media_preload = forms.BooleanField(required=False, label="Предзагружать метаданные аудио и видео")


def storage_summary(user):
    # This is the size of surviving upload records, not a disk quota or a
    # count of other users' received content. No storage paths are exposed.
    uploads = MessageAttachment.objects.filter(message__sender=user, message__is_deleted=False)
    grouped = {
        row["kind"]: row for row in uploads.order_by().values("kind")
        .annotate(count=Count("pk"), size=Sum("size"))
    }
    categories = []
    for kind, label in MessageAttachment.Kind.choices:
        row = grouped.get(kind, {})
        categories.append({"label": label, "count": row.get("count", 0), "size": row.get("size", 0) or 0})
    stickers = Sticker.objects.filter(pack__owner=user).aggregate(
        count=Count("pk"), size=Sum(Length("image"), output_field=BigIntegerField()),
    )
    avatar_size = 0
    if user.avatar:
        try:
            avatar_size = user.avatar.size
        except (OSError, ValueError, NotImplementedError):
            avatar_size = None
    total = sum(row.get("size") or 0 for row in grouped.values())
    counts = sum(row.get("count", 0) for row in grouped.values())
    sticker_bytes = stickers["size"] or 0
    return {
        "categories": categories, "attachment_bytes": total, "attachment_count": counts,
        "sticker_bytes": sticker_bytes, "sticker_count": stickers["count"],
        "avatar_bytes": avatar_size,
        "total_known": total + sticker_bytes + (avatar_size or 0),
    }


@login_required
@never_cache
@ensure_csrf_cookie
@require_http_methods(["GET", "POST"])
def storage_settings(request):
    form = StoragePreferenceForm(
        request.POST if request.method == "POST" else None,
        initial={"account_id": request.user.pk, "media_preload": request.user.media_preload},
    )
    if request.method == "POST" and form.is_valid():
        if form.cleaned_data["account_id"] != request.user.pk:
            form.add_error(None, "Аккаунт изменился. Откройте настройки заново.")
        else:
            User.objects.filter(pk=request.user.pk, is_active=True).update(
                media_preload=form.cleaned_data["media_preload"],
            )
            messages.success(request, "Настройка сохранена.")
            return redirect("accounts:storage")
    return render(request, "accounts/storage.html", {
        "storage": storage_summary(request.user), "form": form,
    }, status=400 if request.method == "POST" else 200)
