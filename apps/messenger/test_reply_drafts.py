from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import User
from .models import ChatParticipant, Message, MessageHiddenForUser
from .services import get_or_create_direct_chat


class ReplyDraftTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("draftalice", "draftalice@example.net", "Password-1945!")
        cls.bob = User.objects.create_user("draftbob", "draftbob@example.net", "Password-1945!")
        cls.chat = get_or_create_direct_chat(cls.alice, cls.bob)
        cls.message = Message.objects.create(chat=cls.chat, sender=cls.bob, text="Original quote text")

    def setUp(self):
        self.client.force_login(self.alice)
        self.url = reverse("messenger:save_draft", args=[self.chat.pk])
        self.page = reverse("messenger:chat", args=[self.chat.pk])

    def save(self, **fields):
        return self.client.post(self.url, {"account_id": self.alice.pk, "text": "Draft", **fields})

    def membership(self):
        return ChatParticipant.objects.get(chat=self.chat, user=self.alice)

    def test_reply_and_verified_quote_restore_on_another_browser(self):
        self.assertEqual(self.save(reply_to=self.message.pk, reply_quote="quote text").status_code, 200)
        member = self.membership()
        self.assertEqual(member.draft_reply_id, self.message.pk)
        self.assertNotIn("quote text", member.draft_quote)
        second = Client()
        second.force_login(self.alice)
        page = second.get(self.page)
        self.assertContains(page, f'name="reply_to" value="{self.message.pk}"')
        self.assertContains(page, 'name="reply_quote" value="quote text"')
        self.assertContains(page, "Draft")
        Message.objects.filter(pk=self.message.pk).update(text="Edited")
        self.assertContains(second.get(self.page), 'name="reply_quote" value=""')
        MessageHiddenForUser.objects.create(message=self.message, user=self.alice)
        self.assertContains(second.get(self.page), 'name="reply_to" value=""')

    def test_reply_only_draft_and_clear(self):
        self.assertEqual(self.save(text="", reply_to=self.message.pk).status_code, 200)
        self.assertIsNotNone(self.membership().draft_updated_at)
        self.assertContains(self.client.get(self.page), f'name="reply_to" value="{self.message.pk}"')
        self.assertEqual(self.save(text="", reply_to="").status_code, 200)
        member = self.membership()
        self.assertIsNone(member.draft_reply_id)
        self.assertIsNone(member.draft_updated_at)
        self.assertEqual(member.draft_quote, "")

    def test_protected_chat_and_cross_chat_reply(self):
        self.chat.protect_content = True
        self.chat.save(update_fields=["protect_content"])
        self.assertEqual(self.save(reply_to=self.message.pk, reply_quote="quote text").status_code, 200)
        self.assertEqual(self.membership().draft_quote, "")
        other = get_or_create_direct_chat(self.bob, self.bob)
        foreign = Message.objects.create(chat=other, sender=self.bob, text="Private elsewhere")
        self.assertEqual(self.save(reply_to=foreign.pk).status_code, 200)
        self.assertIsNone(self.membership().draft_reply_id)
        self.assertEqual(self.save(account_id=self.bob.pk).status_code, 409)
