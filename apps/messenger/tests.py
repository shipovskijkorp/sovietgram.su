import base64
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User

from .models import Chat, Contact, Message, MessageAttachment
from .services import get_or_create_direct_chat


VALID_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class MessengerTests(TestCase):
    password = "Stalingram-test-1945"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media_dir = tempfile.TemporaryDirectory()
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_dir.name)
        cls._media_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._media_override.disable()
        cls._media_dir.cleanup()
        super().tearDownClass()

    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice",
            email="alice@example.com",
            password=self.password,
        )
        self.bob = User.objects.create_user(
            username="bob",
            email="bob@example.com",
            password=self.password,
        )
        self.charlie = User.objects.create_user(
            username="charlie",
            email="charlie@example.com",
            password=self.password,
        )
        self.client.force_login(self.alice)

    def test_contact_search_uses_username_only(self):
        self.bob.first_name = "Needle"
        self.bob.save(update_fields=["first_name"])
        User.objects.create_user(
            username="needle_user",
            email="other@example.com",
            password=self.password,
        )

        response = self.client.get(reverse("messenger:contacts"), {"q": "needle"})

        self.assertContains(response, "@needle_user")
        self.assertNotContains(response, "@bob")

    def test_contact_can_be_added_and_removed(self):
        add_url = reverse("messenger:add_contact", args=[self.bob.username])
        remove_url = reverse("messenger:remove_contact", args=[self.bob.username])

        self.client.post(add_url)
        self.assertTrue(Contact.objects.filter(owner=self.alice, user=self.bob).exists())

        self.client.post(remove_url)
        self.assertFalse(Contact.objects.filter(owner=self.alice, user=self.bob).exists())

    def test_starting_same_direct_chat_does_not_duplicate_it(self):
        url = reverse("messenger:start_chat", args=[self.bob.username])
        first = self.client.post(url)
        second = self.client.post(url)

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(Chat.objects.count(), 1)
        self.assertEqual(Chat.objects.first().participants.count(), 2)

    def test_only_participants_can_open_chat(self):
        chat = get_or_create_direct_chat(self.bob, self.charlie)
        response = self.client.get(reverse("messenger:chat", args=[chat.pk]))
        self.assertEqual(response.status_code, 404)

    def test_text_message_is_saved(self):
        chat = get_or_create_direct_chat(self.alice, self.bob)
        response = self.client.post(
            reverse("messenger:send_message", args=[chat.pk]),
            {"text": "Привет, товарищ."},
        )

        self.assertRedirects(response, reverse("messenger:chat", args=[chat.pk]))
        message = Message.objects.get()
        self.assertEqual(message.sender, self.alice)
        self.assertEqual(message.text, "Привет, товарищ.")

    def test_media_message_is_saved(self):
        chat = get_or_create_direct_chat(self.alice, self.bob)
        upload = SimpleUploadedFile(
            "photo.png",
            VALID_PNG,
            content_type="image/png",
        )
        response = self.client.post(
            reverse("messenger:send_message", args=[chat.pk]),
            {"text": "Подпись", "attachment_mode": "media", "attachments": upload},
        )

        self.assertRedirects(response, reverse("messenger:chat", args=[chat.pk]))
        attachment = MessageAttachment.objects.get()
        self.assertEqual(attachment.kind, MessageAttachment.Kind.IMAGE)
        self.assertEqual(attachment.original_name, "photo.png")
        self.assertEqual(attachment.message.text, "Подпись")

    def test_media_can_be_sent_as_file_without_inline_rendering(self):
        chat = get_or_create_direct_chat(self.alice, self.bob)
        upload = SimpleUploadedFile(
            "original.png",
            b"original-file-content",
            content_type="image/png",
        )
        response = self.client.post(
            reverse("messenger:send_message", args=[chat.pk]),
            {"attachment_mode": "file", "attachments": upload},
        )

        self.assertRedirects(response, reverse("messenger:chat", args=[chat.pk]))
        attachment = MessageAttachment.objects.get()
        self.assertEqual(attachment.kind, MessageAttachment.Kind.FILE)
        self.assertEqual(attachment.original_name, "original.png")

    def test_audio_is_rejected_in_media_mode_and_allowed_as_file(self):
        chat = get_or_create_direct_chat(self.alice, self.bob)
        media_upload = SimpleUploadedFile(
            "track.mp3",
            b"audio",
            content_type="audio/mpeg",
        )
        response = self.client.post(
            reverse("messenger:send_message", args=[chat.pk]),
            {"attachment_mode": "media", "attachments": media_upload},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Message.objects.exists())

        file_upload = SimpleUploadedFile(
            "track.mp3",
            b"audio",
            content_type="audio/mpeg",
        )
        response = self.client.post(
            reverse("messenger:send_message", args=[chat.pk]),
            {"attachment_mode": "file", "attachments": file_upload},
        )
        self.assertRedirects(response, reverse("messenger:chat", args=[chat.pk]))
        self.assertEqual(MessageAttachment.objects.get().kind, MessageAttachment.Kind.FILE)

    def test_empty_message_is_rejected(self):
        chat = get_or_create_direct_chat(self.alice, self.bob)
        response = self.client.post(
            reverse("messenger:send_message", args=[chat.pk]),
            {"text": "   "},
        )
        self.assertRedirects(response, reverse("messenger:chat", args=[chat.pk]))
        self.assertFalse(Message.objects.exists())

    def test_poll_returns_new_messages_and_marks_them_read(self):
        chat = get_or_create_direct_chat(self.alice, self.bob)
        message = Message.objects.create(chat=chat, sender=self.bob, text="Новое сообщение")

        response = self.client.get(
            reverse("messenger:poll_messages", args=[chat.pk]),
            {"after": 0},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["messages"][0]["id"], message.pk)
        membership = chat.memberships.get(user=self.alice)
        self.assertEqual(membership.last_read_message_id, message.pk)
