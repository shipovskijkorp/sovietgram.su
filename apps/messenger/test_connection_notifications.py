from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User, UserBlock
from .markdown import mentioned_usernames
from .models import Chat, ChatParticipant, Message
from .services import get_or_create_direct_chat


class ConnectionNotificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.net", "Password-1945!")
        cls.bob = User.objects.create_user("bob", "bob@example.net", "Password-1945!")
        cls.chat = get_or_create_direct_chat(cls.alice, cls.bob)
        cls.group = Chat.objects.create(type=Chat.Type.GROUP, title="Group")
        for user in (cls.alice, cls.bob):
            ChatParticipant.objects.create(chat=cls.group, user=user, role="member")

    def setUp(self):
        cache.clear()
        self.client.force_login(self.alice)

    def test_notifications_supply_only_safe_routing_metadata(self):
        message = Message.objects.create(chat=self.chat, sender=self.bob, text="private contents")
        Message.objects.create(chat=self.chat,sender=self.bob,text="silent",silent=True)
        response = self.client.get(reverse("messenger:poll_sound_notifications"),
                                   {"since":(timezone.now()-timedelta(seconds=10)).isoformat()})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()["items"],[{"id":message.pk,"chat_id":self.chat.pk,"kind":"message"}])
        self.assertNotContains(response,"private contents")
        self.assertEqual(self.client.get(reverse("accounts:presence_heartbeat")).json()["account_id"],self.alice.pk)
        self.assertEqual(self.client.get(reverse("messenger:poll_sound_notifications"), {"account_id": self.bob.pk}).status_code,409)

    def test_background_notification_poll_does_not_touch_presence(self):
        previous = timezone.now()-timedelta(minutes=5)
        User.objects.filter(pk=self.alice.pk).update(last_seen_at=previous)
        self.client.get(reverse("messenger:poll_sound_notifications"))
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.last_seen_at, previous)

    def test_group_typing_respects_expiry_and_blocking(self):
        member = ChatParticipant.objects.get(chat=self.group,user=self.bob)
        member.last_typing_at = timezone.now()
        member.save(update_fields=["last_typing_at"])
        url = reverse("messenger:poll_messages",args=[self.group.pk])
        self.assertEqual(self.client.get(url).json()["typing_names"],["bob"])
        UserBlock.objects.create(blocker=self.alice,blocked=self.bob)
        self.assertEqual(self.client.get(url).json()["typing_names"],[])
        UserBlock.objects.all().delete()
        member.last_typing_at = timezone.now()-timedelta(seconds=10)
        member.save(update_fields=["last_typing_at"])
        self.assertFalse(self.client.get(url).json()["other_typing"])


    def test_mentions_and_replies_are_content_free_and_muted_stays_muted(self):
        original = Message.objects.create(chat=self.group, sender=self.alice, text="original")
        mention = Message.objects.create(chat=self.group, sender=self.bob, text="Hello @ALICE!")
        reply = Message.objects.create(chat=self.group, sender=self.bob, text="answer", reply_to=original)
        ordinary = Message.objects.create(chat=self.group, sender=self.bob, text="`@alice` [link](https://example.org/@alice) alice@example.org")
        Message.objects.create(chat=self.group, sender=self.bob, text="@alice", silent=True)
        muted = Message.objects.create(chat=self.chat, sender=self.bob, text="@alice")
        ChatParticipant.objects.filter(chat=self.chat, user=self.alice).update(is_muted=True)
        url = reverse("messenger:poll_sound_notifications")
        payload = self.client.get(url, {
            "since":(timezone.now()-timedelta(seconds=10)).isoformat(), "include_unread":"1",
        }).json()
        self.assertEqual(payload["items"], [
            {"id":mention.pk,"chat_id":self.group.pk,"kind":"mention"},
            {"id":reply.pk,"chat_id":self.group.pk,"kind":"reply"},
            {"id":ordinary.pk,"chat_id":self.group.pk,"kind":"message"},
        ])
        self.assertEqual(payload["unread_count"], 5)
        self.assertNotIn(muted.pk, payload["ids"])
        self.assertNotIn("Hello", str(payload))
        self.assertEqual(mentioned_usernames("**@Alice** `@bob` bob@example.org"), {"alice"})

    def test_burst_paginates_equal_timestamps_without_dropping_alerts(self):
        rows = Message.objects.bulk_create([
            Message(chat=self.chat,sender=self.bob,text="burst") for _ in range(135)
        ])
        stamp = timezone.now()-timedelta(seconds=2)
        Message.objects.filter(pk__in=[row.pk for row in rows]).update(created_at=stamp)
        url = reverse("messenger:poll_sound_notifications")
        first = self.client.get(url, {"since":(stamp-timedelta(seconds=1)).isoformat()}).json()
        self.assertTrue(first["has_more"])
        self.assertEqual(len(first["ids"]),100)
        second = self.client.get(url, {"since":first["next_since"],"after_id":first["next_after_id"]}).json()
        self.assertFalse(second["has_more"])
        self.assertEqual(first["ids"]+second["ids"], [row.pk for row in rows])

    def test_initial_poll_returns_badge_without_replaying_old_messages(self):
        Message.objects.create(chat=self.chat, sender=self.bob, text="unread")
        url = reverse("messenger:poll_sound_notifications")
        first = self.client.get(url, {"include_unread":"1"}).json()
        self.assertEqual(first["items"], [])
        self.assertEqual(first["unread_count"],1)
