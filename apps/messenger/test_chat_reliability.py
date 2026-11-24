"""Regression tests for cursor paging, read acknowledgement and send retries."""
import json
import tempfile
from uuid import uuid4

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from .models import Chat, ChatParticipant, Message, MessageAttachment, MessageHiddenForUser, MessageSendReceipt
from .services import get_or_create_direct_chat


class ChatReliabilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.net", "Password-1945!")
        cls.bob = User.objects.create_user("bob", "bob@example.net", "Password-1945!")
        cls.outsider = User.objects.create_user("outsider", "other@example.net", "Password-1945!")
        cls.chat = get_or_create_direct_chat(cls.alice, cls.bob)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.alice)
        self.history_url = reverse("messenger:message_history", args=[self.chat.pk])
        self.read_url = reverse("messenger:read_messages", args=[self.chat.pk])
        self.poll_url = reverse("messenger:poll_messages", args=[self.chat.pk])
        self.send_url = reverse("messenger:send_message", args=[self.chat.pk])

    def membership(self):
        return ChatParticipant.objects.get(chat=self.chat, user=self.alice)

    def incoming(self, text="Incoming"):
        return Message.objects.create(chat=self.chat, sender=self.bob, text=text)

    def send(self, data, url=None):
        return self.client.post(url or self.send_url, data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_history_pages_are_contiguous_without_duplicates(self):
        for index in range(165):
            self.incoming(str(index))
        all_ids = list(Message.objects.filter(chat=self.chat).order_by("id").values_list("id", flat=True))
        latest = self.client.get(self.history_url).json()
        self.assertEqual([item["id"] for item in latest["messages"]], all_ids[-100:])
        self.assertTrue(latest["has_older"])
        self.assertFalse(latest["has_newer"])
        older = self.client.get(self.history_url, {"before": latest["messages"][0]["id"]}).json()
        self.assertEqual([item["id"] for item in older["messages"]], all_ids[15:65])
        earliest = self.client.get(self.history_url, {"before": older["messages"][0]["id"]}).json()
        self.assertEqual([item["id"] for item in earliest["messages"]], all_ids[:15])
        self.assertFalse(earliest["has_older"])
        around = self.client.get(self.history_url, {"around": all_ids[5]}).json()
        self.assertTrue(around["has_newer"])
        next_page = self.client.get(self.history_url, {"after": around["messages"][-1]["id"]}).json()
        self.assertEqual([item["id"] for item in next_page["messages"]], all_ids[56:106])
        self.assertEqual(self.membership().read_through_id, 0)

    def test_history_respects_visibility_and_membership(self):
        hidden = self.incoming("hidden")
        visible = self.incoming("visible")
        deleted = self.incoming("deleted")
        deleted.is_deleted = True
        deleted.save(update_fields=["is_deleted"])
        MessageHiddenForUser.objects.create(message=hidden, user=self.alice)
        self.assertEqual([item["id"] for item in self.client.get(self.history_url).json()["messages"]], [visible.pk])
        self.assertEqual(self.client.post(self.read_url, {"message_id": hidden.pk}).status_code, 404)
        self.assertEqual(self.client.post(self.read_url, {"message_id": deleted.pk}).status_code, 404)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.history_url).status_code, 404)
        self.assertEqual(self.client.post(self.read_url, {"message_id": visible.pk}).status_code, 404)

    def test_open_poll_and_sending_do_not_acknowledge_incoming(self):
        incoming = self.incoming()
        page = self.client.get(reverse("messenger:chat", args=[self.chat.pk]))
        self.assertContains(page, 'data-unread-anchor="%s"' % incoming.pk)
        self.assertEqual(self.client.get(self.poll_url, {"after": 0}).status_code, 200)
        self.assertEqual(self.membership().read_through_id, 0)
        self.assertEqual(self.send({"text": "Reply", "client_message_id": str(uuid4())}).status_code, 200)
        self.assertEqual(self.membership().read_through_id, 0)

    def test_read_cursor_is_monotonic_and_survives_deletion(self):
        first, second = self.incoming("one"), self.incoming("two")
        self.assertEqual(self.client.post(self.read_url, {"message_id": second.pk}).json()["own_last_read_id"], second.pk)
        self.assertEqual(self.client.post(self.read_url, {"message_id": first.pk}).json()["own_last_read_id"], second.pk)
        cursor = second.pk
        second.delete()
        membership = self.membership()
        self.assertIsNone(membership.last_read_message_id)
        self.assertEqual(membership.read_through_id, cursor)
        peer = Client()
        peer.force_login(self.bob)
        self.assertEqual(peer.get(self.poll_url, {"after": 0}).json()["other_last_read_id"], cursor)

    def test_read_endpoint_rejects_own_and_foreign_messages(self):
        own = Message.objects.create(chat=self.chat, sender=self.alice, text="own")
        foreign_chat = get_or_create_direct_chat(self.alice, self.outsider)
        foreign = Message.objects.create(chat=foreign_chat, sender=self.outsider, text="foreign")
        for message in (own, foreign):
            self.assertEqual(self.client.post(self.read_url, {"message_id": message.pk}).status_code, 404)
        self.assertEqual(self.client.get(self.read_url).status_code, 405)
        self.assertEqual(self.client.post(self.read_url, {"message_id": "invalid"}).status_code, 400)
        self.assertEqual(self.membership().read_through_id, 0)

    def test_text_retry_is_idempotent_and_changed_body_is_rejected(self):
        key = str(uuid4())
        first = self.send({"text": "one", "client_message_id": key})
        self.assertEqual(first.status_code, 200)
        retry = self.send({"text": "one", "client_message_id": key})
        self.assertEqual(retry.status_code, 200)
        self.assertTrue(retry.json()["replayed"])
        self.assertEqual(first.json()["message"]["id"], retry.json()["message"]["id"])
        self.assertEqual(Message.objects.filter(chat=self.chat).count(), 1)
        self.assertEqual(self.send({"text": "changed", "client_message_id": key}).status_code, 409)
        self.assertEqual(self.send({"text": "one", "client_message_id": str(uuid4())}).status_code, 200)
        self.assertEqual(Message.objects.filter(chat=self.chat).count(), 2)

    def test_retry_after_hard_deletion_never_recreates_message(self):
        key = str(uuid4())
        original = self.send({"text": "one", "client_message_id": key})
        Message.objects.get(pk=original.json()["message"]["id"]).delete()
        self.assertEqual(self.send({"text": "one", "client_message_id": key}).status_code, 409)
        self.assertFalse(Message.objects.filter(chat=self.chat).exists())
        self.assertIsNone(MessageSendReceipt.objects.get(sender=self.alice, client_id=key).message_id)

    def test_failed_send_does_not_consume_key(self):
        key = str(uuid4())
        self.assertEqual(self.send({"text": "", "client_message_id": key}).status_code, 400)
        self.assertFalse(MessageSendReceipt.objects.filter(client_id=key).exists())
        self.assertEqual(self.send({"text": "valid", "client_message_id": key}).status_code, 200)

    def test_attachment_retry_keeps_one_attachment_and_checks_file_bytes(self):
        key = str(uuid4())
        with tempfile.TemporaryDirectory() as folder, override_settings(MEDIA_ROOT=folder):
            def upload(content):
                return self.send({
                    "text": "caption", "attachment_mode": "file", "client_message_id": key,
                    "attachments": SimpleUploadedFile("test.txt", content, content_type="text/plain"),
                })
            first = upload(b"abc")
            self.assertEqual(first.status_code, 200)
            second = upload(b"abc")
            self.assertEqual(second.status_code, 200)
            self.assertEqual(first.json()["message"]["id"], second.json()["message"]["id"])
            self.assertEqual(MessageAttachment.objects.filter(message__chat=self.chat).count(), 1)
            self.assertEqual(upload(b"xyz").status_code, 409)

    def test_special_and_forward_retries_reuse_messages(self):
        special_url = reverse("messenger:send_special_message", args=[self.chat.pk])
        data = {
            "special_type": "location",
            "payload": json.dumps({"latitude": 54.0, "longitude": 25.0, "label": "Place"}),
            "client_message_id": str(uuid4()),
        }
        first = self.send(data, special_url)
        self.assertEqual(first.status_code, 200, first.content)
        second = self.send(data, special_url)
        self.assertEqual(first.json()["message"]["id"], second.json()["message"]["id"])
        source = self.incoming()
        forward_url = reverse("messenger:forward_message", args=[self.chat.pk, source.pk])
        forward_data = {"target_chat_id": "saved", "client_message_id": str(uuid4())}
        first = self.send(forward_data, forward_url)
        self.assertEqual(first.status_code, 200, first.content)
        second = self.send(forward_data, forward_url)
        self.assertEqual(first.json()["message"]["id"], second.json()["message"]["id"])
        self.assertEqual(first.json()["target_chat_id"], second.json()["target_chat_id"])

    def test_group_and_channel_read_ack_refreshes_real_sidebar_unread_count(self):
        for kind in (Chat.Type.GROUP, Chat.Type.CHANNEL):
            with self.subTest(kind=kind):
                chat = Chat.objects.create(type=kind, title="Read regression")
                ChatParticipant.objects.create(chat=chat, user=self.bob, role=ChatParticipant.Role.OWNER)
                member = ChatParticipant.objects.create(chat=chat, user=self.alice)
                one = Message.objects.create(chat=chat, sender=self.bob, text="First")
                two = Message.objects.create(chat=chat, sender=self.bob, text="Second")
                url = reverse("messenger:read_messages", args=[chat.pk])
                page = self.client.get(reverse("messenger:chat", args=[chat.pk]))
                self.assertContains(page, 'data-message-own="false"')
                self.assertContains(page, 'data-unread-anchor="%s"' % one.pk)
                self.assertContains(page, "js/read-ack.js")
                member.refresh_from_db()
                self.assertEqual(member.read_through_id, 0)
                response = self.client.post(url, {
                    "account_id": self.alice.pk, "message_id": one.pk,
                }, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(response.json()["own_last_read_id"], one.pk)
                self.assertEqual(response.json()["account_id"], self.alice.pk)
                self.assertIn("no-store", response["Cache-Control"])
                home = self.client.get(reverse("messenger:home"))
                current = next(item for item in home.context["chats"] if item.pk == chat.pk)
                self.assertEqual(current.unread_count_ui, 1)
                response = self.client.post(url, {
                    "account_id": self.alice.pk, "message_id": two.pk,
                })
                self.assertEqual(response.json()["own_last_read_id"], two.pk)
                member.refresh_from_db()
                self.assertEqual(member.read_through_id, two.pk)
                home = self.client.get(reverse("messenger:home"))
                current = next(item for item in home.context["chats"] if item.pk == chat.pk)
                self.assertEqual(current.unread_count_ui, 0)
                self.assertFalse(current.has_unread_ui)

    def test_stale_tab_cannot_acknowledge_messages_for_switched_account(self):
        incoming = self.incoming()
        response = self.client.post(self.read_url, {
            "account_id": self.bob.pk, "message_id": incoming.pk,
        })
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.membership().read_through_id, 0)
