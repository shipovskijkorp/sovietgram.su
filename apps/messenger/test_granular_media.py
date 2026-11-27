from io import BytesIO
from tempfile import TemporaryDirectory
from uuid import uuid4

from PIL import Image
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from .models import Chat, ChatParticipant, Message, ScheduledMessage, Sticker, StickerPack
from .scheduled import deliver_due_messages


class GranularMediaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("kindowner", "kindowner@example.net", "Password-1945!")
        cls.member = User.objects.create_user("kindmember", "kindmember@example.net", "Password-1945!")
        cls.chat = Chat.objects.create(type=Chat.Type.GROUP, title="Granular media")
        ChatParticipant.objects.create(chat=cls.chat, user=cls.owner, role="owner")
        ChatParticipant.objects.create(chat=cls.chat, user=cls.member)
        cls.pack = StickerPack.objects.create(owner=cls.member, name="Stickers")
        cls.sticker = Sticker.objects.create(pack=cls.pack, image=b"webp")

    def setUp(self):
        cache.clear()
        work = TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.enterContext(override_settings(MEDIA_ROOT=work.name))
        self.client.force_login(self.owner)
        self.settings_url = reverse("messenger:community_settings", args=[self.chat.pk])
        self.send_url = reverse("messenger:send_message", args=[self.chat.pk])

    def permissions(self, kinds=None, master="1"):
        import json
        data = {"section":"permissions", "send_messages":"1", "send_media":master,
                "send_links":"1", "history_visible":"1", "slow_mode_seconds":"0"}
        if kinds is not None:
            data["media_kinds"] = json.dumps(kinds)
        return self.client.post(self.settings_url, data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def send(self, **fields):
        return self.client.post(self.send_url, fields, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_independent_permissions_and_admin_bypass(self):
        self.assertEqual(self.permissions(["image"]).status_code, 200)
        self.assertEqual(self.permissions(["invalid"]).status_code, 400)
        self.assertEqual(self.permissions().status_code, 200)
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.members_allowed_media, ["image"])
        self.assertEqual(self.send(attachment_mode="file", attachments=SimpleUploadedFile("file.txt", b"owner")).status_code, 200)
        self.client.force_login(self.member)
        page = self.client.get(reverse("messenger:chat", args=[self.chat.pk]))
        self.assertNotContains(page, 'data-attachment-mode="file"')
        self.assertNotContains(page, 'data-sticker-send="true"')
        self.assertContains(page, 'data-attachment-mode="media"')
        self.assertEqual(self.send(attachment_mode="file", attachments=SimpleUploadedFile("file.txt", b"member")).status_code, 403)
        self.assertEqual(self.send(account_id=self.member.pk, sticker_id=self.sticker.pk).status_code, 403)
        image = BytesIO()
        Image.new("RGB", (20, 20), "red").save(image, "PNG")
        self.assertEqual(self.send(attachment_mode="media", attachments=SimpleUploadedFile("photo.png", image.getvalue(), content_type="image/png")).status_code, 200)
        self.assertEqual(self.send(text="Allowed text").status_code, 200)

    def test_scheduled_sticker_permission_rechecked(self):
        self.assertEqual(self.permissions(["sticker"]).status_code, 200)
        self.client.force_login(self.member)
        from datetime import timedelta
        url = reverse("messenger:scheduled_messages", args=[self.chat.pk])
        response = self.client.post(url, {
            "account_id":self.member.pk, "sticker_id":self.sticker.pk,
            "client_message_id":str(uuid4()), "scheduled_for":(timezone.now()+timedelta(minutes=10)).isoformat(),
        })
        self.assertEqual(response.status_code, 200, response.content)
        item = ScheduledMessage.objects.get(pk=response.json()["item"]["id"])
        Chat.objects.filter(pk=self.chat.pk).update(members_allowed_media=["image"])
        ScheduledMessage.objects.filter(pk=item.pk).update(next_attempt_at=timezone.now(), scheduled_for=timezone.now())
        self.assertEqual(deliver_due_messages(), 0)
        item.refresh_from_db()
        self.assertEqual(item.status, ScheduledMessage.Status.FAILED)
        self.assertFalse(Message.objects.filter(chat=self.chat).exists())
