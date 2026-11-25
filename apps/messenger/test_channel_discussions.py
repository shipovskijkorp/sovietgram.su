from datetime import timedelta
from uuid import uuid4

from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from .models import Chat, ChatAdminLog, ChatParticipant, ChannelComment, Message, MessageHiddenForUser


class ChannelDiscussionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("discussowner", "owner@example.net", "Password-1945!")
        cls.member = User.objects.create_user("discussmember", "member@example.net", "Password-1945!")
        cls.other = User.objects.create_user("discussother", "other@example.net", "Password-1945!")
        cls.admin = User.objects.create_user("discussadmin", "admin@example.net", "Password-1945!")
        cls.outsider = User.objects.create_user("discussout", "out@example.net", "Password-1945!")
        cls.channel = Chat.objects.create(type=Chat.Type.CHANNEL, title="News", comments_enabled=True)
        ChatParticipant.objects.create(chat=cls.channel,user=cls.owner,role="owner")
        cls.membership = ChatParticipant.objects.create(chat=cls.channel,user=cls.member)
        ChatParticipant.objects.create(chat=cls.channel,user=cls.other)
        ChatParticipant.objects.create(chat=cls.channel,user=cls.admin,role="admin",admin_permissions=[])
        cls.post = Message.objects.create(chat=cls.channel,sender=cls.owner,text="News")

    def setUp(self):
        cache.clear()
        self.clients = {}
        self.url = reverse("messenger:channel_discussion",args=[self.channel.pk,self.post.pk])
        self.action_url = reverse("messenger:discussion_action",args=[self.channel.pk,self.post.pk])
        self.settings_url = reverse("messenger:community_settings",args=[self.channel.pk])

    def client_for(self,user):
        if user.pk not in self.clients:
            client = Client()
            client.force_login(user)
            self.clients[user.pk] = client
        return self.clients[user.pk]

    def get(self,user=None,**values):
        user = user or self.member
        return self.client_for(user).get(self.url,{"account_id":user.pk,**values})

    def act(self,action,user=None,url=None,**values):
        user = user or self.member
        return self.client_for(user).post(url or self.action_url,{"account_id":user.pk,"action":action,**values})

    def create(self,text="Hello",user=None,**values):
        return self.act("create",user,text=text,client_id=str(uuid4()),reply_to=0,**values)

    def test_subscriber_can_comment_without_channel_post_right_and_retry_is_safe(self):
        client = self.client_for(self.member)
        send = client.post(reverse("messenger:send_message",args=[self.channel.pk]),{"text":"not a publication"},HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(send.status_code,403)
        key = str(uuid4())
        first = self.act("create",text="Hello",client_id=key,reply_to=0)
        self.assertEqual(first.status_code,200,first.content)
        again = self.act("create",text="Hello",client_id=key,reply_to=0)
        self.assertTrue(again.json()["replayed"])
        self.assertEqual(first.json()["id"],again.json()["id"])
        self.assertEqual(self.act("create",text="different",client_id=key,reply_to=0).status_code,409)
        self.assertEqual(ChannelComment.objects.count(),1)
        self.assertEqual(Message.objects.filter(chat=self.channel).count(),1)
        self.assertEqual(self.get().json()["comments"][0]["text"],"Hello")
        self.assertEqual(self.get()["Cache-Control"],"private, no-store")

    def test_replies_edit_conflict_and_delete_permissions(self):
        comment_id = self.create().json()["id"]
        other = self.act("create",self.other,text="Reply",reply_to=comment_id,client_id=str(uuid4()))
        self.assertEqual(other.status_code,200,other.content)
        result = self.get().json()["comments"]
        self.assertEqual(result[1]["reply"]["id"],comment_id)
        revision = result[0]["revision"]
        self.assertEqual(self.act("edit",self.other,comment_id=comment_id,text="stolen",revision=revision).status_code,403)
        self.assertEqual(self.act("edit",comment_id=comment_id,text="Changed",revision=revision).status_code,200)
        self.assertEqual(self.act("edit",comment_id=comment_id,text="Stale",revision=revision).status_code,409)
        self.assertEqual(self.get().json()["comments"][1]["reply"]["text"],"Changed")
        self.assertEqual(self.act("delete",self.admin,comment_id=comment_id).status_code,403)
        self.assertEqual(self.act("delete",self.owner,comment_id=comment_id).status_code,200)
        result = self.get().json()
        self.assertEqual(result["total"],1)
        self.assertIsNone(result["comments"][0]["reply"])
        self.assertEqual(ChannelComment.objects.get(pk=comment_id).text,"")

    def test_moderation_and_channel_setting(self):
        self.assertEqual(self.act("close").status_code,403)
        self.assertEqual(self.act("close",self.owner).status_code,200)
        self.assertTrue(self.get().json()["closed"])
        self.assertFalse(self.get().json()["can_write"])
        self.assertEqual(self.create().status_code,403)
        self.assertEqual(self.act("open",self.owner).status_code,200)
        self.assertEqual(self.create().status_code,200)
        settings = {"section":"comments","enabled":"0"}
        self.assertEqual(self.client_for(self.admin).post(self.settings_url,settings).status_code,403)
        self.assertEqual(self.client_for(self.owner).post(self.settings_url,settings).status_code,200)
        self.assertEqual(self.get().status_code,404)
        self.assertEqual(ChannelComment.objects.filter(is_deleted=False).count(),1)
        settings["enabled"] = "1"
        self.assertEqual(self.client_for(self.owner).post(self.settings_url,settings).status_code,200)
        self.assertEqual(self.get().json()["total"],1)
        mod_url = reverse("messenger:community_moderation",args=[self.channel.pk])
        mod = {"action":"restrict","account_id":self.owner.pk,"user_id":self.member.pk,"duration":"1h","permissions":'["comment"]'}
        response = self.client_for(self.owner).post(mod_url,mod)
        self.assertEqual(response.status_code,200,response.content)
        self.assertFalse(self.get().json()["can_write"])
        self.assertEqual(self.create().status_code,403)
        mod["action"] = "lift"
        self.assertEqual(self.client_for(self.owner).post(mod_url,mod).status_code,200)
        self.assertTrue(self.get().json()["can_write"])
        self.assertTrue(ChatAdminLog.objects.filter(chat=self.channel,action="discussion_close").exists())

    def test_visibility_guards_and_post_deletion(self):
        self.assertEqual(self.get(self.outsider).status_code,404)
        self.assertEqual(self.get(account_id=self.other.pk).status_code,409)
        self.assertEqual(self.act("create",account_id=self.other.pk).status_code,409)
        self.assertEqual(self.get(before="-1").status_code,400)
        self.assertEqual(self.create().status_code,200)
        MessageHiddenForUser.objects.create(message=self.post,user=self.member)
        self.assertEqual(self.get().status_code,404)
        self.assertEqual(self.create().status_code,404)
        MessageHiddenForUser.objects.all().delete()
        ChatParticipant.objects.filter(pk=self.membership.pk).update(cleared_before_message_id=self.post.pk)
        self.assertEqual(self.get().status_code,404)
        ChatParticipant.objects.filter(pk=self.membership.pk).update(cleared_before_message_id=0)
        self.channel.history_visible_to_new_members = False
        self.channel.save(update_fields=["history_visible_to_new_members"])
        ChatParticipant.objects.filter(pk=self.membership.pk).update(can_see_pre_join_history=False,joined_at=timezone.now()+timedelta(seconds=1))
        self.assertEqual(self.get().status_code,404)
        ChatParticipant.objects.filter(pk=self.membership.pk).update(can_see_pre_join_history=True)
        self.assertEqual(self.get().status_code,200)
        response = self.client_for(self.owner).post(reverse("messenger:delete_message",args=[self.channel.pk,self.post.pk]),{"scope":"everyone"})
        self.assertEqual(response.status_code,200,response.content)
        self.assertFalse(ChannelComment.objects.filter(post=self.post).exists())
        self.assertEqual(self.get().status_code,404)

    def test_pagination_counts_and_cross_thread_reply(self):
        rows = ChannelComment.objects.bulk_create([
            ChannelComment(post=self.post,author=self.member,text=str(i),client_id=uuid4()) for i in range(45)
        ])
        first = self.get().json()
        self.assertEqual(first["total"],45)
        self.assertEqual(len(first["comments"]),40)
        second = self.get(before=first["next_before"]).json()
        self.assertEqual([row["id"] for row in second["comments"]+first["comments"]],[row.pk for row in rows])
        self.assertIsNone(second["next_before"])
        poll = self.client_for(self.member).get(reverse("messenger:poll_messages",args=[self.channel.pk]),{"after":self.post.pk,"known_ids":str(self.post.pk)}).json()
        self.assertTrue(poll["comments_enabled"])
        self.assertEqual(poll["discussion_counts"],{str(self.post.pk):45})
        page = self.client_for(self.member).get(reverse("messenger:chat",args=[self.channel.pk]))
        self.assertContains(page,'data-discussion-count="45"')
        another = Message.objects.create(chat=self.channel,sender=self.owner,text="Another")
        url = reverse("messenger:discussion_action",args=[self.channel.pk,another.pk])
        self.assertEqual(self.act("create",url=url,text="Invalid",client_id=str(uuid4()),reply_to=rows[0].pk).status_code,404)

    def test_expiry_and_csrf(self):
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.member)
        self.assertEqual(csrf.post(self.action_url,{"account_id":self.member.pk,"action":"create","text":"test","client_id":str(uuid4())}).status_code,403)
        Message.objects.filter(pk=self.post.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.get().status_code,404)
        self.assertEqual(self.create().status_code,404)
