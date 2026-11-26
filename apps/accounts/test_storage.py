from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.messenger.models import Message, MessageAttachment, Sticker, StickerPack
from apps.messenger.services import get_or_create_direct_chat
from .models import User
from .storage_views import storage_summary


class StorageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("storage_alice", "storage-a@example.net", "Password-1945!")
        cls.bob = User.objects.create_user("storage_bob", "storage-b@example.net", "Password-1945!")
        cls.chat = get_or_create_direct_chat(cls.alice, cls.bob)
        cls.own = Message.objects.create(chat=cls.chat, sender=cls.alice, text="audio")
        peer = Message.objects.create(chat=cls.chat, sender=cls.bob, text="other")
        MessageAttachment.objects.create(message=cls.own, file="messages/audio.ogg",
            kind="audio", size=1024, original_name="audio.ogg", mime_type="audio/ogg")
        MessageAttachment.objects.create(message=peer, file="messages/other.ogg",
            kind="audio", size=9999, original_name="other.ogg", mime_type="audio/ogg")
        pack = StickerPack.objects.create(owner=cls.alice, name="Mine")
        Sticker.objects.create(pack=pack, image=b"123456")

    def setUp(self):
        cache.clear()
        self.client.force_login(self.alice)
        self.url = reverse("accounts:storage")

    def test_storage_counts_only_own_uploads(self):
        summary = storage_summary(self.alice)
        self.assertEqual(summary["attachment_bytes"], 1024)
        self.assertEqual(summary["attachment_count"], 1)
        self.assertEqual(summary["sticker_bytes"], 6)
        self.assertEqual(summary["total_known"], 1030)
        self.assertContains(self.client.get(self.url), "Данные и хранилище")

    def test_preload_setting_persists_and_updates_chat(self):
        self.assertEqual(self.client.post(self.url, {"account_id":self.bob.pk}).status_code, 400)
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.media_preload)
        self.assertRedirects(self.client.post(self.url, {"account_id":self.alice.pk}), self.url)
        self.alice.refresh_from_db()
        self.assertFalse(self.alice.media_preload)
        chat = self.client.get(reverse("messenger:chat", args=[self.chat.pk]))
        self.assertContains(chat, 'data-media-preload="false"')
        self.assertContains(chat, 'preload="none"')
        self.client.post(self.url, {"account_id":self.alice.pk, "media_preload":"on"})
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.media_preload)

    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
