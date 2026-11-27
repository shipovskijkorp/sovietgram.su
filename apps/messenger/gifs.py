"""Private GIF library and explicit, server-hosted opt-in catalogue.

No external search provider, remote URL importer or storage URL is exposed.
"""
import hashlib
import logging
from pathlib import Path
import unicodedata

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q, Sum
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods
from PIL import Image

from . import views
from .forms import _validate_inline_image
from .media_processing import THUMBNAIL_VERSION, cached_thumbnail
from .models import MessageAttachment, SavedGif
from .ratelimit import rate_limit

logger = logging.getLogger(__name__)
MAX_GIF_BYTES = 8 * 1024 * 1024
MAX_LIBRARY_BYTES = 100 * 1024 * 1024
MAX_LIBRARY_ITEMS = 100
PAGE_SIZE = 18


class GifError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _response(data=None, *, status=200):
    response = JsonResponse(data if data is not None else {"ok": True}, status=status)
    response["Cache-Control"] = "private, no-store"
    return response


def _key(value):
    return unicodedata.normalize("NFKC", value).casefold()


def _metadata(name, tags, fallback="GIF"):
    name = " ".join(name.split()) or fallback
    tags = " ".join(tags.split())
    if not name or len(name) > 80 or len(tags) > 160:
        raise GifError("Название до 80 символов, теги до 160 символов.")
    return name, tags, _key(name + " " + tags)[:512]


def _id(raw):
    try:
        value = int(raw)
        if not 0 < value <= 9223372036854775807:
            raise ValueError
        return value
    except (TypeError, ValueError, OverflowError):
        raise GifError("Некорректный идентификатор.") from None


def _public():
    return SavedGif.objects.filter(
        published_at__isnull=False, can_publish=True,
        owner__is_active=True, owner__platform_suspended_at__isnull=True,
    )


def _accessible(user):
    return SavedGif.objects.filter(
        Q(owner=user) | Q(pk__in=_public().values("pk"))
    )


def _payload(item, user, *, saved=None):
    own = item.owner_id == user.pk
    return {
        "id": item.pk, "name": item.name, "tags": item.tags, "size": item.size,
        "own": own, "favorite": item.favorite if own else False,
        "saved": own if saved is None else bool(saved),
        "can_publish": own and item.can_publish,
        "published": item.published_at is not None,
        "image_url": reverse("messenger:gif_image", args=[item.pk]),
        "thumbnail_url": reverse("messenger:gif_thumbnail", args=[item.pk]),
    }


def _bounded_read(source):
    raw = source.read(MAX_GIF_BYTES + 1)
    if not raw or len(raw) > MAX_GIF_BYTES:
        raise GifError("GIF должен занимать не более 8 МиБ.")
    stream = ContentFile(raw, name="animation.gif")
    try:
        _validate_inline_image(stream, ".gif")
    except forms.ValidationError as error:
        raise GifError(error.messages[0]) from error
    return raw


def _read_stored(item):
    try:
        with item.file.open("rb") as source:
            return _bounded_read(source)
    except (OSError, ValueError) as error:
        if isinstance(error, GifError):
            raise
        raise GifError("Исходный GIF недоступен.", 404) from error


