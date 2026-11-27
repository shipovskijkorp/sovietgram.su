from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.storage_views import storage_summary
from .models import Chat, Message, MessageAttachment, SavedGif
from .services import get_or_create_direct_chat
from .test_gif_and_formatting import gif_bytes


class GifLibraryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("gif_owner", "owner@example.test", "Test-pass-1945!")
        cls.peer = User.objects.create_user("gif_peer", "peer@example.test", "Test-pass-1945!")
        cls.outsider = User.objects.create_user("gif_outsider", "outside@example.test", "Test-pass-1945!")
        cls.chat = get_or_create_direct_chat(cls.owner, cls.peer)

    def setUp(self):
        cache.clear()
        self.enterContext(override_settings(MEDIA_ROOT=self.enterContext(TemporaryDirectory())))
        self.client.force_login(self.owner)
        self.other = Client()
        self.other.force_login(self.peer)
        self.url = reverse("messenger:gif_library")

    def action(self, action, client=None, user=None, **fields):
        return (client or self.client).post(self.url, {
            "account_id": (user or self.owner).pk, "action": action, **fields,
        })

    def upload(self, **fields):
        return self.action("upload", file=SimpleUploadedFile("cats.gif", gif_bytes(), content_type="image/gif"), **fields)

    def listing(self, client=None, user=None, **fields):
        return (client or self.client).get(self.url, {"account_id":(user or self.owner).pk, **fields}).json()

    def asset(self, item, client=None, user=None, thumbnail=False):
        url = reverse("messenger:gif_thumbnail" if thumbnail else "messenger:gif_image", args=[item.pk])
        return (client or self.client).get(url, {"account_id":(user or self.owner).pk})

    def test_library_upload_dedup_search_and_favorite(self):
        response = self.upload(name="Котик", tags="СМЕХ реакция")
        self.assertEqual(response.status_code, 200, response.content)
        item = SavedGif.objects.get()
        self.assertTrue(item.favorite)
        self.assertTrue(item.can_publish)
        self.assertTrue(item.file.name.startswith("messages/gifs/"))
        self.assertEqual(self.listing(q="котик смех")["items"][0]["id"], item.pk)
        self.assertEqual(self.listing(self.other, self.peer)["items"], [])
        self.assertEqual(self.asset(item, self.other, self.peer).status_code, 404)
        self.assertTrue(self.upload(name="Duplicate").json()["already_saved"])
        self.assertEqual(SavedGif.objects.count(), 1)
        self.assertEqual(storage_summary(self.owner)["gif_bytes"], len(gif_bytes()))
        response = self.asset(item)
        self.assertEqual(response["Content-Type"], "image/gif")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(b"".join(response.streaming_content), gif_bytes())
        self.assertEqual(self.asset(item, thumbnail=True)["Content-Type"], "image/webp")
        self.assertEqual(self.action("favorite", gif_id=item.pk, enabled="0").status_code, 200)
        self.assertEqual(self.listing(scope="favorites")["items"], [])
        self.assertEqual(self.action("rename", gif_id=item.pk, name="New", tags="fun").status_code, 200)
        self.assertEqual(self.listing(q="fun")["items"][0]["name"], "New")
        self.assertEqual(self.client.get(self.url, {"account_id":self.peer.pk}).status_code, 409)

    def test_public_catalog_explicit_publish_copy_and_revocation(self):
        self.upload(name="Public cat", tags="funny")
        item = SavedGif.objects.get()
        self.assertEqual(self.listing(self.other, self.peer, scope="catalog")["items"], [])
        self.assertEqual(self.action("publish", gif_id=item.pk).status_code, 200)
        self.assertEqual(self.listing(self.other, self.peer, scope="catalog", q="funny")["items"][0]["id"], item.pk)
        self.assertEqual(self.asset(item, self.other, self.peer).status_code, 200)
        response = self.action("save_catalog", self.other, self.peer, gif_id=item.pk)
        self.assertEqual(response.status_code, 200, response.content)
        copy = SavedGif.objects.get(owner=self.peer)
        self.assertFalse(copy.can_publish)
        self.assertEqual(self.action("publish", self.other, self.peer, gif_id=copy.pk).status_code, 403)
        self.assertEqual(self.action("unpublish", gif_id=item.pk).status_code, 200)
        self.assertEqual(self.asset(item, self.other, self.peer).status_code, 404)
        self.assertEqual(self.action("save_catalog", self.other, self.peer, gif_id=item.pk).status_code, 404)
        path, storage = item.file.name, item.file.storage
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.action("delete", gif_id=item.pk).status_code, 200)
        self.assertFalse(storage.exists(path))
        response = self.asset(copy, self.other, self.peer)
        self.assertEqual(b"".join(response.streaming_content), gif_bytes())

    def test_copy_from_visible_message_and_protected_content(self):
        message = Message.objects.create(chat=self.chat, sender=self.owner)
        attachment = MessageAttachment.objects.create(
            message=message, kind="image", original_name="cat.gif", mime_type="image/gif",
            size=len(gif_bytes()), file=SimpleUploadedFile("cat.gif", gif_bytes(), content_type="image/gif"))
        Chat.objects.filter(pk=self.chat.pk).update(protect_content=True)
        self.assertEqual(self.action("save_message", self.other, self.peer, attachment_id=attachment.pk).status_code, 403)
        Chat.objects.filter(pk=self.chat.pk).update(protect_content=False)
        self.client.force_login(self.outsider)
        self.assertEqual(self.action("save_message", user=self.outsider, attachment_id=attachment.pk).status_code, 404)
        response = self.action("save_message", self.other, self.peer, attachment_id=attachment.pk)
        self.assertEqual(response.status_code, 200, response.content)
        item = SavedGif.objects.get(owner=self.peer)
        self.assertFalse(item.can_publish)
        attachment.file.delete(save=False)
        attachment.delete()
        self.assertEqual(b"".join(self.asset(item, self.other, self.peer).streaming_content), gif_bytes())

    def test_invalid_quota_and_account_cleanup(self):
        response = self.action("upload", file=SimpleUploadedFile("broken.gif", b"no GIF"))
        self.assertEqual(response.status_code, 400)
        with patch("apps.messenger.gifs.MAX_LIBRARY_BYTES", 1):
            self.assertEqual(self.upload().status_code, 409)
        self.assertFalse(SavedGif.objects.exists())
        self.assertEqual(self.upload().status_code, 200)
        item = SavedGif.objects.get()
        storage, path = item.file.storage, item.file.name
        with self.captureOnCommitCallbacks(execute=True):
            self.owner.delete()
        self.assertFalse(storage.exists(path))
