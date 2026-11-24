from datetime import timedelta
from io import BytesIO
from tempfile import TemporaryDirectory
from uuid import uuid4

from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.accounts.models import User
from .models import Chat, ChatAdminLog, ChatInviteLink, ChatJoinRequest, ChatParticipant, Message, Sticker, StickerPack
from .services import get_or_create_direct_chat
from .stickers import normalize_image


class StickerCollectionsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.net", "Password-1945!")
        cls.bob = User.objects.create_user("bob", "bob@example.net", "Password-1945!")
        cls.chat = get_or_create_direct_chat(cls.alice, cls.bob)
        cls.pack = StickerPack.objects.create(owner=cls.alice, name="Personal")
        image = BytesIO()
        Image.new("RGBA", (16, 16), (200, 20, 10, 200)).save(image, "PNG")
        data = normalize_image(image.getvalue())
        cls.first = Sticker.objects.create(pack=cls.pack, image=data)
        cls.second = Sticker.objects.create(pack=cls.pack, image=data)

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
        return self.client.post(self.url, {"action": action, "account_id": self.alice.pk, **fields})

    def send(self, sticker, key):
        return self.client.post(reverse("messenger:send_message", args=[self.chat.pk]), {
            "sticker_id": sticker.pk, "account_id": self.alice.pk, "client_message_id": key,
        }, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def ids(self, kind):
        return [item["id"] for item in self.client.get(self.url).json()[kind]]

    def test_favorites_are_idempotent_private_and_independent(self):
        for _ in range(2):
            self.assertEqual(self.action("favorite", sticker_id=self.first.pk, favorite="1").status_code, 200)
        self.assertEqual(self.ids("favorites"), [self.first.pk])
        self.assertEqual(self.ids("recent"), [])
        peer = Client()
        peer.force_login(self.bob)
        self.assertEqual(peer.get(self.url).json()["favorites"], [])
        self.assertEqual(peer.post(self.url, {"action": "favorite", "account_id": self.bob.pk,
                                             "sticker_id": self.first.pk, "favorite": "0"}).status_code, 404)
        self.assertEqual(self.action("favorite", sticker_id=self.first.pk, favorite="0").status_code, 200)
        self.assertEqual(self.ids("favorites"), [])
        self.assertTrue(Sticker.objects.filter(pk=self.first.pk).exists())

    def test_successful_sends_update_recent_order_but_retries_do_not(self):
        first_key = str(uuid4())
        response = self.send(self.first, first_key)
        self.assertEqual(response.status_code, 200, response.content)
        self.first.refresh_from_db()
        initial = self.first.last_used_at
        self.assertIsNotNone(initial)
        self.assertEqual(self.send(self.second, str(uuid4())).status_code, 200)
        self.assertEqual(self.ids("recent"), [self.second.pk, self.first.pk])
        self.assertTrue(self.send(self.first, first_key).json()["replayed"])
        self.first.refresh_from_db()
        self.assertEqual(self.first.last_used_at, initial)
        self.assertEqual(self.ids("recent"), [self.second.pk, self.first.pk])
        self.assertEqual(Message.objects.count(), 2)
        self.assertEqual(self.send(self.first, str(uuid4())).status_code, 200)
        self.assertEqual(self.ids("recent"), [self.first.pk, self.second.pk])

    def test_forget_clear_and_delete_keep_other_collections(self):
        Sticker.objects.filter(pack=self.pack).update(is_favorite=True, last_used_at=timezone.now())
        self.assertEqual(self.action("forget_recent", sticker_id=self.first.pk).status_code, 200)
        self.assertEqual(self.ids("recent"), [self.second.pk])
        self.assertEqual(set(self.ids("favorites")), {self.first.pk, self.second.pk})
        self.assertEqual(self.action("clear_recent").status_code, 200)
        self.assertEqual(self.ids("recent"), [])
        self.assertEqual(set(self.ids("favorites")), {self.first.pk, self.second.pk})
        self.assertEqual(self.action("remove", pack_id=self.pack.pk, sticker_id=self.first.pk).status_code, 200)
        self.assertEqual(self.ids("favorites"), [self.second.pk])


class JoinRequestTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("owner", "owner@example.net", "Password-1945!")
        cls.alice = User.objects.create_user("alice", "alice@example.net", "Password-1945!")
        cls.bob = User.objects.create_user("bob", "bob@example.net", "Password-1945!")
        cls.admin = User.objects.create_user("admin", "admin@example.net", "Password-1945!")
        cls.member = User.objects.create_user("member", "member@example.net", "Password-1945!")
        cls.chat = Chat.objects.create(type=Chat.Type.GROUP, title="Private", history_visible_to_new_members=False)
        ChatParticipant.objects.create(chat=cls.chat, user=cls.owner, role=ChatParticipant.Role.OWNER)
        ChatParticipant.objects.create(chat=cls.chat, user=cls.admin, role=ChatParticipant.Role.ADMIN)
        ChatParticipant.objects.create(chat=cls.chat, user=cls.member)
        cls.invite = ChatInviteLink.objects.create(chat=cls.chat, creator=cls.owner, token="approval-test",
                                                  requires_approval=True, usage_limit=1)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.alice)
        self.owner_client = Client()
        self.owner_client.force_login(self.owner)
        self.invite_url = reverse("messenger:join_invite", args=[self.invite.token])
        self.mine_url = reverse("messenger:my_join_requests")
        self.action_url = reverse("messenger:community_join_request_action", args=[self.chat.pk])
        self.chat_url = reverse("messenger:chat", args=[self.chat.pk])
        self.settings_url = reverse("messenger:community_settings", args=[self.chat.pk])

    def apply(self, client=None, user=None):
        client = client or self.client
        user = user or self.alice
        response = client.post(self.invite_url, {"account_id": user.pk})
        self.assertRedirects(response, self.mine_url)
        return ChatJoinRequest.objects.get(chat=self.chat, user=user)

    def decide(self, row, action="approve", client=None, actor=None, **fields):
        return (client or self.owner_client).post(self.action_url, {
            "account_id": (actor or self.owner).pk, "request_id": row.pk,
            "revision": row.created_at.isoformat(), "action": action, **fields,
        })

    def test_approval_required_no_history_until_decision_and_idempotent_usage(self):
        old = Message.objects.create(chat=self.chat, sender=self.owner, text="Old private history")
        self.assertContains(self.client.get(self.invite_url), "Отправить заявку")
        self.assertFalse(ChatJoinRequest.objects.exists())
        row = self.apply()
        self.assertEqual(self.apply().pk, row.pk)
        self.assertEqual(ChatJoinRequest.objects.count(), 1)
        self.assertEqual(self.client.get(self.chat_url).status_code, 404)
        self.assertEqual(self.client.get(reverse("messenger:message_history", args=[self.chat.pk])).status_code, 404)
        self.invite.refresh_from_db()
        self.assertEqual(self.invite.usage_count, 0)
        settings = self.owner_client.get(self.settings_url).json()["settings"]
        self.assertEqual(settings["pending_join_count"], 1)
        self.assertEqual(settings["join_requests"][0]["id"], row.pk)
        response = self.decide(row)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(self.decide(row).json()["replayed"])
        row.refresh_from_db()
        self.assertEqual(row.status, "approved")
        self.invite.refresh_from_db()
        self.assertEqual(self.invite.usage_count, 1)
        member = ChatParticipant.objects.get(chat=self.chat, user=self.alice)
        self.assertFalse(member.can_see_pre_join_history)
        self.assertNotContains(self.client.get(self.chat_url), old.text)
        self.assertContains(self.client.get(self.mine_url), "Одобрена")
        self.assertEqual(ChatAdminLog.objects.filter(action="join_request_approve").count(), 1)

    def test_only_admins_can_review_and_only_applicant_can_cancel(self):
        row = self.apply()
        ordinary = Client()
        ordinary.force_login(self.member)
        self.assertEqual(self.decide(row, client=ordinary, actor=self.member).status_code, 403)
        self.assertEqual(self.decide(row, client=self.client, actor=self.alice).status_code, 404)
        ordinary.post(self.mine_url, {"account_id": self.member.pk, "action": "cancel",
                                     "request_id": row.pk, "revision": row.created_at.isoformat()})
        row.refresh_from_db()
        self.assertEqual(row.status, "pending")
        self.client.post(self.mine_url, {"account_id": self.alice.pk, "action": "cancel",
                                        "request_id": row.pk, "revision": row.created_at.isoformat()})
        row.refresh_from_db()
        self.assertEqual(row.status, "canceled")
        self.assertEqual(self.decide(row).status_code, 409)
        new = self.apply()
        self.assertEqual(new.pk, row.pk)
        self.assertNotEqual(new.created_at, row.created_at)
        self.assertEqual(self.decide(row).status_code, 409)
        admin = Client()
        admin.force_login(self.admin)
        self.assertEqual(self.decide(new, client=admin, actor=self.admin).status_code, 200)

    def test_exhausted_or_expired_invites_cannot_approve_pending_requests(self):
        row = self.apply()
        peer = Client()
        peer.force_login(self.bob)
        second = self.apply(peer, self.bob)
        self.assertEqual(self.decide(row).status_code, 200)
        self.assertEqual(self.decide(second).status_code, 409)
        self.assertFalse(ChatParticipant.objects.filter(chat=self.chat, user=self.bob).exists())
        self.assertEqual(self.decide(second, "reject").status_code, 200)
        self.invite.refresh_from_db()
        self.assertEqual(self.invite.usage_count, 1)
        # An expired link is also unusable even if there is capacity.
        ChatInviteLink.objects.filter(pk=self.invite.pk).update(usage_limit=2, expires_at=timezone.now()-timedelta(seconds=1))
        ChatJoinRequest.objects.filter(pk=second.pk).update(status="pending")
        self.assertEqual(self.decide(second).status_code, 409)

    def test_revoke_rejects_pending_and_regular_links_remain_immediate(self):
        row = self.apply()
        url = reverse("messenger:community_invite_action", args=[self.chat.pk])
        response = self.owner_client.post(url, {"action": "revoke", "invite_id": self.invite.pk})
        self.assertEqual(response.status_code, 200)
        row.refresh_from_db()
        self.assertEqual(row.status, "rejected")
        self.assertEqual(self.decide(row).status_code, 409)
        response = self.owner_client.post(url, {"action": "create", "name": "Direct"})
        self.assertEqual(response.status_code, 200, response.content)
        direct = ChatInviteLink.objects.get(chat=self.chat, name="Direct")
        self.assertFalse(direct.requires_approval)
        self.assertRedirects(self.client.post(reverse("messenger:join_invite", args=[direct.token])), self.chat_url)
        self.assertTrue(ChatParticipant.objects.filter(chat=self.chat, user=self.alice).exists())

    def test_channel_invite_creation_and_join_request(self):
        channel = Chat.objects.create(type=Chat.Type.CHANNEL, title="News")
        ChatParticipant.objects.create(chat=channel, user=self.owner, role=ChatParticipant.Role.OWNER)
        response = self.owner_client.post(reverse("messenger:community_invite_action", args=[channel.pk]), {
            "action": "create", "name": "Moderated", "requires_approval": "1",
        })
        self.assertEqual(response.status_code, 200, response.content)
        invite = ChatInviteLink.objects.get(chat=channel)
        self.assertTrue(invite.requires_approval)
        self.assertRedirects(self.client.post(reverse("messenger:join_invite", args=[invite.token])), self.mine_url)
        self.assertFalse(ChatParticipant.objects.filter(chat=channel, user=self.alice).exists())
        row = ChatJoinRequest.objects.get(chat=channel, user=self.alice)
        response = self.owner_client.post(reverse("messenger:community_join_request_action", args=[channel.pk]), {
            "account_id": self.owner.pk, "action": "approve", "request_id": row.pk, "revision": row.created_at.isoformat(),
        })
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(ChatParticipant.objects.filter(chat=channel, user=self.alice).exists())
