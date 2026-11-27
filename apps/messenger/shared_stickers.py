"""Opt-in link sharing and explicit additive updates of private snapshots."""
import hashlib
from collections import Counter
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods

from .models import Sticker, StickerPack
from .ratelimit import rate_limit
from .stickers import MAX_PACKS, MAX_STICKERS


def shared_packs():
    return StickerPack.objects.filter(owner__is_active=True, owner__platform_suspended_at__isnull=True)


def page(request, pack, *, problem="", status=200):
    own_pack = pack.owner_id == request.user.pk
    installed = StickerPack.objects.filter(owner=request.user, source_pack_id=pack.pk).exists()
    response = render(request, "messenger/shared_sticker_pack.html", {
        "pack": pack,
        "stickers": pack.stickers.defer("image").all()[:MAX_STICKERS],
        "installed": own_pack or installed,
        "can_update": installed and not own_pack,
        "problem": problem,
    }, status=status)
    # The token is an access capability. Avoid sending it as a referrer.
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


def fingerprint(item):
    return item.emoji, hashlib.sha256(bytes(item.image)).digest()


def missing_stickers(source, local):
    counts = Counter(fingerprint(item) for item in local)
    missing = []
    for item in source:
        key = fingerprint(item)
        if counts[key]:
            counts[key] -= 1
        else:
            missing.append(item)
    return missing


def library_name(owner, original):
    names = {name.casefold() for name in StickerPack.objects.filter(owner=owner).values_list("name", flat=True)}
    if original.casefold() not in names:
        return original
    for number in range(2, MAX_PACKS + 2):
        suffix = f" ({number})"
        name = original[:48-len(suffix)] + suffix
        if name.casefold() not in names:
            return name
    raise ValueError("No unique library name")


@login_required
@never_cache
@ensure_csrf_cookie
@require_http_methods(["GET", "POST"])
@rate_limit("shared_sticker_pack")
def shared_sticker_pack(request, token):
    pack = get_object_or_404(shared_packs(), share_token=token)
    if request.method == "GET":
        return page(request, pack)
    if request.POST.get("account_id") != str(request.user.pk):
        return page(request, pack, problem="Аккаунт изменился. Откройте ссылку заново.", status=409)

    action = request.POST.get("action", "install")
    if action not in {"install", "update"}:
        return page(request, pack, problem="Неизвестное действие.", status=400)

    with transaction.atomic():
        # Existing library mutations serialize on the owner's user row.
        # Acquire source and recipient in a fixed order to avoid deadlocks.
        user_ids = sorted({pack.owner_id, request.user.pk})
        users = list(get_user_model().objects.select_for_update().filter(
            pk__in=user_ids, is_active=True, platform_suspended_at__isnull=True,
        ).order_by("pk").values_list("pk", flat=True))
        if users != user_ids:
            raise Http404
        pack = get_object_or_404(shared_packs(), pk=pack.pk, share_token=token)
        if pack.owner_id == request.user.pk:
            return redirect(reverse("messenger:home") + "?manage_stickers=1")
        installed = StickerPack.objects.filter(owner=request.user, source_pack_id=pack.pk).first()
        if installed:
            if action == "update":
                source = list(pack.stickers.all()[:MAX_STICKERS + 1])
                local = list(installed.stickers.all()[:MAX_STICKERS + 1])
                missing = missing_stickers(source, local)
                if len(source) > MAX_STICKERS or len(local) + len(missing) > MAX_STICKERS:
                    return page(request, pack, problem="Недостаточно места в наборе (лимит 40).", status=400)
                Sticker.objects.bulk_create([
                    Sticker(pack=installed, emoji=item.emoji, image=bytes(item.image))
                    for item in missing
                ])
            # Never discover a replacement token by source ID alone.
            installed.source_share_token = pack.share_token
            installed.auto_update_error = ""
            if installed.auto_update_at is not None:
                installed.auto_update_at = timezone.now() + timedelta(hours=6)
            installed.save(update_fields=["source_share_token", "auto_update_at", "auto_update_error"])
            return redirect(reverse("messenger:home") + "?manage_stickers=1")
        if action == "update":
            return page(request, pack, problem="Сначала установите набор.", status=409)
        if StickerPack.objects.filter(owner=request.user).count() >= MAX_PACKS:
            return page(request, pack, problem="Достигнут лимит: 10 наборов. Удалите ненужный набор.", status=400)
        items = list(pack.stickers.all()[:MAX_STICKERS + 1])
        if not items or len(items) > MAX_STICKERS:
            return page(request, pack, problem="Набор пуст или превышает допустимый размер.", status=400)
        copy = StickerPack.objects.create(
            owner=request.user, name=library_name(request.user, pack.name),
            source_pack_id=pack.pk, source_share_token=pack.share_token,
        )
        Sticker.objects.bulk_create([
            Sticker(pack=copy, emoji=item.emoji, image=bytes(item.image))
            for item in items
        ])
    return redirect(reverse("messenger:home") + "?manage_stickers=1")


@login_required
@never_cache
@require_GET
def shared_sticker_image(request, token, sticker_id):
    item = get_object_or_404(Sticker.objects.filter(pack__in=shared_packs().filter(share_token=token)),
                            pk=sticker_id)
    response = HttpResponse(bytes(item.image), content_type="image/webp")
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "no-referrer"
    return response
