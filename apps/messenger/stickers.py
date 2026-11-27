"""Private sticker library; every sent sticker becomes an immutable chat attachment."""
from io import BytesIO
from math import isfinite
from uuid import uuid4
import warnings

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods
from PIL import Image, ImageOps, UnidentifiedImageError

from . import views
from .models import MessageAttachment, Sticker, StickerPack
from .ratelimit import rate_limit

MAX_PACKS = 10
MAX_STICKERS = 40
MAX_UPLOAD = 2 * 1024 * 1024
MAX_STICKER = 256 * 1024


# Animation budgets bound decoded memory, frame count and encoder work.
MAX_ANIMATION_FRAMES = 60
MAX_ANIMATION_DURATION_MS = 5000
MAX_ANIMATION_PIXELS = 20 * 1024 * 1024
MAX_ANIMATION_EDGE = 1024


def clean_frame(frame, edge=512):
    rgba = frame.convert("RGBA")
    rgba.thumbnail((edge, edge), Image.Resampling.LANCZOS)
    # The fresh canvas preserves alpha while dropping source metadata.
    clean = Image.new("RGBA", rgba.size)
    clean.paste(rgba)
    return clean


def normalize_animation(image, count):
    # APNG may contain a standalone poster before the actual animation.
    start = 1 if image.format == "PNG" and image.info.get("default_image") else 0
    frames_count = count - start
    if not 1 <= frames_count <= MAX_ANIMATION_FRAMES:
        raise ValueError("Анимация должна содержать не более 60 кадров.")
    if (max(image.size) > MAX_ANIMATION_EDGE
            or image.width * image.height * frames_count > MAX_ANIMATION_PIXELS):
        raise ValueError("Слишком большое разрешение или число пикселей анимации.")
    frames, durations = [], []
    total = 0
    for index in range(start, count):
        image.seek(index)
        # Pillow composes disposal/blending for GIF/APNG. Loading also sets
        # the duration for animated WebP before the frame is copied.
        image.load()
        raw = float(image.info.get("duration", 100) or 100)
        if not isfinite(raw) or raw < 0:
            raise ValueError("Некорректная длительность кадра.")
        duration = max(20, round(raw))
        total += duration
        if total > MAX_ANIMATION_DURATION_MS:
            raise ValueError("Анимация должна длиться не более 5 секунд.")
        durations.append(duration)
        frames.append(clean_frame(image))
    if len(frames) == 1:
        return encode_static(frames[0])

    # Bounded attempts: preserve motion, transparency and frame order;
    # reduce image quality/resolution rather than drop or speed up frames.
    for edge, quality in ((512, 80), (512, 55), (384, 50), (256, 35)):
        encoded = frames if max(frames[0].size) <= edge else [
            clean_frame(frame, edge) for frame in frames
        ]
        output = BytesIO()
        encoded[0].save(
            output, format="WEBP", save_all=True, append_images=encoded[1:],
            duration=durations, loop=0, quality=quality, method=2,
        )
        if output.tell() <= MAX_STICKER:
            return output.getvalue()
    raise ValueError("Не удалось сжать анимированный стикер до 256 КБ.")


def encode_static(clean):
    for quality in (90, 75, 55, 35):
        output = BytesIO()
        clean.save(output, format="WEBP", quality=quality, method=4)
        if output.tell() <= MAX_STICKER:
            return output.getvalue()
    raise ValueError("Не удалось сжать стикер до 256 КБ.")


