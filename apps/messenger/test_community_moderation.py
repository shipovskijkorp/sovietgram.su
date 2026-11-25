import json
from datetime import timedelta
from uuid import uuid4

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from .community_permissions import ADMIN_RIGHTS
from .models import Chat, ChatAdminLog, ChatInviteLink, ChatJoinRequest, ChatMemberModeration, ChatParticipant, Message, ScheduledMessage
from .scheduled import deliver_due_messages


class CommunityModerationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("owner", "owner@example.net", "Password-1945!")
        cls.admin = User.objects.create_user("admin", "admin@example.net", "Password-1945!")
        cls.member = User.objects.create_user("member", "member@example.net", "Password-1945!")
        cls.peer = User.objects.create_user("peer", "peer@example.net", "Password-1945!")
        cls.outsider = User.objects.create_user("outsider", "outsider@example.net", "Password-1945!")
        cls.chat = Chat.objects.create(type=Chat.Type.GROUP, title="Group", username="moderation_group",
                                       members_can_add_members=True, members_can_pin_messages=True)
        for user, role in ((cls.owner, "owner"), (cls.admin, "admin"), (cls.member, "member"), (cls.peer, "member")):
            ChatParticipant.objects.create(chat=cls.chat, user=user, role=role)
        cls.invite = ChatInviteLink.objects.create(chat=cls.chat, creator=cls.owner, token="moderation-direct")

    def setUp(self):
        cache.clear()
        self.clients = {}
        for user in (self.owner, self.admin, self.member, self.peer, self.outsider):
            client = Client()
            client.force_login(user)
            self.clients[user.pk] = client

    def client_for(self, user):
        return self.clients[user.pk]

    def call(self, actor, action, target, chat=None, **fields):
        chat = chat or self.chat
        return self.client_for(actor).post(reverse("messenger:community_moderation", args=[chat.pk]), {
            "account_id": actor.pk, "action": action, "user_id": target.pk,
            "permissions": "[]", "duration": "1h", **fields,
        }, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def rights(self, rights, chat=None):
        response = self.call(self.owner, "admin_rights", self.admin, chat=chat, permissions=json.dumps(rights))
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def send(self, user, text, chat=None, **fields):
        return self.client_for(user).post(reverse("messenger:send_message", args=[(chat or self.chat).pk]),
                                          {"text": text, **fields}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_legacy_admin_and_granular_permissions(self):
        url = reverse("messenger:community_settings", args=[self.chat.pk])
        client = self.client_for(self.admin)
        self.assertEqual(set(client.get(url).json()["settings"]["admin_rights"]), set(ADMIN_RIGHTS))
        self.rights(["delete_messages"])
        payload = client.get(url).json()["settings"]
        self.assertEqual(payload["admin_rights"], ["delete_messages"])
        self.assertEqual(payload["invite_links"], [])
        self.assertFalse(payload["can_add_members"])
        self.assertEqual(client.post(url, {"section": "permissions"}).status_code, 403)
        self.assertEqual(client.post(reverse("messenger:community_profile_update", args=[self.chat.pk]),
                                     {"title": "Changed"}).status_code, 403)
        self.assertEqual(client.post(reverse("messenger:community_invite_action", args=[self.chat.pk]),
                                     {"action": "create"}).status_code, 403)
        self.assertEqual(client.post(reverse("messenger:community_member_action", args=[self.chat.pk]),
                                     {"action": "add", "username": self.outsider.username}).status_code, 403)
        msg = Message.objects.create(chat=self.chat, sender=self.peer, text="message")
        self.assertEqual(client.post(reverse("messenger:pin_message", args=[self.chat.pk, msg.pk])).status_code, 403)
        self.assertEqual(client.post(reverse("messenger:delete_message", args=[self.chat.pk, msg.pk]),
                                     {"scope": "everyone"}).status_code, 200)
        msg.refresh_from_db()
        self.assertTrue(msg.is_deleted)
        self.assertEqual(self.call(self.admin, "ban", self.member).status_code, 403)
        self.rights([])
        another = Message.objects.create(chat=self.chat, sender=self.peer, text="other")
        self.assertEqual(client.post(reverse("messenger:delete_message", args=[self.chat.pk, another.pk]),
                                     {"scope": "everyone"}).status_code, 403)

    def test_channel_post_permission_is_separate(self):
        channel = Chat.objects.create(type=Chat.Type.CHANNEL, title="News")
        ChatParticipant.objects.create(chat=channel, user=self.owner, role="owner")
        ChatParticipant.objects.create(chat=channel, user=self.admin, role="admin")
        self.rights(["pin_messages"], channel)
        self.assertEqual(self.send(self.admin, "Denied", channel).status_code, 403)
        self.rights(["post_messages"], channel)
        response = self.send(self.admin, "Allowed", channel)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(Message.objects.filter(chat=channel).count(), 1)

    def test_role_hierarchy_and_invalid_permissions(self):
        self.assertEqual(self.call(self.admin, "admin_rights", self.admin, permissions='["post_messages"]').status_code, 403)
        self.assertEqual(self.call(self.owner, "admin_rights", self.admin, permissions='["owner"]').status_code, 400)
        self.assertEqual(self.call(self.admin, "ban", self.owner).status_code, 403)
        self.assertEqual(self.call(self.admin, "ban", self.admin).status_code, 403)
        self.assertEqual(self.call(self.member, "ban", self.peer).status_code, 403)
        self.assertEqual(self.call(self.owner, "ban", self.member, duration="invalid").status_code, 400)
        self.assertEqual(self.call(self.owner, "ban", self.member, account_id=self.admin.pk).status_code, 409)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.owner)
        self.assertEqual(csrf.post(reverse("messenger:community_moderation", args=[self.chat.pk]), {
            "account_id": self.owner.pk, "user_id": self.member.pk, "action": "ban",
        }).status_code, 403)
        self.assertFalse(ChatMemberModeration.objects.exists())

    def test_ban_blocks_all_join_paths_and_keeps_history(self):
        old = Message.objects.create(chat=self.chat, sender=self.member, text="History stays")
        response = self.call(self.admin, "ban", self.member, duration="forever", reason="Spam")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(ChatParticipant.objects.filter(chat=self.chat, user=self.member).exists())
        self.assertTrue(Message.objects.filter(pk=old.pk, is_deleted=False).exists())
        row = ChatMemberModeration.objects.get(chat=self.chat, user=self.member)
        self.assertTrue(row.banned)
        self.assertEqual(row.reason, "Spam")
        self.assertIsNone(row.expires_at)
        self.assertEqual(response.json()["settings"]["moderation"][0]["user_id"], self.member.pk)
        target = self.client_for(self.member)
        self.assertEqual(target.get(reverse("messenger:chat", args=[self.chat.pk])).status_code, 404)
        self.assertEqual(self.send(self.member, "Denied").status_code, 404)
        self.assertRedirects(target.post(reverse("messenger:join_public_chat", args=[self.chat.username])),
                             reverse("messenger:home"))
        self.assertRedirects(target.post(reverse("messenger:join_invite", args=[self.invite.token])),
                             reverse("messenger:home"))
        added = self.client_for(self.owner).post(reverse("messenger:community_member_action", args=[self.chat.pk]),
                                                {"action": "add", "username": self.member.username})
        self.assertEqual(added.status_code, 403)
        moderated = ChatInviteLink.objects.create(chat=self.chat, creator=self.owner, token="moderation-approval", requires_approval=True)
        self.assertRedirects(target.post(reverse("messenger:join_invite", args=[moderated.token])),
                             reverse("messenger:home"))
        self.assertFalse(ChatJoinRequest.objects.filter(chat=self.chat, user=self.member).exists())
        self.assertFalse(ChatParticipant.objects.filter(chat=self.chat, user=self.member).exists())
        self.assertEqual(self.call(self.admin, "lift", self.member).status_code, 200)
        self.assertFalse(ChatParticipant.objects.filter(chat=self.chat, user=self.member).exists())
        self.assertRedirects(target.post(reverse("messenger:join_invite", args=[self.invite.token])),
                             reverse("messenger:chat", args=[self.chat.pk]))
        self.assertTrue(ChatParticipant.objects.filter(chat=self.chat, user=self.member).exists())
        self.assertTrue(ChatAdminLog.objects.filter(chat=self.chat, action="member_ban").exists())

    def test_temporary_ban_expiry(self):
        response = self.call(self.owner, "ban", self.member, duration="1h")
        self.assertEqual(response.status_code, 200, response.content)
        row = ChatMemberModeration.objects.get(chat=self.chat, user=self.member)
        self.assertGreater(row.expires_at, timezone.now())
        ChatMemberModeration.objects.filter(pk=row.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertRedirects(self.client_for(self.member).post(reverse("messenger:join_public_chat", args=[self.chat.username])),
                             reverse("messenger:chat", args=[self.chat.pk]))
        settings = self.client_for(self.owner).get(reverse("messenger:community_settings", args=[self.chat.pk])).json()["settings"]
        self.assertEqual(settings["moderation_count"], 0)

    def test_restrictions_apply_to_send_forward_edit_pin_and_add(self):
        old = Message.objects.create(chat=self.chat, sender=self.member, text="Old")
        denied = ["send_text", "send_media", "send_links", "add_members", "pin_messages"]
        response = self.call(self.admin, "restrict", self.member, permissions=json.dumps(denied), duration="1d")
        self.assertEqual(response.status_code, 200, response.content)
        target = self.client_for(self.member)
        self.assertEqual(self.send(self.member, "Text").status_code, 403)
        self.assertEqual(self.send(self.member, "", attachment_mode="file",
                                   attachments=SimpleUploadedFile("test.txt", b"test")).status_code, 403)
        self.assertEqual(target.post(reverse("messenger:send_special_message", args=[self.chat.pk]), {
            "special_type": "poll", "payload": json.dumps({"question": "Test", "options": ["Yes", "No"]}),
        }).status_code, 403)
        self.assertEqual(target.post(reverse("messenger:edit_message", args=[self.chat.pk, old.pk]), {"text": "Edit"}).status_code, 403)
        self.assertEqual(target.post(reverse("messenger:pin_message", args=[self.chat.pk, old.pk])).status_code, 403)
        self.assertEqual(target.post(reverse("messenger:community_member_action", args=[self.chat.pk]),
                                     {"action": "add", "username": self.outsider.username}).status_code, 403)
        self.assertEqual(target.post(reverse("messenger:forward_message", args=[self.chat.pk, old.pk]),
                                     {"target_chat_id": self.chat.pk}).status_code, 403)
        # Leaving and rejoining must not clear an unexpired sanction.
        self.assertEqual(target.post(reverse("messenger:community_profile_action", args=[self.chat.pk]),
                                     {"action": "leave"}).status_code, 200)
        self.assertRedirects(target.post(reverse("messenger:join_public_chat", args=[self.chat.username])),
                             reverse("messenger:chat", args=[self.chat.pk]))
        self.assertEqual(self.send(self.member, "Still denied").status_code, 403)
        self.assertEqual(self.call(self.owner, "restrict", self.member, permissions='["send_links"]').status_code, 200)
        self.assertEqual(self.send(self.member, "https://example.com").status_code, 403)
        self.assertEqual(self.send(self.member, "Plain text").status_code, 200)
        self.assertEqual(self.call(self.admin, "lift", self.member).status_code, 200)
        self.assertEqual(self.send(self.member, "https://example.com").status_code, 200)

    def test_scheduled_delivery_rechecks_current_restrictions(self):
        target = self.client_for(self.member)
        response = target.post(reverse("messenger:scheduled_messages", args=[self.chat.pk]), {
            "account_id": self.member.pk, "client_message_id": str(uuid4()), "text": "Future",
            "scheduled_for": (timezone.now()+timedelta(minutes=5)).isoformat(),
        })
        self.assertEqual(response.status_code, 200, response.content)
        item = ScheduledMessage.objects.get(pk=response.json()["item"]["id"])
        self.assertEqual(self.call(self.admin, "restrict", self.member, permissions='["send_text"]').status_code, 200)
        ScheduledMessage.objects.filter(pk=item.pk).update(next_attempt_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(deliver_due_messages(), 0)
        item.refresh_from_db()
        self.assertEqual(item.status, ScheduledMessage.Status.FAILED)
        self.assertFalse(Message.objects.filter(chat=self.chat, text="Future").exists())

    def test_sanctions_are_local_and_owner_can_ban_admin(self):
        other = Chat.objects.create(type=Chat.Type.GROUP, title="Other")
        ChatParticipant.objects.create(chat=other, user=self.owner, role="owner")
        ChatParticipant.objects.create(chat=other, user=self.member, role="member")
        self.assertEqual(self.call(self.owner, "ban", self.member).status_code, 200)
        self.assertEqual(self.send(self.member, "Other works", other).status_code, 200)
        self.assertEqual(self.call(self.owner, "ban", self.admin).status_code, 200)
        self.assertFalse(ChatParticipant.objects.filter(chat=self.chat, user=self.admin).exists())
        self.assertEqual(self.client_for(self.admin).get(reverse("messenger:community_settings", args=[self.chat.pk])).status_code, 404)
