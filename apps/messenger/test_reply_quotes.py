from datetime import timedelta
from uuid import uuid4

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from .models import Message, MessageHiddenForUser, ScheduledMessage
from .services import get_or_create_direct_chat, delete_message_content


class ReplyQuoteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("quote_owner", "quote-owner@example.net", "Password-1945!")
        cls.peer = User.objects.create_user("quote_peer", "quote-peer@example.net", "Password-1945!")
        cls.chat = get_or_create_direct_chat(cls.owner, cls.peer)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.owner)
        self.original = Message.objects.create(chat=self.chat, sender=self.peer, text="Начало 😀 нужный фрагмент конец")
        self.url = reverse("messenger:send_message", args=[self.chat.pk])

    def send_quote(self, quote="нужный фрагмент", **extra):
        return self.client.post(self.url, {
            "text":"Ответ", "reply_to":self.original.pk, "reply_quote":quote,
            "account_id":self.owner.pk, "client_message_id":str(uuid4()), **extra,
        }, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_verified_quote_and_hidden_or_edited_source(self):
        result = self.send_quote()
        self.assertEqual(result.status_code, 200, result.content)
        data = result.json()["message"]
        self.assertEqual(data["reply"]["quote"], "нужный фрагмент")
        reply = Message.objects.get(pk=data["id"])
        self.assertNotIn("нужный фрагмент", reply.reply_quote)
        self.assertEqual(reply.reply_quote_text, "нужный фрагмент")
        page = reverse("messenger:chat", args=[self.chat.pk])
        history = reverse("messenger:message_history", args=[self.chat.pk])
        self.assertContains(self.client.get(page), "message-reply-quote")
        Message.objects.filter(pk=self.original.pk).update(text="Изменённый текст")
        self.assertNotIn("quote", next(row for row in self.client.get(history).json()["messages"] if row["id"]==reply.pk)["reply"])
        MessageHiddenForUser.objects.create(message=self.original, user=self.owner)
        self.assertIsNone(next(row for row in self.client.get(history).json()["messages"] if row["id"]==reply.pk)["reply"])

    def test_rejects_forged_quotes_and_protected_chat(self):
        self.assertEqual(self.send_quote("Подложный текст").status_code, 400)
        self.assertEqual(self.send_quote(reply_to="").status_code, 400)
        self.chat.protect_content = True
        self.chat.save(update_fields=["protect_content"])
        self.assertEqual(self.send_quote().status_code, 400)
        self.assertEqual(Message.objects.filter(chat=self.chat).count(), 1)

    def test_scheduled_quote_survives_until_delivery(self):
        url = reverse("messenger:scheduled_messages", args=[self.chat.pk])
        response = self.client.post(url, {
            "account_id":self.owner.pk, "client_message_id":str(uuid4()),
            "text":"Позже", "reply_to":self.original.pk, "reply_quote":"нужный фрагмент",
            "scheduled_for":(timezone.now()+timedelta(hours=1)).isoformat(),
        }, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200, response.content)
        item = ScheduledMessage.objects.get(pk=response.json()["item"]["id"])
        self.assertTrue(item.reply_quote)
        from .scheduled import deliver_due_messages
        ScheduledMessage.objects.filter(pk=item.pk).update(next_attempt_at=timezone.now()-timedelta(seconds=1))
        deliver_due_messages()
        item.refresh_from_db()
        self.assertEqual(item.status, ScheduledMessage.Status.SENT)
        self.assertEqual(item.delivered_message.reply_quote_text, "нужный фрагмент")
        self.assertEqual(item.reply_quote, "")
