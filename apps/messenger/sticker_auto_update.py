"""Bounded additive refresh of explicitly opted-in sticker snapshots."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .models import Sticker, StickerPack
from .shared_stickers import missing_stickers, shared_packs
from .stickers import MAX_STICKERS

INTERVAL = timedelta(hours=6)
SOURCE_UNAVAILABLE = "Исходная ссылка недоступна. Откройте новую ссылку и включите автообновление."
LIMIT_REACHED = "Недостаточно места в наборе (лимит 40)."


def _refresh_one(pack_id, now):
    snapshot = StickerPack.objects.filter(pk=pack_id, auto_update_at__lte=now).values(
        "owner_id", "source_pack_id",
    ).first()
    if not snapshot:
        return 0
    source_owner = StickerPack.objects.filter(pk=snapshot["source_pack_id"]).values_list("owner_id", flat=True).first()
    user_ids = sorted({pk for pk in (snapshot["owner_id"], source_owner) if pk is not None})
    with transaction.atomic():
        # Serialize with explicit installs/updates and owner mutations,
        # acquiring users in the same fixed order as shared_sticker_pack.
        users = set(get_user_model().objects.select_for_update().filter(
            pk__in=user_ids, is_active=True, platform_suspended_at__isnull=True,
        ).order_by("pk").values_list("pk", flat=True))
        local = StickerPack.objects.filter(
            pk=pack_id, owner_id=snapshot["owner_id"], auto_update_at__lte=now,
        ).first()
        if local is None:
            return 0
        source = None
        if (local.owner_id in users and source_owner in users and local.source_share_token is not None
                and local.source_pack_id == snapshot["source_pack_id"]):
            source = shared_packs().filter(pk=local.source_pack_id, owner_id=source_owner,
                                           share_token=local.source_share_token).first()
        if source is None or source.pk == local.pk:
            # Never resolve a new private token based on source ID.
            local.auto_update_at = None
            local.auto_update_error = SOURCE_UNAVAILABLE
            local.save(update_fields=["auto_update_at", "auto_update_error"])
            return 0
        source_items = list(source.stickers.all()[:MAX_STICKERS + 1])
        local_items = list(local.stickers.all()[:MAX_STICKERS + 1])
        missing = missing_stickers(source_items, local_items)
        if len(source_items) > MAX_STICKERS or len(local_items) + len(missing) > MAX_STICKERS:
            local.auto_update_error = LIMIT_REACHED
            added = 0
        else:
            Sticker.objects.bulk_create([
                Sticker(pack=local, emoji=item.emoji, image=bytes(item.image))
                for item in missing
            ])
            local.auto_update_error = ""
            added = len(missing)
        local.auto_update_at = now + INTERVAL
        local.save(update_fields=["auto_update_at", "auto_update_error"])
        return added


def refresh_due_sticker_packs(*, limit=10, now=None):
    """At most limit packs per maintenance run; each check has its own transaction."""
    now = now or timezone.now()
    ids = list(StickerPack.objects.filter(auto_update_at__lte=now)
               .order_by("auto_update_at", "pk").values_list("pk", flat=True)[:limit])
    return sum(_refresh_one(pk, now) for pk in ids)
