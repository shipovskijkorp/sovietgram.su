from datetime import timedelta

from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from .models import Chat, ChatParticipant, ChatMemberModeration, ChatAdminLog, Message
from .services import serialize_message


class AdminTitlesDirectoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("titles_owner", "owner@example.test", "Test-pass-1945!")
        cls.admin = User.objects.create_user("titles_admin", "admin@example.test", "Test-pass-1945!")
        cls.member = User.objects.create_user("titles_member", "member@example.test", "Test-pass-1945!")
        cls.group = Chat.objects.create(type=Chat.Type.GROUP, title="Космическая Группа", username="cosmic_group",
                                        description="Корабли и астрономия")
        cls.channel = Chat.objects.create(type=Chat.Type.CHANNEL, title="Космический Канал", username="cosmic_channel",
                                          signatures_enabled=True)
        for chat in (cls.group, cls.channel):
            for user, role in ((cls.owner, "owner"), (cls.admin, "admin"), (cls.member, "member")):
                ChatParticipant.objects.create(chat=chat, user=user, role=role)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.owner)

    def member_action(self, chat, user, action, actor=None, **fields):
        self.client.force_login(actor or self.owner)
        return self.client.post(reverse("messenger:community_member_action", args=[chat.pk]),
            {"action":action,"username":user.username,"account_id":(actor or self.owner).pk, **fields})

    def test_title_rights_validation_and_history_snapshot(self):
        self.assertEqual(self.member_action(self.group,self.admin,"admin_title",title="Модератор").status_code,200)
        self.assertEqual(self.member_action(self.group,self.member,"admin_title",title="Fake").status_code,400)
        self.assertEqual(self.member_action(self.group,self.admin,"admin_title",actor=self.admin,title="Fake").status_code,403)
        self.assertEqual(self.member_action(self.group,self.admin,"admin_title",title="a"*33).status_code,400)
        self.assertEqual(self.member_action(self.group,self.admin,"admin_title",title="a\u202eb").status_code,400)
        first = Message.objects.create(chat=self.group,sender=self.admin,text="First")
        self.assertEqual(first.sender_title,"Модератор")
        self.assertEqual(serialize_message(first,self.member)["sender_title"],"Модератор")
        self.assertTrue(serialize_message(first,self.member)["show_group_author"])
        self.assertEqual(self.member_action(self.group,self.admin,"admin_title",title="New").status_code,200)
        second = Message.objects.create(chat=self.group,sender=self.admin,text="Second")
        self.assertEqual(second.sender_title,"New")
        self.assertEqual(self.member_action(self.group,self.admin,"role",role="member").status_code,200)
        third = Message.objects.create(chat=self.group,sender=self.admin,text="Third")
        self.assertEqual(third.sender_title,"")
        self.assertEqual(ChatParticipant.objects.get(chat=self.group,user=self.admin).admin_title,"")
        first.refresh_from_db()
        self.assertEqual(first.sender_title,"Модератор")
        self.assertTrue(ChatAdminLog.objects.filter(chat=self.group,action="admin_title").exists())
        self.client.force_login(self.member)
        self.assertContains(self.client.get(reverse("messenger:chat",args=[self.group.pk])),"Модератор")

    def test_channel_unsigned_posts_do_not_carry_titles(self):
        self.assertEqual(self.member_action(self.channel,self.admin,"admin_title",title="Редактор").status_code,200)
        signed = Message.objects.create(chat=self.channel,sender=self.admin,text="Signed",signature_name="Author")
        unsigned = Message.objects.create(chat=self.channel,sender=self.admin,text="Unsigned")
        self.assertEqual(signed.sender_title,"Редактор")
        self.assertEqual(unsigned.sender_title,"")
        self.assertFalse(serialize_message(signed,self.member)["show_group_author"])
        self.assertEqual(serialize_message(unsigned,self.member)["sender_title"],"")
        self.client.force_login(self.member)
        self.assertContains(self.client.get(reverse("messenger:chat",args=[self.channel.pk])),"Author · Редактор")

    def test_directory_filters_unicode_privacy_and_membership(self):
        private = Chat.objects.create(type=Chat.Type.GROUP,title="Private secret",description="Космос")
        banned = Chat.objects.create(type=Chat.Type.GROUP,title="Banned secret",username="banned_secret")
        ChatMemberModeration.objects.create(chat=banned,user=self.member,banned=True,expires_at=timezone.now()+timedelta(days=1))
        hidden = Chat.objects.create(type=Chat.Type.CHANNEL,title="Platform hidden",platform_public_restricted=True)
        self.client.force_login(self.member)
        url=reverse("messenger:community_directory")
        response=self.client.get(url)
        self.assertContains(response,self.group.title)
        self.assertContains(response,self.channel.title)
        self.assertNotContains(response,private.title)
        self.assertNotContains(response,banned.title)
        self.assertNotContains(response,hidden.title)
        self.assertIn("no-store",response["Cache-Control"])
        response=self.client.get(url,{"q":"КОРАБЛИ космическая","kind":"group"})
        self.assertContains(response,self.group.title)
        self.assertNotContains(response,self.channel.title)
        self.assertContains(response,"Открыть")
        self.group.title="Новая группа"
        self.group.save(update_fields=["title"])
        self.assertContains(self.client.get(url,{"q":"НОВАЯ"}),"Новая группа")
        self.group.username=None
        self.group.save(update_fields=["username"])
        self.assertNotContains(self.client.get(url),"Новая группа")

    def test_directory_join_account_guard_and_pagination(self):
        for i in range(22):
            Chat.objects.create(type=Chat.Type.GROUP,title=f"Public {i:02d}",username=f"public_{i:02d}")
        url=reverse("messenger:community_directory")
        response=self.client.get(url,{"q":"public","sort":"new","kind":"group"})
        self.assertEqual(response.context["page"].paginator.count,22)
        self.assertEqual(len(response.context["page"].object_list),20)
        self.assertEqual(len(self.client.get(url,{"q":"public","page":2}).context["page"].object_list),2)
        join=reverse("messenger:join_public_chat",args=["public_00"])
        self.assertEqual(self.client.post(join,{"account_id":self.member.pk}).status_code,409)
        self.assertEqual(self.client.post(join,{"account_id":self.owner.pk}).status_code,302)
        self.assertTrue(ChatParticipant.objects.filter(chat__username="public_00",user=self.owner).exists())
        self.assertEqual(Client().get(url).status_code,302)
