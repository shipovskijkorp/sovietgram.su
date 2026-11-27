"""Search pagination, old chats, filters and visibility regressions."""
from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from .models import Chat, ChatMemberModeration, ChatParticipant, Message, MessageAttachment, MessageHiddenForUser, PinnedMessage
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

    def test_all_words_quotes_and_attachment_names_without_duplicate_results(self):
        ordered = Message.objects.create(chat=self.chat, sender=self.bob, text="annual report approved #work")
        reversed_words = Message.objects.create(chat=self.chat, sender=self.bob, text="report for annual review #work")
        mixed = Message.objects.create(chat=self.chat, sender=self.bob, text="annual update #work")
        for name in ("report.pdf", "report-copy.pdf"):
            MessageAttachment.objects.create(message=mixed, kind="file", file="test/"+name, original_name=name)
        missing = Message.objects.create(chat=self.chat, sender=self.bob, text="annual #workshop")
        hidden = Message.objects.create(chat=self.chat, sender=self.bob, text="annual report #work")
        MessageHiddenForUser.objects.create(message=hidden, user=self.alice)
        expired = Message.objects.create(chat=self.chat, sender=self.bob, text="annual report #work")
        Message.objects.filter(pk=expired.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        foreign = get_or_create_direct_chat(self.other, self.bob)
        Message.objects.create(chat=foreign, sender=self.bob, text="annual report #work")
        group = Chat.objects.create(type=Chat.Type.GROUP, title="Banned")
        ChatParticipant.objects.create(chat=group, user=self.alice)
        ChatMemberModeration.objects.create(chat=group, user=self.alice, banned=True)
        Message.objects.create(chat=group, sender=self.bob, text="annual report #work")
        for url, key in ((self.global_url, "messages"), (self.chat_url, "results")):
            def ids(query):
                response = self.client.get(url, {"q": query})
                self.assertEqual(response.status_code, 200, response.content)
                return [item["id"] for item in response.json()[key]]
            self.assertEqual(ids("report annual"), [mixed.pk, reversed_words.pk, ordered.pk])
            self.assertEqual(ids('"annual report"'), [ordered.pk])
            self.assertEqual(ids("annual #work"), [mixed.pk, reversed_words.pk, ordered.pk])
            self.assertNotIn(missing.pk, ids("annual #work"))
            self.assertEqual(ids("report.pdf annual"), [mixed.pk])
            self.assertEqual(self.client.get(url, {"q":" ".join("term"+str(i) for i in range(13))}).status_code, 400)

    def test_date_target_uses_first_visible_message_and_requires_account(self):
        from datetime import datetime, UTC
        day = datetime(2025, 6, 1, 12, tzinfo=UTC)
        rows = [Message.objects.create(chat=self.chat, sender=self.bob, text=f"dated {n}") for n in range(5)]
        Message.objects.filter(pk__in=[row.pk for row in rows]).update(created_at=day)
        MessageHiddenForUser.objects.create(user=self.alice, message=rows[0])
        Message.objects.filter(pk=rows[1].pk).update(is_deleted=True)
        Message.objects.filter(pk=rows[2].pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        url = reverse("messenger:history_target", args=[self.chat.pk])
        args = {"mode":"date", "date":"2025-06-01", "account_id":self.alice.pk}
        response = self.client.get(url, args)
        self.assertEqual(response.json()["message_id"], rows[3].pk)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIsNone(self.client.get(url, {**args, "date":"2025-06-02"}).json()["message_id"])
        self.assertEqual(self.client.get(url, {**args, "date":"2025-02-30"}).status_code, 400)
        self.assertEqual(self.client.get(url, {**args, "account_id":self.bob.pk}).status_code, 409)
        outsider = get_or_create_direct_chat(self.bob, self.other)
        self.assertEqual(self.client.get(reverse("messenger:history_target", args=[outsider.pk]), args).status_code, 404)
        self.assertEqual(ChatParticipant.objects.get(chat=self.chat, user=self.alice).read_through_id, 0)

    def test_unread_mention_target_uses_markdown_tokens_and_visibility(self):
        def message(text, sender=None):
            return Message.objects.create(chat=self.chat, sender=sender or self.bob, text=text)

        already_read = message("@alice")
        ChatParticipant.objects.filter(chat=self.chat, user=self.alice).update(read_through_id=already_read.pk)
        message("@alice", self.alice)
        message("@alice_other")
        message("mail@alice.net")
        message("`@alice`")
        message("[@alice](https://example.net)")
        hidden = message("@alice")
        MessageHiddenForUser.objects.create(user=self.alice, message=hidden)
        expired = message("@alice")
        Message.objects.filter(pk=expired.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        first = message("Привет, @ALICE!")
        second = message("Ещё раз @alice")
        url = reverse("messenger:history_target", args=[self.chat.pk])
        args = {"mode":"mention", "account_id":self.alice.pk}
        self.assertEqual(self.client.get(url, args).json()["message_id"], first.pk)
        self.assertEqual(self.client.get(url, {**args, "after":first.pk}).json()["message_id"], second.pk)
        self.assertIsNone(self.client.get(url, {**args, "after":second.pk}).json()["message_id"])
        self.assertEqual(self.client.get(url, {**args, "after":-1}).status_code, 400)
        self.assertEqual(ChatParticipant.objects.get(chat=self.chat, user=self.alice).read_through_id, already_read.pk)

    def test_mention_scan_can_continue_past_bounded_batch(self):
        Message.objects.bulk_create([Message(chat=self.chat, sender=self.bob, text="`@alice`") for _ in range(251)])
        target = Message.objects.create(chat=self.chat, sender=self.bob, text="@alice")
        url = reverse("messenger:history_target", args=[self.chat.pk])
        args = {"mode":"mention", "account_id":self.alice.pk}
        result = self.client.get(url, args).json()
        self.assertIsNone(result["message_id"])
        self.assertTrue(result["next_after"])
        result = self.client.get(url, {**args, "after":result["next_after"]}).json()
        self.assertEqual(result["message_id"], target.pk)

    def test_link_and_pinned_search_filters(self):
        plain = Message.objects.create(chat=self.chat, sender=self.bob, text="plain")
        link = Message.objects.create(chat=self.chat, sender=self.bob, text="See https://example.net/page")
        second = Message.objects.create(chat=self.chat, sender=self.alice, text="www.example.net")
        hidden = Message.objects.create(chat=self.chat, sender=self.bob, text="https://hidden.example.net")
        MessageHiddenForUser.objects.create(user=self.alice, message=hidden)
        for item in (plain, link, hidden):
            PinnedMessage.objects.create(chat=self.chat, message=item, pinned_by=self.alice)
        ids = lambda params: [row["id"] for row in self.client.get(self.chat_url, params).json()["results"]]
        self.assertEqual(ids({"kind":"link"}), [second.pk, link.pk])
        self.assertEqual(ids({"kind":"link", "sender":"bob"}), [link.pk])
        self.assertEqual(ids({"kind":"pinned"}), [link.pk, plain.pk])
        self.assertEqual(ids({"kind":"pinned", "q":"plain"}), [plain.pk])
        self.assertEqual(self.client.get(self.chat_url, {"kind":"pinned", "account_id":self.bob.pk}).status_code, 409)
