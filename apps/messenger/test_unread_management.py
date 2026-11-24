"""Manual unread markers are independent from actual message read cursors."""
from datetime import timedelta

from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from .models import Chat, ChatParticipant, Message, MessageHiddenForUser
from .services import get_or_create_direct_chat
from .views import _prepare_sidebar_chats


class UnreadManagementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.net", "Password-1945!")
        cls.bob = User.objects.create_user("bob", "bob@example.net", "Password-1945!")
        cls.charlie = User.objects.create_user("charlie", "charlie@example.net", "Password-1945!")
        cls.chat = get_or_create_direct_chat(cls.alice, cls.bob)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.alice)
        self.action_url = reverse("messenger:chat_action", args=[self.chat.pk])
        self.read_url = reverse("messenger:read_messages", args=[self.chat.pk])
        self.chat_url = reverse("messenger:chat", args=[self.chat.pk])
        self.all_url = reverse("messenger:mark_all_chats_read")

    def member(self, chat=None, user=None):
        return ChatParticipant.objects.get(chat=chat or self.chat, user=user or self.alice)

    def mark(self, action, chat=None):
        return self.client.post(reverse("messenger:chat_action", args=[(chat or self.chat).pk]), {
            "action": action,
        }, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def sidebar_chat(self):
        return next(item for item in _prepare_sidebar_chats(self.alice) if item.pk == self.chat.pk)

    def test_mark_unread_preserves_read_receipt_and_displays_reminder(self):
        message = Message.objects.create(chat=self.chat, sender=self.bob, text="Read")
        self.client.post(self.read_url, {"message_id": message.pk})
        self.assertEqual(self.mark("mark_unread").status_code, 200)
        membership = self.member()
        self.assertIsNotNone(membership.marked_unread_at)
        self.assertEqual(membership.read_through_id, message.pk)
        self.assertEqual(membership.last_read_message_id, message.pk)
        self.assertIsNone(self.member(user=self.bob).marked_unread_at)
        sidebar = self.sidebar_chat()
        self.assertTrue(sidebar.has_unread_ui)
        self.assertEqual(sidebar.unread_count_ui, 0)
        self.assertEqual(sidebar.unread_badge_count_ui, 1)
        response = self.client.get(reverse("messenger:home"))
        self.assertContains(response, 'data-chat-unread="true"')
        self.assertContains(response, "chat-row__unread--manual")
        slot = next(item for item in response.context["account_slots"] if item["is_current"])
        self.assertEqual(slot["unread_count"], 1)

        peer = Client()
        peer.force_login(self.bob)
        payload = peer.get(reverse("messenger:poll_messages", args=[self.chat.pk])).json()
        self.assertEqual(payload["other_last_read_id"], message.pk)

    def test_manual_marker_not_double_counted_with_real_unread_messages(self):
        self.mark("mark_unread")
        Message.objects.create(chat=self.chat, sender=self.bob, text="Unread one")
        Message.objects.create(chat=self.chat, sender=self.bob, text="Unread two")
        sidebar = self.sidebar_chat()
        self.assertEqual(sidebar.unread_count_ui, 2)
        self.assertEqual(sidebar.unread_badge_count_ui, 2)
        response = self.client.get(reverse("messenger:home"))
        slot = next(item for item in response.context["account_slots"] if item["is_current"])
        self.assertEqual(slot["unread_count"], 2)

    def test_opening_acknowledges_only_original_manual_marker(self):
        self.mark("mark_unread")
        token = self.member().marked_unread_at.isoformat()
        page = self.client.get(self.chat_url)
        self.assertContains(page, 'data-opened-marker="%s"' % token)
        self.assertIsNotNone(self.member().marked_unread_at)
        ChatParticipant.objects.filter(pk=self.member().pk).update(
            marked_unread_at=timezone.now() + timedelta(seconds=1),
        )
        self.assertTrue(self.client.post(self.read_url, {"message_id": 0, "opened_marker": token}).json()["marked_unread"])
        self.assertIsNotNone(self.member().marked_unread_at)
        fresh = self.member().marked_unread_at.isoformat()
        self.assertFalse(self.client.post(self.read_url, {"message_id": 0, "opened_marker": fresh}).json()["marked_unread"])
        self.assertIsNone(self.member().marked_unread_at)
        self.assertEqual(self.member().read_through_id, 0)

    def test_poll_and_normal_read_ack_do_not_clear_newer_manual_marker(self):
        self.mark("mark_unread")
        message = Message.objects.create(chat=self.chat, sender=self.bob, text="New")
        self.client.get(reverse("messenger:poll_messages", args=[self.chat.pk]))
        self.client.post(self.read_url, {"message_id": message.pk})
        self.assertIsNotNone(self.member().marked_unread_at)

    def test_mark_read_clears_marker_and_acks_latest_visible_incoming(self):
        self.mark("mark_unread")
        first = Message.objects.create(chat=self.chat, sender=self.bob, text="Visible")
        hidden = Message.objects.create(chat=self.chat, sender=self.bob, text="Hidden")
        MessageHiddenForUser.objects.create(message=hidden, user=self.alice)
        response = self.mark("mark_read")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.member().marked_unread_at)
        self.assertEqual(self.member().read_through_id, first.pk)
        self.assertFalse(self.sidebar_chat().has_unread_ui)

    def test_mark_all_includes_archive_excludes_hidden_and_other_users(self):
        archived = get_or_create_direct_chat(self.alice, self.charlie)
        hidden_chat = Chat.objects.create(type=Chat.Type.GROUP, title="Hidden group")
        hidden_member = ChatParticipant.objects.create(
            chat=hidden_chat, user=self.alice, is_hidden=True, marked_unread_at=timezone.now(),
        )
        ChatParticipant.objects.create(chat=hidden_chat, user=self.bob)
        hidden_message = Message.objects.create(chat=hidden_chat, sender=self.bob, text="Hidden")
        self.member(archived).chat.memberships.filter(user=self.alice).update(is_archived=True)
        one = Message.objects.create(chat=self.chat, sender=self.bob, text="One")
        two = Message.objects.create(chat=archived, sender=self.charlie, text="Two")
        self.mark("mark_unread")
        self.mark("mark_unread", archived)
        Message.objects.create(chat=self.chat, sender=self.alice, text="Peer unread")
        response = self.client.post(self.all_url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.member().read_through_id, one.pk)
        self.assertEqual(self.member(archived).read_through_id, two.pk)
        self.assertIsNone(self.member().marked_unread_at)
        self.assertIsNone(self.member(archived).marked_unread_at)
        self.assertEqual(self.member(user=self.bob).read_through_id, 0)
        hidden_member.refresh_from_db()
        self.assertEqual(hidden_member.read_through_id, 0)
        self.assertIsNotNone(hidden_member.marked_unread_at)
        self.assertTrue(Message.objects.filter(pk=hidden_message.pk).exists())
        self.assertEqual(self.client.get(self.all_url).status_code, 405)

    def test_mark_all_respects_history_visibility(self):
        group = Chat.objects.create(type=Chat.Type.GROUP, title="New member", history_visible_to_new_members=False)
        ChatParticipant.objects.create(chat=group, user=self.bob)
        prior = Message.objects.create(chat=group, sender=self.bob, text="Before join")
        Message.objects.filter(pk=prior.pk).update(created_at=timezone.now() - timedelta(days=1))
        member = ChatParticipant.objects.create(
            chat=group, user=self.alice, can_see_pre_join_history=False, marked_unread_at=timezone.now(),
        )
        self.assertEqual(self.client.post(self.all_url, HTTP_X_REQUESTED_WITH="XMLHttpRequest").status_code, 200)
        member.refresh_from_db()
        self.assertEqual(member.read_through_id, 0)
        self.assertIsNone(member.marked_unread_at)

    def test_read_management_requires_membership_and_csrf(self):
        self.client.force_login(self.charlie)
        self.assertEqual(self.mark("mark_unread").status_code, 404)
        self.assertEqual(self.mark("mark_read").status_code, 404)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.alice)
        self.assertEqual(client.post(self.action_url, {"action": "mark_unread"}).status_code, 403)
        self.assertEqual(client.post(self.all_url).status_code, 403)

    def test_filter_controls_and_row_menu_are_present(self):
        response = self.client.get(self.chat_url)
        for name in ("all", "unread", "group", "channel"):
            self.assertContains(response, 'data-chat-filter="%s"' % name)
        self.assertContains(response, 'data-chat-type="private"')
        self.assertContains(response, 'id="sidebarChatContext"')
        self.assertContains(response, 'id="markAllChatsReadForm"')
        self.assertContains(response, 'value="mark_read"')
        self.assertContains(response, 'value="mark_unread"')
