from uuid import uuid4

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from .models import ChatParticipant, Message, MessageSendReceipt
from .services import get_or_create_direct_chat


class TextOutboxTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.net", "Password-1945!")
        cls.bob = User.objects.create_user("bob", "bob@example.net", "Password-1945!")
        cls.chat = get_or_create_direct_chat(cls.alice, cls.bob)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.alice)

    def test_queued_send_preserves_new_draft_and_retry_is_idempotent(self):
        member = ChatParticipant.objects.get(chat=self.chat, user=self.alice)
        member.draft_text = "new draft"
        member.save(update_fields=["draft_text"])
        url = reverse("messenger:send_message", args=[self.chat.pk])
        fields = {"text":"queued", "client_message_id":str(uuid4()),
                  "account_id":self.alice.pk, "preserve_draft":"1"}
        for _ in range(2):
            result = self.client.post(url, fields, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
            self.assertEqual(result.status_code, 200, result.content)
        member.refresh_from_db()
        self.assertEqual(member.draft_text, "new draft")
        self.assertEqual(Message.objects.filter(chat=self.chat).count(), 1)
        self.assertEqual(MessageSendReceipt.objects.filter(sender=self.alice).count(), 1)

    def test_stale_account_cannot_send_or_change_draft(self):
        url = reverse("messenger:send_message", args=[self.chat.pk])
        result = self.client.post(url, {"text":"wrong account","client_message_id":str(uuid4()),
                                       "account_id":self.bob.pk}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(result.status_code, 409)
        draft = reverse("messenger:save_draft", args=[self.chat.pk])
        self.assertEqual(self.client.post(draft, {"text":"wrong","account_id":self.bob.pk}).status_code, 409)
        self.assertFalse(Message.objects.exists())
        self.assertEqual(ChatParticipant.objects.get(chat=self.chat,user=self.alice).draft_text,"")
