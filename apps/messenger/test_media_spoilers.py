from io import BytesIO
from tempfile import TemporaryDirectory
from uuid import uuid4

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.accounts.models import User
from .models import Chat, ChatParticipant, Message, MessageAttachment
from .services import get_or_create_direct_chat


def picture():
    data = BytesIO()
    Image.new("RGB", (40, 30), "red").save(data, "PNG")
    return SimpleUploadedFile("photo.png", data.getvalue(), content_type="image/png")


class MediaSpoilerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("spoiler_alice", "alice@example.test", "Test-pass-1945!")
        cls.bob = User.objects.create_user("spoiler_bob", "bob@example.test", "Test-pass-1945!")
        cls.chat = get_or_create_direct_chat(cls.alice, cls.bob)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.alice)
        self.enterContext(override_settings(MEDIA_ROOT=self.enterContext(TemporaryDirectory())))
        self.url = reverse("messenger:send_message", args=[self.chat.pk])

    def send(self, **fields):
        return self.client.post(self.url, {"account_id":self.alice.pk,
            "client_message_id":str(uuid4()), "attachment_mode":"media",
            "attachments":picture(), **fields}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_spoiler_survives_history_gallery_forward_and_reload(self):
        response = self.send(media_spoiler="1")
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()["message"]
        attachment = MessageAttachment.objects.get(pk=data["attachments"][0]["id"])
        self.assertTrue(data["attachments"][0]["is_spoiler"])
        self.assertTrue(attachment.is_spoiler)
        self.client.force_login(self.bob)
        page = self.client.get(reverse("messenger:chat", args=[self.chat.pk]))
        self.assertContains(page, f'data-media-spoiler="{attachment.pk}"')
        gallery = self.client.get(reverse("messenger:chat_gallery", args=[self.chat.pk]),
                                  {"kind":"media", "account_id":self.bob.pk})
        self.assertEqual(gallery.status_code, 200, gallery.content)
        self.assertTrue(gallery.json()["items"][0]["is_spoiler"])
        history = self.client.get(reverse("messenger:message_history", args=[self.chat.pk]))
        self.assertTrue(history.json()["messages"][0]["attachments"][0]["is_spoiler"])
        target = Chat.objects.create(type=Chat.Type.GROUP, title="Forward target")
        ChatParticipant.objects.create(chat=target, user=self.bob, role="owner")
        result = self.client.post(reverse("messenger:forward_message", args=[self.chat.pk, attachment.message_id]),
            {"target_chat_id":target.pk}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(result.status_code, 200, result.content)
        self.assertTrue(MessageAttachment.objects.get(message__chat=target).is_spoiler)

    def test_default_and_reject_invalid_spoiler_modes(self):
        response = self.send()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(response.json()["message"]["attachments"][0]["is_spoiler"])
        self.assertEqual(self.send(media_spoiler="1", attachment_mode="file").status_code, 400)
        self.assertEqual(self.client.post(self.url, {"text":"Text", "media_spoiler":"1"},
                                         HTTP_X_REQUESTED_WITH="XMLHttpRequest").status_code, 400)
        self.assertEqual(Message.objects.count(), 1)
