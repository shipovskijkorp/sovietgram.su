from io import BytesIO
from tempfile import TemporaryDirectory
from uuid import uuid4

from django.core.cache import cache, caches
from unittest.mock import patch
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, SimpleTestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.accounts.models import User
from .media_processing import compress_image_upload, make_thumbnail
from .models import Message, MessageAttachment, MessageHiddenForUser
from .services import get_or_create_direct_chat


def photo(name="photo.jpg", fmt="JPEG", size=(2600, 1600), mode="RGB", **kwargs):
    stream = BytesIO()
    Image.new(mode, size, "red").save(stream, format=fmt, **kwargs)
    mime = {"JPEG": "image/jpeg", "PNG": "image/png", "GIF": "image/gif", "WEBP": "image/webp"}[fmt]
    return SimpleUploadedFile(name, stream.getvalue(), content_type=mime)


class ImageCompressionTests(SimpleTestCase):
    def test_large_jpeg_reduces_dimensions_and_size(self):
        original = photo()
        output = compress_image_upload(original)
        self.assertLess(output.size, original.size)
        self.assertEqual(original.tell(), 0)
        with Image.open(output) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertLessEqual(max(image.size), 1920)
            self.assertEqual(image.size[0], 1920)

    def test_small_and_animated_remain_unchanged(self):
        small = photo(size=(80, 80))
        self.assertIs(compress_image_upload(small), small)
        stream = BytesIO()
        first = Image.new("RGBA", (50, 50), "red")
        second = Image.new("RGBA", (50, 50), "blue")
        first.save(stream, format="PNG", save_all=True, append_images=[second], duration=100, loop=0)
        animation = SimpleUploadedFile("animated.png", stream.getvalue(), content_type="image/png")
        self.assertIs(compress_image_upload(animation), animation)
        gif = photo("animation.gif", "GIF", (80, 80))
        self.assertIs(compress_image_upload(gif), gif)

    def test_png_preserves_alpha_and_extension(self):
        original = photo("alpha.png", "PNG", mode="RGBA")
        output = compress_image_upload(original)
        self.assertEqual(output.name, original.name)
        with Image.open(output) as image:
            self.assertEqual(image.mode, "RGBA")
            self.assertEqual(image.format, "PNG")
            self.assertLessEqual(max(image.size), 1920)


class CompressedSendTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("compress_alice", "alice@example.net", "Password-1945!")
        cls.bob = User.objects.create_user("compress_bob", "bob@example.net", "Password-1945!")
        cls.chat = get_or_create_direct_chat(cls.alice, cls.bob)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.alice)
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(override_settings(MEDIA_ROOT=directory))
        self.url = reverse("messenger:send_message", args=[self.chat.pk])

    def send(self, mode, compress, client_id):
        return self.client.post(self.url, {
            "account_id": self.alice.pk, "attachment_mode": mode,
            "attachments": photo(), "compress_images": compress,
            "client_message_id": client_id,
        }, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_opt_in_only_original_file_and_idempotent_retry(self):
        key = str(uuid4())
        compressed = self.send("media", "1", key)
        self.assertEqual(compressed.status_code, 200, compressed.content)
        repeated = self.send("media", "1", key)
        self.assertEqual(repeated.status_code, 200, repeated.content)
        self.assertTrue(repeated.json()["replayed"])
        original_size = photo().size
        plain = self.send("media", "", str(uuid4()))
        as_file = self.send("file", "1", str(uuid4()))
        self.assertEqual(plain.status_code, 200, plain.content)
        self.assertEqual(as_file.status_code, 200, as_file.content)
        self.assertLess(compressed.json()["message"]["attachments"][0]["size"], original_size)
        self.assertEqual(plain.json()["message"]["attachments"][0]["size"], original_size)
        self.assertEqual(as_file.json()["message"]["attachments"][0]["size"], original_size)
        self.assertEqual(Message.objects.filter(chat=self.chat).count(), 3)


class ThumbnailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("thumb_alice", "alice@example.net", "Password-1945!")
        cls.bob = User.objects.create_user("thumb_bob", "bob@example.net", "Password-1945!")
        cls.other = User.objects.create_user("thumb_other", "other@example.net", "Password-1945!")
        cls.chat = get_or_create_direct_chat(cls.alice, cls.bob)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.alice)
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(override_settings(MEDIA_ROOT=directory))
        original = photo("alpha.png", "PNG", (1800, 1200), "RGBA")
        self.original = original.read()
        original.seek(0)
        self.message = Message.objects.create(chat=self.chat, sender=self.bob)
        self.attachment = MessageAttachment.objects.create(
            message=self.message, file=original, kind="image",
            original_name=original.name, mime_type="image/png", size=original.size,
        )
        self.url = reverse("messenger:thumbnail_attachment", args=[self.attachment.pk])

    def test_cache_reuses_bytes_but_rechecks_access_and_source(self):
        thumbnail_cache = caches["thumbnails"]
        thumbnail_cache.clear()
        self.addCleanup(thumbnail_cache.clear)
        with patch("apps.messenger.media_processing.make_thumbnail", wraps=make_thumbnail) as transform:
            first = self.client.get(self.url)
            second = self.client.get(self.url)
            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.content, first.content)
            self.assertEqual(transform.call_count, 1)
            self.client.force_login(self.other)
            self.assertEqual(self.client.get(self.url).status_code, 404)
            self.assertEqual(transform.call_count, 1)
            self.client.force_login(self.alice)
            thumbnail_cache.clear()
            self.assertEqual(self.client.get(self.url).status_code, 200)
            self.assertEqual(transform.call_count, 2)
            self.attachment.file.storage.delete(self.attachment.file.name)
            self.assertEqual(self.client.get(self.url).status_code, 404)
            self.assertEqual(transform.call_count, 2)

    def test_thumbnail_is_small_and_original_is_unchanged(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/webp")
        self.assertIn("private", response["Cache-Control"])
        self.assertIn("Cookie", response["Vary"])
        with Image.open(BytesIO(response.content)) as image:
            self.assertEqual(image.size, (384, 256))
            self.assertEqual(image.format, "WEBP")
        etag = response["ETag"]
        self.assertEqual(self.client.get(self.url, HTTP_IF_NONE_MATCH=etag).status_code, 304)
        original = self.client.get(reverse("messenger:view_attachment", args=[self.attachment.pk]))
        self.assertEqual(b"".join(original.streaming_content), self.original)
        original.close()
        gallery = self.client.get(reverse("messenger:chat_gallery",args=[self.chat.pk])).json()
        self.assertEqual(gallery["items"][0]["thumbnail_url"], self.url)

    def test_access_is_checked_even_when_etag_matches(self):
        etag = self.client.get(self.url)["ETag"]
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url, HTTP_IF_NONE_MATCH=etag).status_code, 404)
        self.client.force_login(self.alice)
        MessageHiddenForUser.objects.create(message=self.message, user=self.alice)
        self.assertEqual(self.client.get(self.url, HTTP_IF_NONE_MATCH=etag).status_code, 404)

    def test_missing_file_returns_404_instead_of_server_error(self):
        self.attachment.file.storage.delete(self.attachment.file.name)
        for route in ("thumbnail_attachment", "view_attachment", "download_attachment"):
            url = reverse("messenger:" + route, args=[self.attachment.pk])
            self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get(reverse("messenger:view_attachment", args=[self.attachment.pk]), HTTP_RANGE="bytes=0-10").status_code,404)


class ThumbnailImageTests(SimpleTestCase):
    def test_transparent_animation_uses_first_frame(self):
        source = BytesIO()
        first = Image.new("RGBA", (500, 250), (0, 0, 0, 0))
        first.paste((255, 0, 0, 255), (150, 50, 350, 200))
        second = Image.new("RGBA", first.size, "blue")
        first.save(source, format="PNG", save_all=True, append_images=[second], duration=100, loop=0)
        source.seek(0)
        with Image.open(BytesIO(make_thumbnail(source))) as preview:
            self.assertEqual(preview.size, (384, 192))
            self.assertFalse(getattr(preview, "is_animated", False))
            self.assertEqual(preview.convert("RGBA").getpixel((0, 0))[3], 0)
