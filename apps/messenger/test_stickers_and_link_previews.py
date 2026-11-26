from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.accounts.models import User
from .link_previews import Metadata, PreviewError, fetch_metadata, first_link, public_ipv4, safe_target
from .models import Chat, ChatParticipant, Message, MessageAttachment, Sticker, StickerPack
from .services import get_or_create_direct_chat
from .stickers import normalize_image


def image_bytes(size=(600, 300)):
    buffer = BytesIO()
    Image.new("RGBA", size, (200, 30, 50, 140)).save(buffer, format="PNG")
    return buffer.getvalue()


def animated_bytes(fmt="GIF", *, size=(64, 32), duration=120):
    buffer = BytesIO()
    frames = [Image.new("RGBA", size, color) for color in ("red", "blue")]
    frames[0].save(buffer, format=fmt, save_all=True, append_images=frames[1:],
                   duration=duration, loop=0)
    return buffer.getvalue()


class StickerImageTests(SimpleTestCase):
    def test_normalized_image_is_static_bounded_and_preserves_alpha(self):
        result = normalize_image(image_bytes())
        self.assertLessEqual(len(result), 256 * 1024)
        with Image.open(BytesIO(result)) as decoded:
            self.assertEqual(decoded.format, "WEBP")
            self.assertEqual(decoded.size, (512, 256))
            self.assertEqual(decoded.n_frames, 1)
            self.assertEqual(decoded.mode, "RGBA")

    def test_invalid_oversized_and_long_animations_are_rejected(self):
        for data in (b"<svg onload='alert(1)'/>", b"x" * (2 * 1024 * 1024 + 1),
                     animated_bytes("GIF", duration=3000)):
            with self.assertRaises(ValueError):
                normalize_image(data)
        frames = [Image.new("RGB", (4, 4), (i * 3, 20, 100)) for i in range(61)]
        buffer = BytesIO()
        frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:],
                       duration=30, loop=0)
        with self.assertRaisesMessage(ValueError, "60 кадров"):
            normalize_image(buffer.getvalue())
        with self.assertRaisesMessage(ValueError, "разрешение"):
            normalize_image(animated_bytes("PNG", size=(1025, 8)))

    def test_gif_apng_and_webp_keep_animation_and_bounded_size(self):
        for fmt in ("GIF", "PNG", "WEBP"):
            with self.subTest(fmt=fmt):
                result = normalize_image(animated_bytes(fmt))
                self.assertLessEqual(len(result), 256 * 1024)
                with Image.open(BytesIO(result)) as decoded:
                    self.assertEqual(decoded.format, "WEBP")
                    self.assertEqual(decoded.n_frames, 2)
                    self.assertEqual(decoded.size, (64, 32))
                    durations = []
                    for i in range(2):
                        decoded.seek(i)
                        decoded.load()
                        durations.append(decoded.info["duration"])
                    self.assertEqual(durations, [120, 120])
                    self.assertEqual(decoded.info["loop"], 0)
                # Saving a received animated WebP must not flatten it.
                with Image.open(BytesIO(normalize_image(result))) as saved:
                    self.assertEqual(saved.n_frames, 2)


class StickerLibraryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.net", "Password-1945!")
        cls.bob = User.objects.create_user("bob", "bob@example.net", "Password-1945!")
        cls.outsider = User.objects.create_user("outsider", "other@example.net", "Password-1945!")
        cls.chat = get_or_create_direct_chat(cls.alice, cls.bob)
        cls.pack = StickerPack.objects.create(owner=cls.alice, name="Personal")
        cls.sticker = Sticker.objects.create(pack=cls.pack, emoji="Hi", image=normalize_image(image_bytes()))

    def setUp(self):
        cache.clear()
        self.client.force_login(self.alice)
        self.url = reverse("messenger:sticker_packs")
        self.media = TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.override = override_settings(MEDIA_ROOT=self.media.name)
        self.override.enable()
        self.addCleanup(self.override.disable)

    def action(self, action, **fields):
        return self.client.post(self.url, {"account_id": self.alice.pk, "action": action, **fields})

    def send(self, **fields):
        return self.client.post(reverse("messenger:send_message", args=[self.chat.pk]), {
            "account_id": self.alice.pk, "sticker_id": self.sticker.pk, "client_message_id": str(uuid4()),
            **fields,
        }, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_crud_and_private_image_endpoint(self):
        response = self.action("create", name="New")
        self.assertEqual(response.status_code, 200, response.content)
        pack_id = response.json()["pack"]["id"]
        upload = SimpleUploadedFile("example.png", image_bytes(), content_type="image/png")
        response = self.action("add", pack_id=pack_id, image=upload, emoji="😀")
        self.assertEqual(response.status_code, 200, response.content)
        item = response.json()["pack"]["stickers"][0]
        image = self.client.get(item["url"])
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image["Content-Type"], "image/webp")
        self.assertEqual(self.action("rename", pack_id=pack_id, name="Renamed").status_code, 200)
        self.assertEqual(self.action("remove", pack_id=pack_id, sticker_id=item["id"]).status_code, 200)
        self.assertEqual(self.client.get(item["url"]).status_code, 404)
        self.assertEqual(self.action("delete", pack_id=pack_id).status_code, 200)
        peer = Client()
        peer.force_login(self.bob)
        self.assertEqual(peer.get(self.url).json()["packs"], [])
        self.assertEqual(peer.get(reverse("messenger:sticker_image", args=[self.sticker.pk])).status_code, 404)
        self.assertEqual(peer.post(self.url, {
            "account_id": self.bob.pk, "action": "delete", "pack_id": self.pack.pk,
        }).status_code, 404)

    def test_sticker_send_retry_copy_and_draft_preservation(self):
        ChatParticipant.objects.filter(chat=self.chat, user=self.alice).update(draft_text="Keep draft")
        key = str(uuid4())
        response = self.send(client_message_id=key, silent="1")
        self.assertEqual(response.status_code, 200, response.content)
        message = response.json()["message"]
        self.assertEqual(message["attachments"][0]["kind"], "sticker")
        self.assertTrue(message["silent"])
        self.assertTrue(self.send(client_message_id=key, silent="1").json()["replayed"])
        self.assertEqual(Message.objects.count(), 1)
        self.assertEqual(ChatParticipant.objects.get(chat=self.chat, user=self.alice).draft_text, "Keep draft")
        self.assertEqual(Message.objects.get().preview, "Стикер")
        url = message["attachments"][0]["url"]
        self.assertEqual(self.action("delete", pack_id=self.pack.pk).status_code, 200)
        peer = Client()
        peer.force_login(self.bob)
        self.assertEqual(peer.get(url).status_code, 200)
        self.assertContains(peer.get(reverse("messenger:chat", args=[self.chat.pk])), "message-sticker")
        outsider = Client()
        outsider.force_login(self.outsider)
        self.assertEqual(outsider.get(url).status_code, 404)

    def test_chat_sticker_dialog_has_explicit_send_endpoint(self):
        page = self.client.get(reverse("messenger:chat", args=[self.chat.pk]))
        self.assertContains(page, f'data-send-url="{reverse("messenger:send_message", args=[self.chat.pk])}"')
        self.assertContains(page, f'data-chat-id="{self.chat.pk}"')
        response = self.send(attachment_mode="media", reply_to="", silent="1")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["message"]["attachments"][0]["kind"], "sticker")

    def test_save_received_sticker_and_protected_chat(self):
        response = self.send()
        self.assertEqual(response.status_code, 200, response.content)
        attachment = MessageAttachment.objects.get()
        pack = StickerPack.objects.create(owner=self.bob, name="Received")
        peer = Client()
        peer.force_login(self.bob)
        fields = {"account_id": self.bob.pk, "action": "save_message", "pack_id": pack.pk, "attachment_id": attachment.pk}
        self.assertEqual(peer.post(self.url, fields).status_code, 200)
        self.assertEqual(pack.stickers.count(), 1)
        Chat.objects.filter(pk=self.chat.pk).update(protect_content=True)
        self.assertEqual(peer.post(self.url, fields).status_code, 403)
        self.assertEqual(pack.stickers.count(), 1)

    def test_animated_sticker_is_sent_and_saved_without_flattening(self):
        uploaded = SimpleUploadedFile("animated.gif", animated_bytes("GIF"), content_type="image/gif")
        response = self.action("add", pack_id=self.pack.pk, image=uploaded, emoji="🎉")
        self.assertEqual(response.status_code, 200, response.content)
        item = self.pack.stickers.exclude(pk=self.sticker.pk).get()
        with Image.open(BytesIO(bytes(item.image))) as image:
            self.assertEqual(image.n_frames, 2)
        sent = self.send(sticker_id=item.pk)
        self.assertEqual(sent.status_code, 200, sent.content)
        attachment = MessageAttachment.objects.get()
        with attachment.file.open("rb") as source:
            with Image.open(source) as image:
                self.assertEqual(image.n_frames, 2)
        other = StickerPack.objects.create(owner=self.bob, name="Saved")
        peer = Client()
        peer.force_login(self.bob)
        result = peer.post(self.url, {"account_id":self.bob.pk, "action":"save_message",
            "pack_id":other.pk, "attachment_id":attachment.pk})
        self.assertEqual(result.status_code, 200, result.content)
        with Image.open(BytesIO(bytes(other.stickers.get().image))) as image:
            self.assertEqual(image.n_frames, 2)

    def test_sticker_cannot_be_combined_with_text_or_sent_from_wrong_account(self):
        self.assertEqual(self.send(text="Caption").status_code, 400)
        self.assertEqual(self.send(account_id=self.bob.pk).status_code, 409)
        self.client.force_login(self.bob)
        self.assertEqual(self.send(account_id=self.bob.pk).status_code, 404)
        self.assertFalse(Message.objects.exists())

    def test_stickers_respect_media_permission_and_cannot_be_edited(self):
        group = Chat.objects.create(type=Chat.Type.GROUP, title="Restricted", members_can_send_media=False)
        ChatParticipant.objects.create(chat=group, user=self.bob, role=ChatParticipant.Role.OWNER)
        ChatParticipant.objects.create(chat=group, user=self.alice)
        response = self.client.post(reverse("messenger:send_message", args=[group.pk]), {
            "account_id": self.alice.pk, "sticker_id": self.sticker.pk,
        }, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 403)
        sent = self.send()
        self.assertEqual(sent.status_code, 200, sent.content)
        response = self.client.post(reverse("messenger:edit_message", args=[self.chat.pk, sent.json()["message"]["id"]]), {"text": "change"})
        self.assertEqual(response.status_code, 400)


