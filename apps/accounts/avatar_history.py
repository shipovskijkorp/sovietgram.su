"""Owner-only previous photos, bounded retention and explicit restoration."""
import mimetypes

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .models import AvatarHistory, User
from .privacy import privacy_allows
from apps.messenger.ratelimit import rate_limit

HISTORY_LIMIT = 10


def delete_unused_avatar(name, storage):
    if not name or storage is None:
        return

    def cleanup():
        if not User.objects.filter(avatar=name).exists() and not AvatarHistory.objects.filter(image=name).exists():
            storage.delete(name)

    transaction.on_commit(cleanup, robust=True)


def archive_previous(user, name):
    """Caller holds the user row lock; name is an existing owned storage object."""
    if not name or name == user.avatar.name:
        return
    AvatarHistory.objects.get_or_create(user=user, image=name)
    obsolete = list(user.avatar_history.all()[HISTORY_LIMIT:])
    for row in obsolete:
        image_name, storage = row.image.name, row.image.storage
        row.delete()
        delete_unused_avatar(image_name, storage)


@login_required
@never_cache
@require_GET
def history(request):
    return render(request, "accounts/avatar_history.html", {
        "photos": request.user.avatar_history.all()[:HISTORY_LIMIT],
        "history_limit": HISTORY_LIMIT,
    })


@login_required
@never_cache
@require_GET
def image(request, photo_id):
    photo = get_object_or_404(AvatarHistory, pk=photo_id, user=request.user)
    try:
        handle = photo.image.open("rb")
    except (FileNotFoundError, OSError, ValueError):
        raise Http404
    mime = mimetypes.guess_type(photo.image.name)[0]
    if mime not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
        handle.close()
        raise Http404
    response = FileResponse(handle, content_type=mime)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
@never_cache
@require_POST
def action(request, photo_id):
    if request.POST.get("account_id") != str(request.user.pk):
        return HttpResponseBadRequest("Аккаунт изменился. Обновите страницу.")
    operation = request.POST.get("action")
    if operation not in {"restore", "delete", "share", "unshare"}:
        return HttpResponseBadRequest("Неизвестное действие.")
    with transaction.atomic():
        user = get_object_or_404(User.objects.select_for_update(), pk=request.user.pk)
        photo = get_object_or_404(AvatarHistory, pk=photo_id, user=user)
        name, storage = photo.image.name, photo.image.storage
        if operation == "restore":
            if not storage.exists(name):
                messages.error(request, "Файл фотографии недоступен.")
                return redirect("accounts:avatar_history")
            previous = user.avatar.name
            user.avatar = name
            user.save(update_fields=["avatar"])
            photo.delete()
            archive_previous(user, previous)
            messages.success(request, "Фотография профиля восстановлена.")
        elif operation in {"share", "unshare"}:
            if operation == "share" and not storage.exists(name):
                messages.error(request, "Файл фотографии недоступен.")
                return redirect("accounts:avatar_history")
            photo.is_shared = operation == "share"
            photo.save(update_fields=["is_shared"])
            messages.success(request, "Фотография добавлена в галерею." if photo.is_shared else "Фотография скрыта из галереи.")
        else:
            photo.delete()
            delete_unused_avatar(name, storage)
            messages.success(request, "Фотография удалена из истории.")
    return redirect("accounts:avatar_history")


def gallery_allowed(owner, viewer):
    return bool(owner.is_active and (not owner.platform_suspended_at or
        (viewer and viewer.is_authenticated and viewer.pk == owner.pk))
        and privacy_allows(owner, viewer, "profile_photo"))


def gallery_payload(owner, viewer):
    if not gallery_allowed(owner, viewer):
        return []
    photos = []
    if owner.avatar:
        photos.append({"id": "current", "url": owner.avatar_url, "current": True})
    for photo in owner.avatar_history.filter(is_shared=True)[:HISTORY_LIMIT]:
        photos.append({"id": str(photo.pk),
                       "url": reverse("accounts:gallery_image", args=[owner.username, photo.pk]),
                       "current": False})
    return photos


@never_cache
@require_GET
@rate_limit("profile_gallery")
def gallery(request, username):
    owner = get_object_or_404(User, username__iexact=username, is_active=True)
    if not gallery_allowed(owner, request.user):
        raise Http404
    response = render(request, "accounts/profile_gallery.html", {
        "owner": owner, "photos": gallery_payload(owner, request.user),
    })
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


@never_cache
@require_GET
@rate_limit("profile_gallery")
def gallery_image(request, username, photo_id):
    owner = get_object_or_404(User, username__iexact=username, is_active=True)
    if not gallery_allowed(owner, request.user):
        raise Http404
    photo = get_object_or_404(AvatarHistory, pk=photo_id, user=owner, is_shared=True)
    mime = mimetypes.guess_type(photo.image.name)[0]
    if mime not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
        raise Http404
    try:
        handle = photo.image.open("rb")
    except (OSError, ValueError):
        raise Http404 from None
    response = FileResponse(handle, content_type=mime)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "no-referrer"
    return response
