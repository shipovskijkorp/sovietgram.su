from uuid import uuid4

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from .models import Message
from .services import get_or_create_direct_chat


class ForwardOptionsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.net", "Password-1945!")
        cls.bob = User.objects.create_user("bob", "bob@example.net", "Password-1945!")
        cls.carol = User.objects.create_user("carol", "carol@example.net", "Password-1945!")
        cls.source = get_or_create_direct_chat(cls.alice, cls.bob)
        cls.target = get_or_create_direct_chat(cls.alice, cls.carol)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.alice)

    def forward(self, message, **fields):
        return self.client.post(
            reverse("messenger:forward_message", args=[message.chat_id,message.pk]),
            {"target_chat_id":self.target.pk, "account_id":self.alice.pk, **fields},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

    def test_hidden_sender_and_silent_forward_are_idempotent_and_not_reattributed(self):
        source = Message.objects.create(chat=self.source,sender=self.bob,text="forward me")
        fields = {"hide_sender":"1","silent":"1","client_message_id":str(uuid4())}
        result = self.forward(source,**fields)
        self.assertEqual(result.status_code,200,result.content)
        retry = self.forward(source,**fields)
        self.assertEqual(retry.status_code,200)
        self.assertTrue(retry.json()["replayed"])
        first = Message.objects.get(pk=result.json()["message"]["id"])
        self.assertTrue(first.silent)
        self.assertIsNone(first.forwarded_from_id)
        self.assertEqual(first.forwarded_from_username,"")
        self.assertEqual(first.forwarded_from_name,"Скрытый отправитель")
        second = self.forward(first,target_chat_id="saved")
        self.assertEqual(second.status_code,200,second.content)
        self.assertEqual(second.json()["message"]["forwarded"]["name"],"Скрытый отправитель")
        self.assertEqual(second.json()["message"]["forwarded"]["username"],"")
        self.assertEqual(Message.objects.filter(chat=self.target).count(),1)

    def test_forward_poll_has_no_source_votes_and_is_independent(self):
        source = Message.objects.create(chat=self.source,sender=self.bob,
            special_type=Message.SpecialType.POLL,
            special_data={"question":"Question","anonymous":True,"closed":True,
                          "options":[{"text":"A","voters":[self.alice.pk]}, {"text":"B","voters":[self.bob.pk]}]})
        response = self.forward(source)
        self.assertEqual(response.status_code,200,response.content)
        copied = Message.objects.get(pk=response.json()["message"]["id"])
        self.assertFalse(copied.special_data["closed"])
        self.assertEqual([item["voters"] for item in copied.special_data["options"]],[[],[]])
        self.assertEqual(response.json()["message"]["special"]["total_voters"],0)
        source.refresh_from_db()
        self.assertTrue(source.special_data["closed"])
        self.assertEqual(source.special_data["options"][0]["voters"],[self.alice.pk])

    def test_unanswered_quiz_cannot_be_forwarded_to_reveal_solution(self):
        source = Message.objects.create(chat=self.source,sender=self.bob,
            special_type=Message.SpecialType.POLL,
            special_data={"question":"Question","quiz":True,"correct_option":1,
                          "options":[{"text":"A","voters":[]},{"text":"B","voters":[]}]})
        denied = self.forward(source)
        self.assertEqual(denied.status_code,403)
        self.assertFalse(Message.objects.filter(chat=self.target).exists())
        vote = self.client.post(reverse("messenger:special_message_action",args=[self.source.pk,source.pk]),
                                {"action":"vote","options":"[0]"},HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(vote.status_code,200,vote.content)
        allowed = self.forward(source)
        self.assertEqual(allowed.status_code,200,allowed.content)
        self.assertEqual(allowed.json()["message"]["special"]["total_voters"],0)

    def test_forward_todo_does_not_copy_source_user_id(self):
        source = Message.objects.create(chat=self.source,sender=self.bob,
            special_type=Message.SpecialType.TODO,
            special_data={"title":"Tasks","tasks":[{"text":"Done","done":True,"done_by":self.bob.pk}]})
        result = self.forward(source)
        self.assertEqual(result.status_code,200,result.content)
        copied = Message.objects.get(pk=result.json()["message"]["id"])
        self.assertEqual(copied.special_data["tasks"],[{"text":"Done","done":True,"done_by":None}])

    def test_protection_and_stale_account_apply_to_forward_and_delete(self):
        source = Message.objects.create(chat=self.source,sender=self.bob,text="protected")
        self.source.protect_content = True
        self.source.save(update_fields=["protect_content"])
        self.assertEqual(self.forward(source,hide_sender="1").status_code,403)
        self.assertEqual(self.forward(source,account_id=self.bob.pk).status_code,409)
        delete = reverse("messenger:delete_message",args=[self.source.pk,source.pk])
        self.assertEqual(self.client.post(delete,{"account_id":self.bob.pk,"scope":"everyone"}).status_code,409)
        self.assertEqual(self.client.post(delete,{"scope":"invalid"}).status_code,400)
        source.refresh_from_db()
        self.assertFalse(source.is_deleted)

    def test_context_menu_exposes_forward_options_and_message_link(self):
        Message.objects.create(chat=self.source,sender=self.bob,text="hello")
        page = self.client.get(reverse("messenger:chat",args=[self.source.pk]))
        for marker in ('id="forwardConfirm"', 'id="forwardHideSender"', 'id="forwardSilent"',
                       'data-message-action="copy-link"'):
            self.assertContains(page,marker)
