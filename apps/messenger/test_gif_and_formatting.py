from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.accounts.models import User
from .forms import MessageForm
from .models import Message, MessageAttachment
from .services import get_or_create_direct_chat


def gif_bytes():
    buffer = BytesIO()
    Image.new("RGB", (12, 10), "red").save(
        buffer, format="GIF", save_all=True,
        append_images=[Image.new("RGB", (12, 10), "blue")],
        duration=[100, 150], loop=0,
    )
    return buffer.getvalue()


def gif_upload(content=None, name="animation.gif", mime="image/gif"):
    return SimpleUploadedFile(name, gif_bytes() if content is None else content, content_type=mime)


class GifAndFormattingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.com", "Password-1945!")
        cls.bob = User.objects.create_user("bob", "bob@example.com", "Password-1945!")
        cls.outsider = User.objects.create_user("outsider", "other@example.com", "Password-1945!")
        cls.chat = get_or_create_direct_chat(cls.alice, cls.bob)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.alice)
        media = TemporaryDirectory()
        self.addCleanup(media.cleanup)
        settings = override_settings(MEDIA_ROOT=media.name)
        settings.enable()
        self.addCleanup(settings.disable)

    def send(self, **data):
        return self.client.post(reverse("messenger:send_message", args=[self.chat.pk]),
                                data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_animated_gif_keeps_frames_and_original_bytes_inline(self):
        content = gif_bytes()
        response = self.send(attachment_mode="media", attachments=gif_upload(content))
        self.assertEqual(response.status_code, 200, response.content)
        item = response.json()["message"]["attachments"][0]
        self.assertEqual(item["kind"], "image")
        self.assertEqual(item["mime_type"], "image/gif")
        attachment = MessageAttachment.objects.get(pk=item["id"])
        self.assertEqual(attachment.kind, MessageAttachment.Kind.IMAGE)
        url = reverse("messenger:view_attachment", args=[attachment.pk])
        peer = Client()
        peer.force_login(self.bob)
        media = peer.get(url)
        self.assertEqual(media.status_code, 200)
        self.assertEqual(media["Content-Type"], "image/gif")
        received = b"".join(media.streaming_content)
        media.close()
        self.assertEqual(received, content)
        with Image.open(BytesIO(received)) as image:
            self.assertEqual(image.n_frames, 2)
        peer.force_login(self.outsider)
        self.assertEqual(peer.get(url).status_code, 404)

    def test_gif_document_mode_is_downloadable_not_inline(self):
        response = self.send(attachment_mode="file", attachments=gif_upload())
        self.assertEqual(response.status_code, 200, response.content)
        item = response.json()["message"]["attachments"][0]
        self.assertEqual(item["kind"], "file")
        inline = reverse("messenger:view_attachment", args=[item["id"]])
        self.assertEqual(self.client.get(inline).status_code, 404)
        download = self.client.get(reverse("messenger:download_attachment", args=[item["id"]]))
        self.assertEqual(download.status_code, 200)
        self.assertEqual(b"".join(download.streaming_content), gif_bytes())
        download.close()

    def test_invalid_and_mislabeled_gifs_are_rejected(self):
        png = BytesIO()
        Image.new("RGB", (12, 10), "blue").save(png, format="PNG")
        for upload in (
            gif_upload(b"GIF89a"),
            gif_upload(png.getvalue()),
            gif_upload(name="animation.png"),
            gif_upload(mime="image/png"),
        ):
            with self.subTest(name=upload.name, mime=upload.content_type):
                self.assertEqual(self.send(attachment_mode="media", attachments=upload).status_code, 400)
        self.assertFalse(Message.objects.filter(chat=self.chat).exists())

    def test_gif_decode_limits_cover_all_frames(self):
        for setting, limit in (("MAX_GIF_FRAMES", 1), ("MAX_GIF_TOTAL_PIXELS", 200),
                               ("MAX_GIF_FRAME_PIXELS", 100), ("MAX_GIF_DIMENSION", 8)):
            with self.subTest(setting=setting), patch("apps.messenger.forms."+setting, limit):
                form = MessageForm(
                    data={"attachment_mode": "media"},
                    files={"attachments": gif_upload()},
                )
                self.assertFalse(form.is_valid())
                self.assertIn("GIF слишком сложный", str(form.errors))
        form = MessageForm(data={"attachment_mode": "media"}, files={"attachments": gif_upload()})
        self.assertTrue(form.is_valid(), form.errors)

    def test_markup_and_unicode_round_trip_and_edit(self):
        raw = "**Привет** @bob ||спойлер|| __тест__ 😀"
        response = self.send(text=raw, attachment_mode="media")
        self.assertEqual(response.status_code, 200, response.content)
        item = response.json()["message"]
        self.assertEqual(item["text"], raw)
        self.assertEqual(Message.objects.get(pk=item["id"]).text, raw)
        new = "~~старое~~ *новое* ❤️"
        response = self.client.post(
            reverse("messenger:edit_message", args=[self.chat.pk, item["id"]]),
            {"text": new}, HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["message"]["text"], new)
        history = self.client.get(reverse("messenger:message_history", args=[self.chat.pk])).json()
        self.assertEqual(history["messages"][0]["text"], new)

    def test_editor_controls_and_gif_picker_present(self):
        page = self.client.get(reverse("messenger:chat", args=[self.chat.pk]))
        self.assertContains(page, 'data-compose-panel="format"')
        self.assertContains(page, 'data-compose-panel="emoji"')
        for target in ("messageInput", "mediaComposeCaption", "editMessageText"):
            self.assertContains(page, 'data-compose-target="%s"' % target)
        self.assertContains(page, "image/webp,image/gif,video/mp4")
        self.assertContains(page, "js/message-format.js")
        self.assertContains(page, "js/composer-tools.js")
