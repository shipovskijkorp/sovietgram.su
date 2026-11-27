from io import BytesIO

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from apps.accounts.models import User
from .models import Sticker, StickerPack


class StickerDiscoveryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("catalog_owner", "owner@example.test", "Test-pass-1945!")
        cls.peer = User.objects.create_user("catalog_peer", "peer@example.test", "Test-pass-1945!")
        data = BytesIO()
        Image.new("RGBA", (8, 8), "red").save(data, "WEBP")
        cls.image = data.getvalue()
        cls.pack = StickerPack.objects.create(owner=cls.owner, name="Public Cats")
        cls.sticker = Sticker.objects.create(pack=cls.pack, emoji="❤️", image=cls.image)
        cls.other = StickerPack.objects.create(owner=cls.peer, name="Private Dogs")
        Sticker.objects.create(pack=cls.other, emoji="❤️", image=cls.image)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.owner)

    def action(self, action, pack=None, **extra):
        pack = pack or self.pack
        return self.client.post(reverse("messenger:sticker_packs"), {
            "account_id": self.owner.pk, "pack_id": pack.pk, "action": action, **extra,
        })

    def catalog(self, **params):
        return self.client.get(reverse("messenger:sticker_catalog"), params)

    def test_explicit_opt_in_and_revocation(self):
        self.assertEqual(self.action("share").status_code, 200)
        self.assertNotContains(self.catalog(), self.pack.name)
        result = self.action("publish")
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json()["pack"]["catalog_published"])
        self.assertContains(self.catalog(), self.pack.name)
        self.assertNotContains(self.catalog(), self.other.name)
        self.assertNotContains(self.catalog(q="Dogs"), self.pack.name)
        self.assertContains(self.catalog(q="cats", sort="new"), self.pack.name)
        link = result.json()["pack"]["share_url"]
        self.assertEqual(self.action("unpublish").status_code, 200)
        self.assertNotContains(self.catalog(), self.pack.name)
        self.assertEqual(self.client.get(link).status_code, 200)
        self.action("publish")
        self.action("unshare")
        self.assertNotContains(self.catalog(), self.pack.name)
        self.assertEqual(self.client.get(link).status_code, 404)

    def test_foreign_empty_copies_and_removed_last_sticker(self):
        self.assertEqual(self.action("publish", self.other).status_code, 404)
        empty = StickerPack.objects.create(owner=self.owner, name="Empty")
        self.assertEqual(self.action("publish", empty).status_code, 400)
        copy = StickerPack.objects.create(owner=self.owner, name="Copy", source_pack_id=self.other.pk)
        Sticker.objects.create(pack=copy, emoji="❤️", image=self.image)
        self.assertEqual(self.action("publish", copy).status_code, 400)
        self.action("publish")
        self.assertEqual(self.action("remove", sticker_id=self.sticker.pk).status_code, 200)
        self.assertNotContains(self.catalog(), self.pack.name)
        self.pack.refresh_from_db()
        self.assertIsNone(self.pack.catalog_published_at)

    def test_catalog_counts_active_installed_copies(self):
        link = self.action("publish").json()["pack"]["share_url"]
        self.client.force_login(self.peer)
        self.assertEqual(self.client.post(link, {"account_id": self.peer.pk}).status_code, 302)
        page = self.catalog().context["page"]
        self.assertEqual(page.object_list[0].install_count, 1)
        self.assertEqual(page.object_list[0].sticker_count, 1)
        self.peer.is_active = False
        self.peer.save(update_fields=["is_active"])
        self.client.force_login(self.owner)
        self.assertEqual(self.catalog().context["page"].object_list[0].install_count, 0)

    def test_suggestions_account_privacy_variation_selectors_and_priority(self):
        favorite = Sticker.objects.create(pack=self.pack, emoji="❤ cat", image=self.image, is_favorite=True)
        url = reverse("messenger:sticker_suggestions")
        response = self.client.get(url, {"account_id": self.owner.pk, "emoji": "❤"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual([item["id"] for item in response.json()["items"]], [favorite.pk, self.sticker.pk])
        self.assertEqual(self.client.get(url, {"account_id": self.peer.pk, "emoji": "❤"}).status_code, 409)
        self.assertEqual(self.client.get(url, {"account_id": self.owner.pk, "emoji": "🐶"}).json()["items"], [])
