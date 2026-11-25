from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from .models import Chat, ChatParticipant, Message, MessageAttachment, MessageHiddenForUser


class MediaGalleryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("gallery_alice", "alice@example.net", "Password-1945!")
        cls.bob = User.objects.create_user("gallery_bob", "bob@example.net", "Password-1945!")
        cls.group = Chat.objects.create(type=Chat.Type.GROUP, title="Gallery")
        cls.member = ChatParticipant.objects.create(chat=cls.group, user=cls.alice, role="owner")
        ChatParticipant.objects.create(chat=cls.group, user=cls.bob, role="member")

    def setUp(self):
        self.client.force_login(self.alice)
        self.url = reverse("messenger:chat_gallery", args=[self.group.pk])
        self.profile_url = reverse("messenger:community_profile", args=[self.group.pk])

    def attachment(self, kind="image", **kwargs):
        msg = Message.objects.create(chat=self.group, sender=self.bob, **kwargs)
        return MessageAttachment.objects.create(
            message=msg, kind=kind, original_name=f"{kind}-{msg.pk}.png",
            file=f"test/{msg.pk}.png", size=123,
        )

    def test_counts_pagination_and_categories(self):
        media = [self.attachment() for _ in range(45)]
        file = self.attachment("file")
        self.attachment("audio")
        self.attachment("voice")
        self.attachment("sticker")
        first = self.client.get(self.url).json()
        self.assertEqual(first["counts"], {"media":45,"files":1,"audio":1,"voice":1,"stickers":1})
        self.assertEqual(len(first["items"]), 40)
        self.attachment()
        second = self.client.get(self.url, {"before":first["next_before"]}).json()
        self.assertEqual([row["id"] for row in first["items"]+second["items"]], [row.pk for row in reversed(media)])
        self.assertIsNone(second["next_before"])
        self.assertEqual(self.client.get(self.url, {"kind":"files"}).json()["items"][0]["id"], file.pk)
        self.assertEqual(self.client.get(self.url, {"kind":"bad"}).status_code, 400)
        self.assertEqual(self.client.get(self.url, {"before":"-1"}).status_code, 400)
        self.assertEqual(self.client.get(self.url, {"account_id":self.bob.pk}).status_code, 409)

    def test_gallery_and_profile_exclude_hidden_cleared_expired_deleted_and_prejoin(self):
        cleared = self.attachment()
        ChatParticipant.objects.filter(pk=self.member.pk).update(cleared_before_message_id=cleared.message_id)
        prejoin = self.attachment()
        Message.objects.filter(pk=prejoin.message_id).update(created_at=timezone.now()-timedelta(days=2))
        self.group.history_visible_to_new_members = False
        self.group.save(update_fields=["history_visible_to_new_members"])
        ChatParticipant.objects.filter(pk=self.member.pk).update(can_see_pre_join_history=False)
        hidden = self.attachment()
        MessageHiddenForUser.objects.create(message=hidden.message, user=self.alice)
        expired = self.attachment(expires_at=timezone.now()-timedelta(seconds=10))
        self.attachment(is_deleted=True)
        visible = self.attachment()
        for result in (self.client.get(self.url).json()["items"], self.client.get(self.profile_url).json()["profile"]["attachments"]):
            self.assertEqual([item["id"] for item in result], [visible.pk])
        self.assertEqual(self.client.get(reverse("messenger:view_attachment", args=[expired.pk])).status_code, 404)

    def test_protection_and_access(self):
        item = self.attachment()
        self.group.protect_content = True
        self.group.save(update_fields=["protect_content"])
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response.json()["items"][0]["download_url"], "")
        self.assertEqual(self.client.get(reverse("messenger:download_attachment", args=[item.pk])).status_code, 403)
        outsider = User.objects.create_user("outsider", "out@example.net", "Password-1945!")
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(self.url).status_code, 404)
