"""Regression coverage for safe poll exports and cross-client message removal."""
import html
import json
import zipfile
from datetime import timedelta
from io import BytesIO

from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from .models import Chat, ChatParticipant, Message, MessageHiddenForUser
from .services import get_or_create_direct_chat, purge_expired_messages


class PollPrivacyAndRemovalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.net", "Password-1945!")
        cls.bob = User.objects.create_user("bob", "bob@example.net", "Password-1945!")
        cls.admin = User.objects.create_user("admin", "admin@example.net", "Password-1945!")
        cls.chat = get_or_create_direct_chat(cls.alice, cls.bob)
        cls.group = Chat.objects.create(type=Chat.Type.GROUP, title="Group")
        for user, role in ((cls.alice, "owner"), (cls.bob, "member"), (cls.admin, "admin")):
            ChatParticipant.objects.create(chat=cls.group, user=user, role=role)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.bob)

    def poll(self, chat=None, **fields):
        return Message.objects.create(
            chat=chat or self.chat, sender=self.alice, special_type=Message.SpecialType.POLL,
            special_data={
                "question": "Question", "anonymous": True, "multiple": False,
                "quiz": False, "closed": False,
                "options": [{"text": "First", "voters": []}, {"text": "Second", "voters": []}],
                **fields,
            },
        )

    def exported(self, chat):
        response = self.client.get(reverse("messenger:export_chat_history", args=[chat.pk]))
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(BytesIO(b"".join(response.streaming_content))) as bundle:
            return html.unescape(bundle.read("history.html").decode())

    def action(self, message, **fields):
        return self.client.post(
            reverse("messenger:special_message_action", args=[message.chat_id, message.pk]),
            fields, HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

    def test_anonymous_export_and_unanswered_quiz_do_not_expose_private_fields(self):
        message = self.poll(quiz=True, correct_option=1, explanation="SECRET-EXPLANATION",
                            options=[{"text": "First", "voters": [self.alice.pk]},
                                     {"text": "Second", "voters": []}])
        content = self.exported(self.chat)
        self.assertNotIn('"voters":', content)
        self.assertNotIn('"correct_option":', content)
        self.assertNotIn("SECRET-EXPLANATION", content)
        self.assertIn('"votes": 1', content)
        response = self.action(message, action="vote", options="[0]")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["message"]["special"]["can_vote"])
        self.assertIn("SECRET-EXPLANATION", self.exported(self.chat))

    def test_quiz_vote_is_immutable_but_retry_is_safe(self):
        message = self.poll(quiz=True, correct_option=1)
        self.assertEqual(self.action(message, action="vote", options="[0]").status_code, 200)
        self.assertEqual(self.action(message, action="vote", options="[0]").status_code, 200)
        self.assertEqual(self.action(message, action="vote", options="[1]").status_code, 409)
        message.refresh_from_db()
        self.assertEqual(message.special_data["options"][0]["voters"], [self.bob.pk])
        self.assertEqual(message.special_data["options"][1]["voters"], [])
        page = self.client.get(reverse("messenger:chat", args=[self.chat.pk]))
        self.assertContains(page, 'data-can-vote="false"')
        self.assertContains(page, 'data-poll-option="0" disabled')

    def test_normal_poll_still_allows_changing_vote(self):
        message = self.poll()
        self.assertEqual(self.action(message, action="vote", options="[0]").status_code, 200)
        result = self.action(message, action="vote", options="[1]")
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json()["message"]["special"]["can_vote"])
        self.assertEqual(result.json()["message"]["special"]["selected_indexes"], [1])

    def test_admin_close_permission_matches_rendered_ui(self):
        message = self.poll(self.group)
        url = reverse("messenger:chat", args=[self.group.pk])
        self.assertNotContains(self.client.get(url), "data-poll-close")
        self.assertEqual(self.action(message, action="close").status_code, 403)
        self.client.force_login(self.admin)
        member = ChatParticipant.objects.get(chat=self.group, user=self.admin)
        member.admin_permissions = []
        member.save(update_fields=["admin_permissions"])
        self.assertNotContains(self.client.get(url), "data-poll-close")
        member.admin_permissions = ["edit_messages"]
        member.save(update_fields=["admin_permissions"])
        self.assertContains(self.client.get(url), "data-poll-close")
        response = self.action(message, action="close")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["message"]["special"]["can_close"])
        self.assertFalse(response.json()["message"]["special"]["can_vote"])

    def test_reconcile_hidden_cleared_expired_and_deleted_messages(self):
        def incoming(text):
            return Message.objects.create(chat=self.chat, sender=self.alice, text=text)
        cleared, hidden, expired, soft, live = [incoming(text) for text in
                                                ("cleared", "hidden", "expired", "soft", "live")]
        expired_id = expired.pk
        MessageHiddenForUser.objects.create(message=hidden, user=self.bob)
        ChatParticipant.objects.filter(chat=self.chat, user=self.bob).update(cleared_before_message_id=cleared.pk)
        Message.objects.filter(pk=expired.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        purge_expired_messages()
        Message.objects.filter(pk=soft.pk).update(is_deleted=True)
        foreign = Message.objects.create(chat=self.group, sender=self.alice, text="foreign")
        ids = [cleared.pk, hidden.pk, expired_id, soft.pk, live.pk, foreign.pk]
        url = reverse("messenger:poll_messages", args=[self.chat.pk])
        query = {"after": live.pk, "known_ids": ",".join(map(str, ids))}
        response = self.client.get(url, query)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["removed_ids"], sorted(set(ids)-{live.pk}))
        peer = Client()
        peer.force_login(self.alice)
        self.assertEqual(peer.get(url, query).json()["removed_ids"], sorted([expired_id, soft.pk, foreign.pk]))
        self.assertEqual(self.client.get(url, {**query, "account_id": self.alice.pk}).status_code, 409)
        self.assertEqual(self.client.get(url, {"known_ids": "1,invalid"}).status_code, 400)
        self.assertEqual(self.client.get(url, {"known_ids": ",".join(["1"]*101)}).status_code, 400)
