"""Owner-only previous photos, bounded retention and explicit restoration."""
import mimetypes

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .models import AvatarHistory, User

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
    if operation not in {"restore", "delete"}:
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
        else:
            photo.delete()
            delete_unused_avatar(name, storage)
            messages.success(request, "Фотография удалена из истории.")
    return redirect("accounts:avatar_history")
