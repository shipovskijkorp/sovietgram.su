"""Explicit public catalogue and account-private emoji recommendations."""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Exists, F, IntegerField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .models import Sticker, StickerPack
from .ratelimit import rate_limit
from .shared_stickers import shared_packs
from .stickers import sticker_payload, error


def emoji_key(value):
    return value.replace("\ufe0e", "").replace("\ufe0f", "").strip()


@login_required
@never_cache
@require_GET
@rate_limit("sticker_suggestions")
def sticker_suggestions(request):
    if request.GET.get("account_id") != str(request.user.pk):
        return error("Аккаунт изменился. Обновите страницу.", 409)
    raw = request.GET.get("emoji", "")
    if not raw or len(raw) > 24 or not emoji_key(raw):
        return error("Некорректный эмодзи.")
    key = emoji_key(raw)
    # A library is capped at 10 packs of 40 stickers. Never read image blobs
    # or consider a different account's stickers, even if they are shared.
    items = Sticker.objects.filter(pack__owner=request.user).exclude(emoji="").defer("image").order_by(
        "-is_favorite", F("last_used_at").desc(nulls_last=True), "-id",
    )[:400]
    matches = []
    for item in items:
        label = emoji_key(item.emoji)
        if key == label or key in label.split():
            matches.append(sticker_payload(item))
            if len(matches) == 8:
                break
    return JsonResponse({"ok": True, "account_id": request.user.pk, "items": matches})


@login_required
@never_cache
@require_GET
@rate_limit("sticker_catalog")
def sticker_catalog(request):
    query = request.GET.get("q", "").strip()[:80]
    sort = request.GET.get("sort", "popular")
    if sort not in {"popular", "new"}:
        sort = "popular"
    stickers = Sticker.objects.filter(pack_id=OuterRef("pk"))
    copies = StickerPack.objects.filter(
        source_pack_id=OuterRef("pk"), owner__is_active=True,
        owner__platform_suspended_at__isnull=True,
    ).order_by().values("source_pack_id").annotate(total=Count("pk")).values("total")
    packs = shared_packs().filter(
        catalog_published_at__isnull=False, share_token__isnull=False,
        source_pack_id__isnull=True,
    ).filter(Exists(stickers)).annotate(
        cover_id=Subquery(stickers.order_by("pk").values("pk")[:1]),
        sticker_count=Subquery(stickers.order_by().values("pack_id").annotate(total=Count("pk")).values("total"),
                               output_field=IntegerField()),
        install_count=Coalesce(Subquery(copies, output_field=IntegerField()), Value(0)),
    )
    if query:
        packs = packs.filter(name__icontains=query)
    order = ("-catalog_published_at", "-pk")
    if sort == "popular":
        order = ("-install_count", *order)
    page = Paginator(packs.order_by(*order), 20).get_page(request.GET.get("page"))
    response = render(request, "messenger/sticker_catalog.html", {"page": page, "query": query, "sort": sort})
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response