class LinkPreviewSafetyTests(SimpleTestCase):
    def test_reject_private_special_and_ambiguous_targets(self):
        for address in ("127.0.0.1", "10.1.2.3", "169.254.169.254", "192.168.1.1",
                        "100.64.0.1", "224.0.0.1", "168.63.129.16", "198.18.1.1", "::1"):
            self.assertFalse(public_ipv4(address))
        self.assertTrue(public_ipv4("93.184.216.34"))
        for url in ("file:///etc/passwd", "http://localhost/", "http://127.0.0.1/", "http://[::1]/",
                    "https://user:pass@example.org/", "https://example.org:8443/", "https://test.internal/"):
            with self.subTest(url=url), self.assertRaises(PreviewError):
                safe_target(url)

    @patch("apps.messenger.link_previews.socket.getaddrinfo")
    def test_dns_mixed_answers_rejected_and_public_target_pinned(self, dns):
        dns.return_value = [(2, 1, 6, "", ("93.184.216.34", 443)), (2, 1, 6, "", ("127.0.0.1", 443))]
        with self.assertRaises(PreviewError):
            safe_target("https://example.org/page")
        dns.return_value = dns.return_value[:1]
        self.assertEqual(safe_target("https://example.org/page?q=a#fragment"),
                         ("https", "example.org", 443, "93.184.216.34", "/page?q=a"))

    def test_only_rendered_markdown_links_are_selected_and_metadata_is_plain_text(self):
        code = chr(96) + "https://example.net" + chr(96)
        self.assertEqual(first_link(code + " [Example](https://example.org)"), "https://example.org")
        self.assertEqual(first_link(code), "")
        parser = Metadata()
        parser.feed('<title>Fallback</title><meta property="og:title" content="Hello &amp; world">'
                    '<meta property="og:description" content="Test &lt;script&gt;">')
        self.assertEqual(parser.result()["title"], "Hello & world")
        self.assertEqual(parser.result()["description"], "Test <script>")

    @patch("apps.messenger.link_previews.socket.create_connection")
    @patch("apps.messenger.link_previews.http.client.HTTPSConnection")
    @patch("apps.messenger.link_previews.socket.getaddrinfo")
    def test_redirect_to_private_ip_is_rejected_and_connection_uses_pinned_address(self, dns, https, connect):
        dns.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
        connection = https.return_value
        connection.getresponse.return_value.status = 302
        connection.getresponse.return_value.getheader.return_value = "http://127.0.0.1/"
        with self.assertRaises(PreviewError):
            fetch_metadata("https://example.org")
        connection._create_connection(("example.org", 443), 3, None)
        connect.assert_called_once_with(("93.184.216.34", 443), 3, None)
        self.assertEqual(https.call_count, 1)
        self.assertTrue(connection.close.called)


class LinkPreviewAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.net", "Password-1945!")
        cls.bob = User.objects.create_user("bob", "bob@example.net", "Password-1945!")
        cls.outsider = User.objects.create_user("outsider", "other@example.net", "Password-1945!")
        cls.chat = get_or_create_direct_chat(cls.alice, cls.bob)
        cls.message = Message.objects.create(chat=cls.chat, sender=cls.bob, text="[Example](https://example.org/page)")

    def setUp(self):
        cache.clear()
        self.client.force_login(self.alice)
        self.url = reverse("messenger:link_preview", args=[self.chat.pk])
        self.data = {"account_id": self.alice.pk, "message_id": self.message.pk, "url": "https://example.org/page"}

    @patch("apps.messenger.link_previews.fetch_metadata")
    def test_preview_is_opt_in_cached_and_bound_to_visible_message(self, fetch):
        fetch.return_value = {"title": "Example", "description": "Description", "site_name": "", "domain": "example.org"}
        self.client.get(reverse("messenger:chat", args=[self.chat.pk]))
        fetch.assert_not_called()
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertEqual(self.client.post(self.url, {**self.data, "url": "https://different.org/"}).status_code, 400)
        fetch.assert_not_called()
        for _ in range(2):
            response = self.client.post(self.url, self.data)
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response.json()["preview"]["title"], "Example")
            self.assertIn("no-store", response["Cache-Control"])
        fetch.assert_called_once_with(self.data["url"])
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.post(self.url, {**self.data, "account_id": self.outsider.pk}).status_code, 404)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.alice)
        self.assertEqual(csrf.post(self.url, self.data).status_code, 403)
