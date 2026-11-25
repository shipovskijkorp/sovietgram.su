from io import BytesIO
from tempfile import TemporaryDirectory
from uuid import uuid4

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, SimpleTestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.accounts.models import User
from .media_processing import compress_image_upload
from .models import Message
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
