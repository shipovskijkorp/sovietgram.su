"""Archive folder, account isolation, stable pins and live scoped management."""
import json
from datetime import timedelta

from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from .models import Chat, ChatParticipant, Contact, Message
from .services import apply_archive_rules_on_new_message, get_or_create_direct_chat
from .views import _prepare_sidebar_chats


class ArchiveControlTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.net", "Password-1945!")
        cls.bob = User.objects.create_user("bob", "bob@example.net", "Password-1945!")
        cls.charlie = User.objects.create_user("charlie", "charlie@example.net", "Password-1945!")
        cls.outsider = User.objects.create_user("outsider", "other@example.net", "Password-1945!")
        cls.first = get_or_create_direct_chat(cls.alice, cls.bob)
        cls.second = get_or_create_direct_chat(cls.alice, cls.charlie)
        cls.foreign = get_or_create_direct_chat(cls.bob, cls.outsider)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.alice)
        self.url = reverse("messenger:chat_list_action")

    def member(self, chat, user=None):
        return ChatParticipant.objects.get(chat=chat, user=user or self.alice)

    def action(self, action, chats=(), folder="main", **extra):
        return self.client.post(self.url, {
            "action": action, "chat_ids": json.dumps([chat.pk for chat in chats]),
            "folder": folder, "account_id": str(self.alice.pk), **extra,
        })

    def ok(self, action, chats=(), folder="main", **extra):
        response = self.action(action, chats, folder, **extra)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_batch_archive_preserves_data_and_is_personal(self):
        message = Message.objects.create(chat=self.first, sender=self.bob, text="Unread")
        self.ok("pin", [self.first])
        self.ok("mute", [self.first], duration="8h")
        self.ok("mark_unread", [self.first])
        ChatParticipant.objects.filter(chat=self.first, user=self.alice).update(draft_text="Draft")
        prior = self.member(self.first)
        self.assertEqual(self.ok("archive", [self.first, self.second])["count"], 2)
        after = self.member(self.first)
        self.assertTrue(after.is_archived)
        self.assertFalse(after.is_pinned)
        self.assertEqual(after.pin_order, 0)
        self.assertEqual(after.draft_text, "Draft")
        self.assertEqual(after.marked_unread_at, prior.marked_unread_at)
        self.assertEqual(after.read_through_id, prior.read_through_id)
        self.assertEqual(after.muted_until, prior.muted_until)
        self.assertTrue(Message.objects.filter(pk=message.pk).exists())
        self.assertFalse(self.member(self.first, self.bob).is_archived)
        self.assertTrue(self.member(self.second).is_archived)
        self.assertEqual(self.action("archive", [self.first]).status_code, 409)
        self.ok("unarchive", [self.first, self.second], "archive")
        self.assertFalse(self.member(self.first).is_archived)
        self.assertTrue(self.member(self.first).notifications_muted)

    def test_pin_order_stays_stable_and_can_be_changed_in_archive(self):
        self.ok("archive", [self.first, self.second])
        self.ok("pin", [self.first], "archive")
        self.ok("pin", [self.second], "archive")
        self.assertEqual([chat.pk for chat in _prepare_sidebar_chats(self.alice, archived=True)],
                         [self.second.pk, self.first.pk])
        Message.objects.create(chat=self.first, sender=self.alice, text="More recent")
        self.assertEqual([chat.pk for chat in _prepare_sidebar_chats(self.alice, archived=True)],
                         [self.second.pk, self.first.pk])
        self.ok("move_up", [self.first], "archive")
        self.assertEqual([chat.pk for chat in _prepare_sidebar_chats(self.alice, archived=True)],
                         [self.first.pk, self.second.pk])
        self.ok("unarchive", [self.first], "archive")
        self.assertFalse(self.member(self.first).is_pinned)
        self.assertTrue(self.member(self.second).is_pinned)
        self.ok("pin", [self.first])
        self.assertTrue(self.member(self.first).is_pinned)
        self.assertEqual(self.member(self.first).pin_order, 1)
        self.assertEqual(self.action("move_up", [self.first, self.second]).status_code, 400)

    def test_auto_return_clears_only_old_folder_pin(self):
        self.ok("archive", [self.first, self.second])
        self.ok("pin", [self.first, self.second], "archive")
        self.ok("mute", [self.second], "archive")
        one = Message.objects.create(chat=self.first, sender=self.bob, text="Return")
        apply_archive_rules_on_new_message(self.first, one)
        two = Message.objects.create(chat=self.second, sender=self.charlie, text="Stay")
        apply_archive_rules_on_new_message(self.second, two)
        self.assertFalse(self.member(self.first).is_archived)
        self.assertFalse(self.member(self.first).is_pinned)
        self.assertEqual(self.member(self.first).pin_order, 0)
        self.assertTrue(self.member(self.second).is_archived)
        self.assertTrue(self.member(self.second).is_pinned)

    def test_read_all_archive_never_touches_main_or_other_accounts(self):
        self.ok("archive", [self.first])
        self.ok("mark_unread", [self.first], "archive")
        self.ok("mark_unread", [self.second])
        first = Message.objects.create(chat=self.first, sender=self.bob, text="Archived")
        second = Message.objects.create(chat=self.second, sender=self.charlie, text="Main")
        self.ok("archive_read_all")
        self.assertEqual(self.member(self.first).read_through_id, first.pk)
        self.assertIsNone(self.member(self.first).marked_unread_at)
        self.assertLess(self.member(self.second).read_through_id, second.pk)
        self.assertIsNotNone(self.member(self.second).marked_unread_at)
        self.assertEqual(self.member(self.first,self.bob).read_through_id, 0)
        # Non-JS fallback obeys exactly the same scope.
        later = Message.objects.create(chat=self.first, sender=self.bob, text="Later")
        response = self.client.post(reverse("messenger:mark_all_chats_read"), {"scope":"archive"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.member(self.first).read_through_id, later.pk)
        self.assertLess(self.member(self.second).read_through_id, second.pk)

    def test_access_validation_atomicity_and_csrf(self):
        self.assertEqual(self.action("archive", [self.first, self.foreign]).status_code, 404)
        self.assertFalse(self.member(self.first).is_archived)
        self.assertEqual(self.action("archive", [self.first], account_id=self.bob.pk).status_code, 409)
        self.assertEqual(self.action("archive", [self.first], folder="archive").status_code, 400)
        self.assertEqual(self.action("mute", [self.first], duration="invalid").status_code, 400)
        self.assertEqual(self.action("archive", chat_ids="[true]").status_code, 400)
        self.assertEqual(self.action("archive", chat_ids=json.dumps([self.first.pk]*201)).status_code, 400)
        ChatParticipant.objects.filter(chat=self.first,user=self.alice).update(is_hidden=True)
        self.assertEqual(self.action("archive", [self.first]).status_code, 404)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.alice)
        self.assertEqual(csrf.post(self.url, {"action":"archive_read_all","account_id":self.alice.pk}).status_code,403)
        self.assertEqual(self.client.get(self.url).status_code,405)

    def test_visibility_and_live_archive_counts(self):
        self.ok("archive", [self.first])
        self.ok("mute", [self.first], "archive")
        Message.objects.create(chat=self.first, sender=self.bob, text="New")
        self.ok("archive_visibility", hidden="0")
        self.alice.refresh_from_db()
        self.assertFalse(self.alice.archive_in_main_menu)
        snapshot = self.client.get(reverse("messenger:sidebar_snapshot"))
        self.assertContains(snapshot, 'data-archive-count="1"')
        self.assertContains(snapshot, 'data-archive-unread="1"')
        self.assertContains(snapshot, 'data-archive-loud-unread="false"')
        self.assertContains(snapshot, 'class="archive-folder-row"')
        self.assertContains(snapshot, "archive-folder-row__badge--muted")
        self.assertIn("no-store", snapshot["Cache-Control"])
        self.ok("archive_visibility", hidden="1")
        snapshot = self.client.get(reverse("messenger:sidebar_snapshot"))
        self.assertContains(snapshot, 'data-archive-hidden="true"')
        self.assertContains(snapshot, "archive-folder-row--concealed")
        self.assertTrue(self.member(self.first).is_archived)
        page = self.client.get(reverse("messenger:home"), {"archived":"1"})
        self.assertContains(page, 'id="archiveFolderMenuButton"')
        self.assertContains(page, 'id="archiveSelectionBar"')
        self.assertContains(page, 'data-batch-action="unarchive"')
        self.assertContains(page, 'name="scope" value="archive"')

    def test_archive_search_only_uses_request_users_archived_membership(self):
        self.ok("archive", [self.first])
        # Another participant archiving the second chat must not make it
        # part of Alice's own archive search.
        ChatParticipant.objects.filter(chat=self.second,user=self.charlie).update(is_archived=True)
        first = Message.objects.create(chat=self.first,sender=self.bob,text="UniqueSearch")
        second = Message.objects.create(chat=self.second,sender=self.charlie,text="UniqueSearch")
        url = reverse("messenger:global_search")
        result = self.client.get(url, {"q":"UniqueSearch", "archived":"1"}).json()
        self.assertEqual([item["id"] for item in result["messages"]], [first.pk])
        self.assertEqual(result["people"], [])
        self.assertEqual(result["communities"], [])
        self.assertEqual({item["id"] for item in self.client.get(url,{"q":"UniqueSearch"}).json()["messages"]},
                         {first.pk,second.pk})
        self.assertEqual([item["id"] for item in self.client.get(url,{"q":"bob","archived":"1"}).json()["chats"]],
                         [self.first.pk])

    def test_private_chat_menu_has_explicit_archive_and_pin_actions(self):
        page=self.client.get(reverse("messenger:chat",args=[self.first.pk]))
        self.assertContains(page,'name="archived" value="1"')
        self.assertContains(page,'name="pinned" value="1"')
        url=reverse("messenger:chat_action",args=[self.first.pk])
        for _ in range(2):
            response=self.client.post(url,{"action":"archive","archived":"1"},HTTP_X_REQUESTED_WITH="XMLHttpRequest")
            self.assertEqual(response.status_code,200)
            self.assertTrue(response.json()["is_archived"])
        for _ in range(2):
            response=self.client.post(url,{"action":"pin","pinned":"1"},HTTP_X_REQUESTED_WITH="XMLHttpRequest")
            self.assertEqual(response.status_code,200)
            self.assertTrue(response.json()["is_pinned"])
        self.assertTrue(self.member(self.first).is_archived)
        self.assertTrue(self.member(self.first).is_pinned)

    def test_unsolicited_community_additions_are_archived_but_contacts_are_not(self):
        self.alice.archive_unknown_chats=True
        self.alice.save(update_fields=["archive_unknown_chats"])
        self.charlie.archive_unknown_chats=True
        self.charlie.save(update_fields=["archive_unknown_chats"])
        Contact.objects.create(owner=self.charlie,user=self.bob)
        group=Chat.objects.create(type=Chat.Type.GROUP,title="Invitations")
        ChatParticipant.objects.create(chat=group,user=self.bob,role=ChatParticipant.Role.OWNER)
        self.client.force_login(self.bob)
        url=reverse("messenger:community_member_action",args=[group.pk])
        for target in (self.alice,self.charlie):
            response=self.client.post(url,{"action":"add","username":target.username},HTTP_X_REQUESTED_WITH="XMLHttpRequest")
            self.assertEqual(response.status_code,200,response.content)
        self.assertTrue(self.member(group,self.alice).is_archived)
        self.assertTrue(self.member(group,self.alice).notifications_muted)
        self.assertFalse(self.member(group,self.charlie).is_archived)
        self.assertFalse(self.member(group,self.charlie).notifications_muted)
