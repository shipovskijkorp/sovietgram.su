"""Search pagination, old chats, filters and visibility regressions."""
from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from .models import Chat, ChatParticipant, Message, MessageAttachment, MessageHiddenForUser
from .services import get_or_create_direct_chat


class SearchPaginationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.net", "Password-1945!")
        cls.bob = User.objects.create_user("bob", "bob@example.net", "Password-1945!")
        cls.other = User.objects.create_user("other", "other@example.net", "Password-1945!")
        cls.chat = get_or_create_direct_chat(cls.alice, cls.bob)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.alice)
        self.global_url = reverse("messenger:global_search")
        self.chat_url = reverse("messenger:search_messages", args=[self.chat.pk])

    def test_old_chat_name_is_found_before_limit_and_not_listed_as_new_community(self):
        group = Chat.objects.create(type=Chat.Type.GROUP, title="Старый Архив", username="old_group")
        ChatParticipant.objects.create(chat=group, user=self.alice, role="member")
        for i in range(125):
            newer = Chat.objects.create(type=Chat.Type.GROUP, title=f"Recent {i}")
            ChatParticipant.objects.create(chat=newer, user=self.alice, role="member")
        result = self.client.get(self.global_url, {"q": "старый архив"}).json()
        self.assertIn(group.pk, [item["id"] for item in result["chats"]])
        result = self.client.get(self.global_url, {"q": "old_group"}).json()
        self.assertIn(group.pk, [item["id"] for item in result["chats"]])
        self.assertNotIn(group.pk, [item["id"] for item in result["communities"]])
        result = self.client.get(self.global_url, {"q": "bob"}).json()
        self.assertIn(self.chat.pk, [item["id"] for item in result["chats"]])

    def test_pagination_is_stable_and_excludes_hidden_and_foreign_messages(self):
        messages = [Message.objects.create(chat=self.chat, sender=self.bob, text="needle") for _ in range(72)]
        MessageHiddenForUser.objects.create(message=messages[5], user=self.alice)
        Message.objects.filter(pk=messages[10].pk).update(is_deleted=True)
        other_chat = get_or_create_direct_chat(self.bob, self.other)
        Message.objects.create(chat=other_chat, sender=self.bob, text="needle")
        expected = [m.pk for m in reversed(messages) if m.pk not in {messages[5].pk, messages[10].pk}]
        for url, key, page_size in ((self.global_url, "messages", 18), (self.chat_url, "results", 50)):
            first = self.client.get(url, {"q": "needle"}).json()
            self.assertEqual(len(first[key]), page_size)
            # A message arriving during paging must not shift the cursor.
            newer = Message.objects.create(chat=self.chat, sender=self.bob, text="needle")
            got = [item["id"] for item in first[key]]
            cursor = first["next_before"]
            while cursor:
                page = self.client.get(url, {"q": "needle", "before": cursor, "messages_only": "1"}).json()
                got.extend(item["id"] for item in page[key])
                cursor = page["next_before"]
                if key == "messages":
                    self.assertEqual(page["chats"], [])
            self.assertEqual(got, expected)
            newer.delete()

    def test_filters_work_without_query_and_can_be_combined(self):
        old = Message.objects.create(chat=self.chat, sender=self.bob, text="report old")
        Message.objects.filter(pk=old.pk).update(created_at=timezone.now()-timedelta(days=10))
        target = Message.objects.create(chat=self.chat, sender=self.bob, text="report new")
        MessageAttachment.objects.create(message=target, kind="file", file="test/report.txt", original_name="report.txt")
        own = Message.objects.create(chat=self.chat, sender=self.alice, text="report own")
        MessageAttachment.objects.create(message=own, kind="file", file="test/own.txt", original_name="own.txt")
        Message.objects.create(chat=self.chat, sender=self.bob, text="text only")
        filters = {"sender": "@bob", "kind": "file", "date_from": timezone.localdate().isoformat()}
        for query in ("", "report"):
            response = self.client.get(self.chat_url, {**filters, "q": query})
            self.assertEqual(response.status_code, 200)
            self.assertEqual([item["id"] for item in response.json()["results"]], [target.pk])
        self.assertEqual(self.client.get(self.chat_url, {"date_from": "2026-02-30"}).status_code, 400)
        self.assertEqual(self.client.get(self.chat_url, {"kind": "unknown"}).status_code, 400)
        for url in (self.global_url, self.chat_url):
            self.assertEqual(self.client.get(url, {"q": "report", "before": "-1"}).status_code, 400)