def normalize_image(source):
    """Normalize bounded static or animated raster images to WebP."""
    if len(source) > MAX_UPLOAD:
        raise ValueError("Изображение должно быть не больше 2 МБ.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(source)) as image:
                if image.format not in {"PNG", "WEBP", "JPEG", "GIF"}:
                    raise ValueError("Используйте PNG, WebP, GIF или JPEG.")
                if image.width * image.height > 4096 * 4096 or max(image.size) > 4096:
                    raise ValueError("Слишком большое разрешение изображения.")
                count = getattr(image, "n_frames", 1)
                if count > 1:
                    return normalize_animation(image, count)
                return encode_static(clean_frame(ImageOps.exif_transpose(image)))
    except (UnidentifiedImageError, OSError, EOFError, SyntaxError, OverflowError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError("Не удалось прочитать изображение.") from None


def error(message, status=400):
    return JsonResponse({"ok": False, "error": message}, status=status)


def sticker_payload(item):
    return {"id": item.pk, "pack_id": item.pack_id, "emoji": item.emoji,
            "favorite": item.is_favorite, "url": reverse("messenger:sticker_image", args=[item.pk])}


def pack_payload(pack):
    return {"id": pack.pk, "name": pack.name,
            "share_url": reverse("messenger:shared_sticker_pack", args=[pack.share_token]) if pack.share_token else "",
            "source_url": reverse("messenger:shared_sticker_pack", args=[pack.source_share_token]) if pack.source_share_token else "",
            "installed_copy": pack.source_pack_id is not None,
            "catalog_published": pack.catalog_published_at is not None,
            "stickers": [
        sticker_payload(item) for item in pack.stickers.defer("image").all()
    ]}


@login_required
@require_http_methods(["GET", "POST"])
@rate_limit("sticker_packs")
def sticker_packs(request):
    if request.method == "GET":
        if request.GET.get("account_id", str(request.user.pk)) != str(request.user.pk):
            return error("Аккаунт изменился. Обновите страницу.", 409)
        library = Sticker.objects.filter(pack__owner=request.user).defer("image")
        response = JsonResponse({
            "ok": True, "account_id": request.user.pk,
            "packs": [pack_payload(pack) for pack in StickerPack.objects.filter(owner=request.user)],
            "favorites": [sticker_payload(item) for item in library.filter(is_favorite=True).order_by("-id")],
            "recent": [sticker_payload(item) for item in library.filter(last_used_at__isnull=False)
                       .order_by("-last_used_at", "-id")[:30]],
        })
        response["Cache-Control"] = "private, no-store"
        return response

    if request.POST.get("account_id") != str(request.user.pk):
        return error("Аккаунт изменился. Обновите страницу.", 409)
    action = request.POST.get("action", "")
    if action not in {"create", "rename", "delete", "add", "remove", "save_message", "favorite", "forget_recent", "clear_recent", "share", "unshare", "publish", "unpublish"}:
        return error("Неизвестное действие.")
    image = None
    emoji = request.POST.get("emoji", "").strip()
    if len(emoji) > 24 or any(ord(c) < 32 for c in emoji):
        return error("Подпись стикера должна содержать не более 24 символов.")
    if action == "add":
        upload = request.FILES.get("image")
        if not upload or upload.size > MAX_UPLOAD:
            return error("Выберите изображение размером не более 2 МБ.")
        try:
            image = normalize_image(upload.read(MAX_UPLOAD + 1))
        except ValueError as exc:
            return error(str(exc))
    elif action == "save_message":
        try:
            attachment_id = int(request.POST.get("attachment_id", ""))
            if not 0 < attachment_id <= 9223372036854775807:
                raise ValueError
        except (ValueError, TypeError, OverflowError):
            return error("Некорректный стикер.")
        attachment = views._attachment_for_user(request.user, attachment_id)
        if attachment.kind != MessageAttachment.Kind.STICKER or attachment.message.chat.protect_content:
            return error("Сохранение этого стикера запрещено.", 403)
        try:
            with attachment.file.open("rb") as source:
                image = normalize_image(source.read(MAX_UPLOAD + 1))
        except (OSError, ValueError):
            return error("Стикер недоступен.")
    with transaction.atomic():
        get_user_model().objects.select_for_update().only("id").get(pk=request.user.pk)
        packs = StickerPack.objects.filter(owner=request.user)
        library = Sticker.objects.filter(pack__owner=request.user)
        if action == "clear_recent":
            library.filter(last_used_at__isnull=False).update(last_used_at=None)
            return JsonResponse({"ok": True})
        if action in {"favorite", "forget_recent"}:
            try:
                sticker_id = int(request.POST.get("sticker_id", ""))
                if not 0 < sticker_id <= 9223372036854775807:
                    raise ValueError
            except (ValueError, TypeError, OverflowError):
                return error("Некорректный стикер.")
            item = get_object_or_404(library.defer("image"), pk=sticker_id)
            if action == "favorite":
                value = request.POST.get("favorite")
                if value not in {"0", "1"}:
                    return error("Некорректное состояние избранного.")
                item.is_favorite = value == "1"
                item.save(update_fields=["is_favorite"])
            else:
                item.last_used_at = None
                item.save(update_fields=["last_used_at"])
            return JsonResponse({"ok": True, "sticker": sticker_payload(item)})
        name = request.POST.get("name", "").strip()
        if action in {"create", "rename"}:
            if not 1 <= len(name) <= 48 or any(ord(c) < 32 for c in name):
                return error("Название набора должно содержать от 1 до 48 символов.")
        if action == "create":
            if packs.count() >= MAX_PACKS:
                return error("Можно создать до 10 наборов.")
            if packs.filter(name__iexact=name).exists():
                return error("Набор с таким названием уже существует.")
            pack = StickerPack.objects.create(owner=request.user, name=name)
            return JsonResponse({"ok": True, "pack": pack_payload(pack)})
        try:
            pack_id = int(request.POST.get("pack_id", ""))
            if not 0 < pack_id <= 9223372036854775807:
                raise ValueError
        except (ValueError, TypeError, OverflowError):
            return error("Некорректный набор.")
        pack = get_object_or_404(packs, pk=pack_id)
        if action == "rename":
            if packs.exclude(pk=pack.pk).filter(name__iexact=name).exists():
                return error("Набор с таким названием уже существует.")
            pack.name = name
            pack.save(update_fields=["name"])
        elif action == "share":
            if not pack.stickers.exists():
                return error("Добавьте хотя бы один стикер перед публикацией.")
            if pack.share_token is None:
                pack.share_token = uuid4()
                pack.save(update_fields=["share_token"])
        elif action == "publish":
            if pack.source_pack_id is not None:
                return error("В каталог можно публиковать только собственные наборы.")
            if not pack.stickers.exists():
                return error("Добавьте хотя бы один стикер перед публикацией.")
            if pack.share_token is None:
                pack.share_token = uuid4()
            if pack.catalog_published_at is None:
                pack.catalog_published_at = timezone.now()
            pack.save(update_fields=["share_token", "catalog_published_at"])
        elif action == "unpublish":
            if pack.catalog_published_at is not None:
                pack.catalog_published_at = None
                pack.save(update_fields=["catalog_published_at"])
        elif action == "unshare":
            if pack.share_token is not None or pack.catalog_published_at is not None:
                pack.share_token = None
                pack.catalog_published_at = None
                pack.save(update_fields=["share_token", "catalog_published_at"])
        elif action == "delete":
            pack.delete()
            return JsonResponse({"ok": True})
        elif action in {"add", "save_message"}:
            if pack.stickers.count() >= MAX_STICKERS:
                return error("В наборе может быть не более 40 стикеров.")
            Sticker.objects.create(pack=pack, emoji=emoji, image=image)
        elif action == "remove":
            try:
                sticker_id = int(request.POST.get("sticker_id", ""))
                if not 0 < sticker_id <= 9223372036854775807:
                    raise ValueError
            except (ValueError, TypeError, OverflowError):
                return error("Некорректный стикер.")
            get_object_or_404(pack.stickers, pk=sticker_id).delete()
            if pack.catalog_published_at is not None and not pack.stickers.exists():
                pack.catalog_published_at = None
                pack.save(update_fields=["catalog_published_at"])
        return JsonResponse({"ok": True, "pack": pack_payload(pack)})


@login_required
@require_GET
def sticker_image(request, sticker_id):
    sticker = get_object_or_404(Sticker, pk=sticker_id, pack__owner=request.user)
    response = HttpResponse(bytes(sticker.image), content_type="image/webp")
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
