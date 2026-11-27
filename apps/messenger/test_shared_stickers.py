from io import BytesIO

from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse
from PIL import Image

from apps.accounts.models import User
from .models import Sticker, StickerPack


class SharedStickerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("share_owner", "share-owner@example.net", "Password-1945!")
        cls.peer = User.objects.create_user("share_peer", "share-peer@example.net", "Password-1945!")
        cls.pack = StickerPack.objects.create(owner=cls.owner, name="Shared")
        data = BytesIO()
        Image.new("RGBA", (8, 8), "red").save(data, "WEBP")
        cls.sticker = Sticker.objects.create(pack=cls.pack, image=data.getvalue(), emoji="X",
                                             is_favorite=True)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.owner)
        self.peer_client = Client()
        self.peer_client.force_login(self.peer)
        self.endpoint = reverse("messenger:sticker_packs")

    def act(self, action, **extra):
        return self.client.post(self.endpoint, {"account_id": self.owner.pk,
            "pack_id": self.pack.pk, "action": action, **extra})

    def test_opt_in_install_copy_and_revoke(self):
        self.assertEqual(self.peer_client.get(reverse("messenger:sticker_image",
            args=[self.sticker.pk])).status_code, 404)
        result = self.act("share")
        self.assertEqual(result.status_code, 200)
        link = result.json()["pack"]["share_url"]
        self.pack.refresh_from_db()
        self.assertEqual(self.act("share").json()["pack"]["share_url"], link)
        image = reverse("messenger:shared_sticker_image", args=[self.pack.share_token, self.sticker.pk])
        page = self.peer_client.get(link)
        self.assertContains(page, "Установить набор")
        self.assertIn("no-store", page["Cache-Control"])
        self.assertEqual(page["Referrer-Policy"], "no-referrer")
        self.assertEqual(self.peer_client.get(image).content, bytes(self.sticker.image))
        self.assertEqual(Client().get(link).status_code, 302)
        self.assertEqual(Client().get(image).status_code, 302)
        self.assertEqual(self.peer_client.post(link, {"account_id": self.owner.pk}).status_code, 409)
        for _ in range(2):
            self.assertEqual(self.peer_client.post(link, {"account_id": self.peer.pk}).status_code, 302)
        copy = StickerPack.objects.get(owner=self.peer, source_pack_id=self.pack.pk)
        item = copy.stickers.get()
        self.assertEqual(bytes(item.image), bytes(self.sticker.image))
        self.assertFalse(item.is_favorite)
        self.assertIsNone(item.last_used_at)
        self.assertIsNone(copy.share_token)
        self.assertContains(self.peer_client.get(link), "уже есть")
        self.assertEqual(self.act("unshare").status_code, 200)
        self.assertEqual(self.peer_client.get(link).status_code, 404)
        self.assertEqual(self.peer_client.get(image).status_code, 404)
        self.assertEqual(self.act("delete").status_code, 200)
        self.assertTrue(StickerPack.objects.filter(pk=copy.pk).exists())
        self.assertEqual(self.peer_client.get(reverse("messenger:sticker_image", args=[item.pk])).status_code, 200)

    def test_update_preserves_local_copies_and_respects_revocation(self):
        link = self.act("share").json()["pack"]["share_url"]
        self.peer_client.post(link, {"account_id": self.peer.pk})
        copy = StickerPack.objects.get(owner=self.peer, source_pack_id=self.pack.pk)
        local = copy.stickers.get()
        local.is_favorite = True
        local.save(update_fields=["is_favorite"])
        own = Sticker.objects.create(pack=copy, image=b"own", emoji="Own")
        Sticker.objects.create(pack=self.pack, image=b"new", emoji="New")
        self.assertContains(self.peer_client.get(link), "Обновить набор")
        for _ in range(2):
            self.assertEqual(self.peer_client.post(link, {"account_id": self.peer.pk, "action":"update"}).status_code, 302)
        self.assertEqual(copy.stickers.count(), 3)
        local.refresh_from_db()
        self.assertTrue(local.is_favorite)
        self.assertTrue(copy.stickers.filter(pk=own.pk).exists())
        self.assertTrue(copy.stickers.filter(emoji="New").exists())
        self.sticker.delete()
        self.assertEqual(self.peer_client.post(link, {"account_id":self.peer.pk, "action":"update"}).status_code, 302)
        self.assertEqual(copy.stickers.count(), 3)
        self.act("unshare")
        replacement = self.act("share").json()["pack"]["share_url"]
        self.assertEqual(self.peer_client.post(link, {"account_id":self.peer.pk, "action":"update"}).status_code, 404)
        listed = self.peer_client.get(self.endpoint).json()["packs"][0]
        self.assertEqual(listed["source_url"], link)
        self.assertNotEqual(listed["source_url"], replacement)
        self.assertEqual(self.peer_client.post(replacement, {"account_id":self.peer.pk, "action":"update"}).status_code, 302)

    def test_update_capacity_atomic_and_legacy_copy(self):
        link = self.act("share").json()["pack"]["share_url"]
        copy = StickerPack.objects.create(owner=self.peer, name="Legacy", source_pack_id=self.pack.pk)
        Sticker.objects.bulk_create([Sticker(pack=copy, image=b"own", emoji=str(i)) for i in range(40)])
        self.assertEqual(self.peer_client.post(link, {"account_id":self.peer.pk, "action":"update"}).status_code, 400)
        self.assertEqual(copy.stickers.count(), 40)
        copy.refresh_from_db()
        self.assertIsNone(copy.source_share_token)
        copy.stickers.first().delete()
        self.assertEqual(self.peer_client.post(link, {"account_id":self.peer.pk, "action":"update"}).status_code, 302)
        self.assertEqual(copy.stickers.count(), 40)
        copy.refresh_from_db()
        self.assertIsNotNone(copy.source_share_token)

    def test_owner_only_and_capacity(self):
        empty = StickerPack.objects.create(owner=self.owner, name="Empty")
        self.assertEqual(self.act("share", pack_id=empty.pk).status_code, 400)
        self.assertEqual(self.peer_client.post(self.endpoint, {
            "account_id": self.peer.pk, "action":"share", "pack_id":self.pack.pk,
        }).status_code, 404)
        link = self.act("share").json()["pack"]["share_url"]
        for n in range(10):
            StickerPack.objects.create(owner=self.peer, name=f"Pack {n}")
        self.assertEqual(self.peer_client.post(link, {"account_id": self.peer.pk}).status_code, 400)
        self.assertEqual(StickerPack.objects.filter(owner=self.peer).count(), 10)
        StickerPack.objects.filter(owner=self.peer, name="Pack 0").delete()
        StickerPack.objects.filter(owner=self.peer, name="Pack 1").update(name="Shared")
        self.assertEqual(self.peer_client.post(link, {"account_id": self.peer.pk}).status_code, 302)
        self.assertEqual(StickerPack.objects.get(owner=self.peer, source_pack_id=self.pack.pk).name, "Shared (2)")
        self.act("unshare")
        replacement = self.act("share").json()["pack"]["share_url"]
        self.assertNotEqual(replacement, link)