def _list(request):
    scope = request.GET.get("scope", "library")
    if scope not in {"library", "favorites", "catalog"}:
        raise GifError("Неизвестный раздел GIF.")
    query = request.GET.get("q", "").strip()
    if len(query) > 80:
        raise GifError("Поиск ограничен 80 символами.")
    own = SavedGif.objects.filter(owner=request.user)
    if scope == "catalog":
        items = _public().annotate(
            saved_here=Exists(own.filter(digest=OuterRef("digest"))),
        ).order_by("-published_at", "-pk")
    else:
        items = own
        if scope == "favorites":
            items = items.filter(favorite=True)
        items = items.order_by("-favorite", "-created_at", "-pk")
    for word in _key(query).split()[:10]:
        items = items.filter(search_key__contains=word)
    page = Paginator(items, PAGE_SIZE).get_page(request.GET.get("page"))
    usage = own.aggregate(count=Count("pk"), size=Sum("size"))
    return _response({
        "ok": True, "account_id": request.user.pk, "scope": scope,
        "items": [_payload(item, request.user, saved=getattr(item, "saved_here", None)) for item in page],
        "page": page.number, "has_next": page.has_next(),
        "usage": {"count": usage["count"], "bytes": usage["size"] or 0,
                  "max_count": MAX_LIBRARY_ITEMS, "max_bytes": MAX_LIBRARY_BYTES},
    })


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
@rate_limit("gif_library")
def gif_library(request):
    data = request.GET if request.method == "GET" else request.POST
    if data.get("account_id") != str(request.user.pk):
        return _response({"ok": False, "error": "Аккаунт изменился. Обновите страницу."}, status=409)
    if not request.user.is_active or request.user.platform_suspended_at:
        return _response({"ok": False, "error": "Аккаунт недоступен."}, status=403)
    if request.method == "GET":
        try:
            return _list(request)
        except GifError as error:
            return _response({"ok": False, "error": str(error)}, status=error.status)

    action = data.get("action", "")
    saved_file = None
    committed = False
    try:
        if action in {"upload", "save_message", "save_catalog"}:
            if action == "upload":
                files = request.FILES.getlist("file")
                if len(files) != 1 or set(request.FILES) != {"file"}:
                    raise GifError("Выберите один GIF.")
                uploaded = files[0]
                if Path(uploaded.name).suffix.lower() != ".gif":
                    raise GifError("Поддерживаются только файлы GIF.")
                raw = _bounded_read(uploaded)
                fallback = Path(uploaded.name).stem[:80] or "GIF"
                name, tags, key = _metadata(data.get("name", ""), data.get("tags", ""), fallback)
            else:
                if request.FILES:
                    raise GifError("Неожиданные файлы.")
                # Read only an authorized source. Recheck under the sender lock
                # before creating the durable independent copy.
                source_id = _id(data.get("attachment_id" if action == "save_message" else "gif_id"))
                if action == "save_message":
                    source = views._attachment_for_user(request.user, source_id)
                    if source.message.chat.protect_content:
                        raise GifError("Копирование запрещено для этой переписки.", 403)
                    if source.kind not in {MessageAttachment.Kind.IMAGE, MessageAttachment.Kind.FILE} or Path(source.original_name).suffix.lower() != ".gif":
                        raise GifError("Это не GIF.")
                    raw = _read_stored(source)
                    name, tags, key = _metadata("", "", Path(source.original_name).stem[:80] or "GIF")
                else:
                    source = get_object_or_404(_public(), pk=source_id)
                    raw = _read_stored(source)
                    name, tags, key = _metadata(source.name, source.tags)
            digest = hashlib.sha256(raw).hexdigest()
            with transaction.atomic():
                owner = get_user_model().objects.select_for_update().filter(
                    pk=request.user.pk, is_active=True, platform_suspended_at__isnull=True,
                ).first()
                if owner is None:
                    raise GifError("Аккаунт недоступен.", 403)
                if action == "save_message":
                    source = views._attachment_for_user(owner, source_id)
                    if source.message.chat.protect_content:
                        raise GifError("Копирование запрещено для этой переписки.", 403)
                elif action == "save_catalog" and not _public().filter(pk=source_id, digest=digest).exists():
                    raise GifError("Публикация больше недоступна.", 404)
                item = SavedGif.objects.filter(owner=owner, digest=digest).first()
                if item is not None:
                    if not item.favorite:
                        item.favorite = True
                        item.save(update_fields=["favorite"])
                    return _response({"ok": True, "item": _payload(item, owner), "already_saved": True})
                usage = SavedGif.objects.filter(owner=owner).aggregate(count=Count("pk"), size=Sum("size"))
                if usage["count"] >= MAX_LIBRARY_ITEMS or (usage["size"] or 0) + len(raw) > MAX_LIBRARY_BYTES:
                    raise GifError("Библиотека заполнена: до 100 GIF и 100 МиБ.", 409)
                item = SavedGif(owner=owner, digest=digest, size=len(raw), name=name, tags=tags,
                                search_key=key, favorite=True, can_publish=action == "upload")
                item.file.save("animation.gif", ContentFile(raw), save=False)
                saved_file = (item.file.storage, item.file.name)
                item.save()
            committed = True
            return _response({"ok": True, "item": _payload(item, owner), "already_saved": False})

        if action not in {"rename", "favorite", "publish", "unpublish", "delete"}:
            raise GifError("Неизвестное действие.")
        if request.FILES:
            raise GifError("Неожиданные файлы.")
        with transaction.atomic():
            owner = get_user_model().objects.select_for_update().filter(
                pk=request.user.pk, is_active=True, platform_suspended_at__isnull=True,
            ).first()
            if owner is None:
                raise GifError("Аккаунт недоступен.", 403)
            item = get_object_or_404(SavedGif, owner=owner, pk=_id(data.get("gif_id")))
            if action == "delete":
                item.delete()
                return _response()
            if action == "rename":
                item.name, item.tags, item.search_key = _metadata(data.get("name", ""), data.get("tags", ""), item.name)
                item.save(update_fields=["name", "tags", "search_key"])
            elif action == "favorite":
                if data.get("enabled") not in {"0", "1"}:
                    raise GifError("Некорректное значение.")
                item.favorite = data["enabled"] == "1"
                item.save(update_fields=["favorite"])
            elif action == "publish":
                if not item.can_publish:
                    raise GifError("Публиковать можно только GIF, загруженные вами с устройства.", 403)
                if not item.file or not item.file.storage.exists(item.file.name):
                    raise GifError("GIF недоступен.", 404)
                if item.published_at is None:
                    item.published_at = timezone.now()
                    item.save(update_fields=["published_at"])
            else:
                item.published_at = None
                item.save(update_fields=["published_at"])
        return _response({"ok": True, "item": _payload(item, owner)})
    except GifError as error:
        return _response({"ok": False, "error": str(error)}, status=error.status)
    except OSError:
        logger.exception("Could not save GIF library entry")
        return _response({"ok": False, "error": "Не удалось сохранить GIF."}, status=503)
    finally:
        if saved_file is not None and not committed:
            try:
                saved_file[0].delete(saved_file[1])
            except OSError:
                logger.exception("Could not clean failed GIF upload")


def _image_item(request, gif_id):
    if request.GET.get("account_id") != str(request.user.pk) or not request.user.is_active or request.user.platform_suspended_at:
        raise Http404
    return get_object_or_404(_accessible(request.user), pk=gif_id)


def _image_headers(response):
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "no-referrer"
    return response


@login_required
@require_GET
@rate_limit("gif_asset")
def gif_image(request, gif_id):
    item = _image_item(request, gif_id)
    try:
        item.file.open("rb")
    except (OSError, ValueError):
        raise Http404 from None
    return _image_headers(FileResponse(item.file, content_type="image/gif", filename="animation.gif"))


@login_required
@require_GET
@rate_limit("gif_asset")
def gif_thumbnail(request, gif_id):
    item = _image_item(request, gif_id)
    if not item.file or not item.file.storage.exists(item.file.name):
        raise Http404
    try:
        version = hashlib.sha256(f"gif:{THUMBNAIL_VERSION}:{item.pk}:{item.digest}".encode()).hexdigest()
        content = cached_thumbnail(item, version)
    except (OSError, ValueError, EOFError, SyntaxError, Image.DecompressionBombError):
        raise Http404 from None
    return _image_headers(HttpResponse(content, content_type="image/webp"))
