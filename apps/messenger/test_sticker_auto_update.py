from datetime import timedelta
from io import BytesIO, StringIO

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.accounts.models import User
from .models import Sticker, StickerPack
from .sticker_auto_update import refresh_due_sticker_packs


def image(color):
    data = BytesIO()
    Image.new("RGBA", (8, 8), color).save(data, "WEBP")
    return data.getvalue()


class StickerAutoUpdateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("auto_source", "source@example.test", "Test-pass-1945!")
        cls.peer = User.objects.create_user("auto_peer", "peer@example.test", "Test-pass-1945!")
        cls.source = StickerPack.objects.create(owner=cls.owner, name="Source")
        Sticker.objects.create(pack=cls.source, emoji="A", image=image("red"))

    def setUp(self):
        cache.clear()
        self.client.force_login(self.owner)
        self.endpoint = reverse("messenger:sticker_packs")
        result = self.client.post(self.endpoint, {"account_id":self.owner.pk, "action":"share", "pack_id":self.source.pk})
        self.assertEqual(result.status_code, 200)
        self.link = result.json()["pack"]["share_url"]
        self.source.refresh_from_db()
        self.client.force_login(self.peer)
        self.assertEqual(self.client.post(self.link, {"account_id":self.peer.pk}).status_code, 302)
        self.local = StickerPack.objects.get(owner=self.peer, source_pack_id=self.source.pk)

    def toggle(self, enabled, pack=None):
        return self.client.post(self.endpoint, {"account_id":self.peer.pk, "action":"auto_update",
            "pack_id":(pack or self.local).pk, "enabled":enabled})

    def test_opt_in_additive_and_idempotent(self):
        old = self.local.stickers.get()
        old.is_favorite = True
        old.save(update_fields=["is_favorite"])
        self.local.name = "My name"
        self.local.save(update_fields=["name"])
        Sticker.objects.create(pack=self.source, emoji="B", image=image("blue"))
        self.assertIsNone(self.local.auto_update_at)
        self.assertEqual(refresh_due_sticker_packs(), 0)
        self.assertEqual(self.toggle("1").status_code, 200)
        now = timezone.now()
        self.assertEqual(refresh_due_sticker_packs(now=now), 1)
        self.assertEqual(refresh_due_sticker_packs(now=now), 0)
        self.assertEqual(self.local.stickers.count(), 2)
        old.refresh_from_db()
        self.assertTrue(old.is_favorite)
        self.local.refresh_from_db()
        self.assertEqual(self.local.name, "My name")
        self.assertGreater(self.local.auto_update_at, now)
        self.assertEqual(self.toggle("0").status_code, 200)
        self.assertEqual(refresh_due_sticker_packs(now=now+timedelta(days=1)), 0)

    def test_revoked_token_never_discovers_rotated_link(self):
        self.assertEqual(self.toggle("1").status_code, 200)
        self.client.force_login(self.owner)
        for action in ("unshare", "share"):
            self.assertEqual(self.client.post(self.endpoint, {"account_id":self.owner.pk,
                "action":action,"pack_id":self.source.pk}).status_code, 200)
        Sticker.objects.create(pack=self.source, emoji="B", image=image("blue"))
        self.assertEqual(refresh_due_sticker_packs(), 0)
        self.local.refresh_from_db()
        self.assertIsNone(self.local.auto_update_at)
        self.assertTrue(self.local.auto_update_error)
        self.assertEqual(self.local.stickers.count(), 1)

    def test_worker_limit_and_no_partial_update(self):
        Sticker.objects.bulk_create([Sticker(pack=self.local, emoji=str(i), image=image("green"))
                                     for i in range(39)])
        Sticker.objects.create(pack=self.source, emoji="B", image=image("blue"))
        self.assertEqual(self.toggle("1").status_code, 200)
        self.assertEqual(refresh_due_sticker_packs(limit=0), 0)
        call_command("run_maintenance", message_limit=0, account_limit=0, sticker_limit=1, stdout=StringIO())
        self.local.refresh_from_db()
        self.assertEqual(self.local.stickers.count(), 40)
        self.assertTrue(self.local.auto_update_error)
        self.assertIsNotNone(self.local.auto_update_at)

    def test_foreign_or_original_pack_cannot_enable(self):
        self.assertEqual(self.toggle("1", self.source).status_code, 404)
        own = StickerPack.objects.create(owner=self.peer, name="My own")
        self.assertEqual(self.toggle("1", own).status_code, 400)

