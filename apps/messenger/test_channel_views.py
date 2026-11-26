from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import User
from .models import ChannelPostView, Chat, ChatParticipant, Message, MessageHiddenForUser


class ChannelViewsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("view_owner", "owner-view@example.net", "Password-1945!")
        cls.peer = User.objects.create_user("view_peer", "peer-view@example.net", "Password-1945!")
        cls.outsider = User.objects.create_user("view_outsider", "other-view@example.net", "Password-1945!")
        cls.channel = Chat.objects.create(type=Chat.Type.CHANNEL, title="Views")
        cls.group = Chat.objects.create(type=Chat.Type.GROUP, title="Group")
        for chat in (cls.channel, cls.group):
            ChatParticipant.objects.create(chat=chat, user=cls.owner, role="owner")
            ChatParticipant.objects.create(chat=chat, user=cls.peer, role="member")
        cls.post = Message.objects.create(chat=cls.channel, sender=cls.owner, text="Publication")
        cls.other_post = Message.objects.create(chat=cls.group, sender=cls.owner, text="Other chat")

    def setUp(self):
        cache.clear()
        self.client.force_login(self.peer)
        self.url = reverse("messenger:channel_post_views", args=[self.channel.pk])

    def post_views(self, ids, user=None, client=None):
        return (client or self.client).post(self.url, {
            "ids": ",".join(str(pk) for pk in ids),
            "account_id": (user or self.peer).pk,
        })

    def test_unique_views_and_read_only_subscribers(self):
        self.assertEqual(self.post_views([self.post.pk, self.post.pk]).json()["counts"], {str(self.post.pk):1})
        self.assertEqual(self.post_views([self.post.pk]).json()["counts"], {str(self.post.pk):1})
        owner = Client()
        owner.force_login(self.owner)
        self.assertEqual(self.post_views([self.post.pk], self.owner, owner).json()["counts"], {str(self.post.pk):2})
        self.assertEqual(self.post_views([self.post.pk]).json()["counts"], {str(self.post.pk):2})
        self.assertEqual(ChannelPostView.objects.filter(post=self.post).count(), 2)

    def test_membership_visibility_and_validated_ids(self):
        self.assertEqual(self.post_views([self.other_post.pk]).json()["counts"], {})
        MessageHiddenForUser.objects.create(message=self.post, user=self.peer)
        self.assertEqual(self.post_views([self.post.pk]).json()["counts"], {})
        self.assertFalse(ChannelPostView.objects.exists())
        self.assertEqual(self.post_views([-1]).status_code, 400)
        self.assertEqual(self.post_views([self.post.pk], self.owner).status_code, 409)
        self.assertEqual(self.client.post(reverse("messenger:channel_post_views", args=[self.group.pk]),
                         {"ids": self.other_post.pk, "account_id": self.peer.pk}).status_code, 404)
        self.client.force_login(self.outsider)
        self.assertEqual(self.post_views([self.post.pk], self.outsider).status_code, 404)
