from datetime import timedelta

from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from .models import ChannelPostView, Chat, ChatParticipant, Message, MessageReaction


class CommunityStatisticsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("statsowner", "statsowner@example.org", "Password-1945!")
        cls.member = User.objects.create_user("statsmember", "statsmember@example.org", "Password-1945!")
        cls.admin = User.objects.create_user("statsadmin", "statsadmin@example.org", "Password-1945!")
        cls.outsider = User.objects.create_user("statsout", "statsout@example.org", "Password-1945!")
        cls.group = Chat.objects.create(type=Chat.Type.GROUP, title="Stats")
        cls.owner_row = ChatParticipant.objects.create(chat=cls.group, user=cls.owner, role="owner")
        ChatParticipant.objects.create(chat=cls.group, user=cls.member)
        cls.admin_row = ChatParticipant.objects.create(chat=cls.group, user=cls.admin, role="admin", admin_permissions=[])
        cls.url = reverse("messenger:community_statistics", args=[cls.group.pk])

    def setUp(self):
        cache.clear()
        self.client.force_login(self.owner)

    def test_counts_retained_messages_and_current_members(self):
        recent = Message.objects.create(chat=self.group, sender=self.owner, text="secret body")
        Message.objects.create(chat=self.group, sender=self.member, text="another")
        old = Message.objects.create(chat=self.group, sender=self.owner, text="old")
        Message.objects.filter(pk=old.pk).update(created_at=timezone.now()-timedelta(days=12))
        deleted = Message.objects.create(chat=self.group, sender=self.member, is_deleted=True)
        expired = Message.objects.create(chat=self.group, sender=self.member, expires_at=timezone.now()-timedelta(seconds=1))
        for msg in (recent, old, deleted, expired):
            MessageReaction.objects.create(message=msg,user=self.member,emoji="👍")
        ChatParticipant.objects.filter(pk=self.owner_row.pk).update(joined_at=timezone.now()-timedelta(days=12))
        seven = self.client.get(self.url).json()
        self.assertEqual(seven["messages"],2)
        self.assertEqual(seven["active_authors"],2)
        self.assertEqual(seven["members"],3)
        self.assertEqual(seven["new_members"],2)
        self.assertEqual(seven["reactions"],1)
        self.assertEqual(len(seven["series"]),7)
        self.assertEqual(sum(row["messages"] for row in seven["series"]),2)
        self.assertNotIn("secret body",str(seven))
        thirty = self.client.get(self.url,{"days":30}).json()
        self.assertEqual(thirty["messages"],3)
        self.assertEqual(thirty["new_members"],3)
        self.assertEqual(thirty["reactions"],2)
        self.assertEqual(len(thirty["series"]),30)

    def test_channel_reach_uses_first_view_dates_and_retained_posts(self):
        channel = Chat.objects.create(type=Chat.Type.CHANNEL, title="Channel stats")
        ChatParticipant.objects.create(chat=channel, user=self.owner, role="owner")
        old = Message.objects.create(chat=channel, sender=self.owner, text="Old")
        Message.objects.filter(pk=old.pk).update(created_at=timezone.now()-timedelta(days=12))
        recent = Message.objects.create(chat=channel, sender=self.owner, text="Recent")
        unseen = Message.objects.create(chat=channel, sender=self.owner, text="Unseen")
        deleted = Message.objects.create(chat=channel, sender=self.owner, is_deleted=True)
        for post, user, stamp in (
            (old, self.member, timezone.now()),
            (recent, self.member, timezone.now()),
            (recent, self.admin, None),
            (deleted, self.outsider, timezone.now()),
        ):
            ChannelPostView.objects.create(post=post, user=user, viewed_at=stamp)
        url = reverse("messenger:community_statistics", args=[channel.pk])
        data = self.client.get(url).json()
        self.assertEqual(data["channel_stats"], {
            "views": 2, "reach": 1, "published_views": 2,
            "average_views": 1.0, "undated_views": 1,
        })
        self.assertEqual(sum(row["views"] for row in data["series"]), 2)
        self.assertIsNone(self.client.get(self.url).json()["channel_stats"])
        self.assertEqual(self.client.get(url, {"days":30}).json()["channel_stats"]["published_views"], 3)

    def test_permission_account_guard_and_period_validation(self):
        self.assertEqual(self.client.get(self.url,{"days":"999"}).status_code,400)
        self.assertEqual(self.client.get(self.url,{"account_id":self.member.pk}).status_code,409)
        self.assertEqual(self.client.get(self.url)["Cache-Control"],"private, no-store")
        for user, status in ((self.member,403),(self.admin,403),(self.outsider,404)):
            client = Client()
            client.force_login(user)
            self.assertEqual(client.get(self.url).status_code,status)
        ChatParticipant.objects.filter(pk=self.admin_row.pk).update(admin_permissions=["manage_permissions"])
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url).status_code,200)
