from datetime import timedelta
import json

from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from .membership_statistics import Source, purge_membership_events, record_membership_event
from .models import (
    Chat, ChatParticipant, ChatInviteLink, ChatJoinRequest,
    CommunityMembershipEvent, Message, MessageReaction, ChannelComment,
)


class MembershipStatisticsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("acqowner", "acqowner@example.test", "Test-pass-1945!")
        cls.peer = User.objects.create_user("acqpeer", "acqpeer@example.test", "Test-pass-1945!")
        cls.other = User.objects.create_user("acqother", "acqother@example.test", "Test-pass-1945!")
        cls.admin = User.objects.create_user("acqadmin", "acqadmin@example.test", "Test-pass-1945!")
        cls.channel = Chat.objects.create(type=Chat.Type.CHANNEL, title="Acquisition", username="acquisition")
        ChatParticipant.objects.create(chat=cls.channel, user=cls.owner, role="owner")
        ChatParticipant.objects.create(chat=cls.channel, user=cls.admin, role="admin", admin_permissions=["manage_permissions"])
        cls.direct_invite = ChatInviteLink.objects.create(chat=cls.channel, creator=cls.owner, name="Friends", token="acq-invite-token")
        cls.approval_invite = ChatInviteLink.objects.create(chat=cls.channel, creator=cls.owner, name="Approval", token="acq-approval-token", requires_approval=True)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.owner)

    def client_for(self, user):
        client = Client()
        client.force_login(user)
        return client

    def stats(self, client=None, days=7):
        response = (client or self.client).get(reverse("messenger:community_statistics", args=[self.channel.pk]), {"days":days})
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def post(self, name, client, **fields):
        return client.post(reverse("messenger:" + name, args=[self.channel.pk]), fields, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_join_sources_survive_leave_and_are_idempotent(self):
        peer = self.client_for(self.peer)
        other = self.client_for(self.other)
        join = reverse("messenger:join_directory_chat", args=[self.channel.username])
        for _ in range(2):
            self.assertEqual(peer.post(join, {"account_id":self.peer.pk}).status_code,302)
        self.assertEqual(self.post("chat_action",peer,action="leave").status_code,200)
        # Repeated leave cannot record a second event.
        self.assertEqual(CommunityMembershipEvent.objects.filter(chat=self.channel,source=Source.LEAVE).count(),1)
        self.assertEqual(peer.post(reverse("messenger:join_public_chat", args=[self.channel.username])).status_code,302)
        self.assertEqual(other.post(reverse("messenger:join_invite", args=[self.direct_invite.token])).status_code,302)
        self.assertEqual(self.post("community_member_action",self.client,action="remove",username=self.other.username).status_code,200)
        self.assertEqual(other.post(reverse("messenger:join_invite", args=[self.approval_invite.token])).status_code,302)
        row = ChatJoinRequest.objects.get(chat=self.channel,user=self.other)
        for _ in range(2):
            self.assertEqual(self.post("community_join_request_action",self.client,action="approve",request_id=row.pk,account_id=self.owner.pk,revision=row.created_at.isoformat()).status_code,200)
        data = self.stats()
        growth = data["membership_stats"]
        self.assertEqual((growth["recorded_joins"],growth["recorded_leaves"],growth["recorded_net"]),(4,2,2))
        sources = {item["source"]:item["count"] for item in growth["join_sources"]}
        self.assertEqual([sources[s] for s in ("directory","public","invite","approval")],[1,1,1,1])
        self.assertEqual(sum(row["joins"] for row in data["series"]),4)
        self.assertEqual(sum(row["leaves"] for row in data["series"]),2)
        self.assertEqual(len(growth["invite_sources"]),2)
        self.assertNotIn(self.direct_invite.token,json.dumps(data))
        limited = self.stats(self.client_for(self.admin))["membership_stats"]
        self.assertIsNone(limited["invite_sources"])
        self.assertEqual(limited["recorded_joins"],4)
        self.assertEqual(peer.get(reverse("messenger:community_statistics",args=[self.channel.pk])).status_code,403)

    def test_manual_add_ban_and_revocation(self):
        self.assertEqual(self.post("community_member_action",self.client,action="add",username=self.peer.username).status_code,200)
        for _ in range(2):
            self.assertEqual(self.post("community_moderation",self.client,action="ban",user_id=self.peer.pk,
                account_id=self.owner.pk,duration="forever",permissions="[]").status_code,200)
        growth=self.stats()["membership_stats"]
        self.assertEqual(growth["recorded_joins"],1)
        self.assertEqual(growth["recorded_leaves"],1)
        self.assertEqual({row["source"]:row["count"] for row in growth["leave_sources"]}["banned"],1)
        self.assertFalse(ChatParticipant.objects.filter(chat=self.channel,user=self.peer).exists())

    def test_retention_and_distinct_engagement_on_old_posts(self):
        ChatParticipant.objects.create(chat=self.channel,user=self.peer)
        old=Message.objects.create(chat=self.channel,sender=self.owner,text="Secret post")
        Message.objects.filter(pk=old.pk).update(created_at=timezone.now()-timedelta(days=12))
        MessageReaction.objects.create(message=old,user=self.peer,emoji="👍")
        MessageReaction.objects.create(message=old,user=self.peer,emoji="🔥")
        import uuid
        ChannelComment.objects.create(post=old,author=self.peer,client_id=uuid.uuid4(),text="Private comment")
        record_membership_event(self.channel,Source.PUBLIC)
        old_event=CommunityMembershipEvent.objects.create(chat=self.channel,source=Source.MANUAL_ADD,
            occurred_at=timezone.now()-timedelta(days=12))
        expired=CommunityMembershipEvent.objects.create(chat=self.channel,source=Source.LEAVE,
            occurred_at=timezone.now()-timedelta(days=91))
        recent=self.stats()
        self.assertEqual(recent["engagement"],{
            "active_members":1,"active_member_percent":33.3,"period_reactions":2,
            "unique_reactors":1,"period_comments":1,"unique_commenters":1,
        })
        self.assertEqual(recent["membership_stats"]["recorded_joins"],1)
        self.assertEqual(self.stats(days=30)["membership_stats"]["recorded_joins"],2)
        self.assertNotIn("Secret post",json.dumps(recent))
        self.assertNotIn("Private comment",json.dumps(recent))
        self.assertEqual(purge_membership_events(limit=1),1)
        self.assertFalse(CommunityMembershipEvent.objects.filter(pk=expired.pk).exists())
        self.assertTrue(CommunityMembershipEvent.objects.filter(pk=old_event.pk).exists())
