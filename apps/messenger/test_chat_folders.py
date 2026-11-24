"""Personal folders, live filter rules and archive integration regression tests."""
import json

from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import User
from .models import Chat, ChatFolder, ChatParticipant, Contact, Message
from .services import apply_archive_rules_on_new_message, get_or_create_direct_chat
from .views import _folder_sidebar_context


class ChatFolderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.net", "Password-1945!")
        cls.bob = User.objects.create_user("bob", "bob@example.net", "Password-1945!")
        cls.charlie = User.objects.create_user("charlie", "charlie@example.net", "Password-1945!")
        cls.first = get_or_create_direct_chat(cls.alice, cls.bob)
        cls.second = get_or_create_direct_chat(cls.alice, cls.charlie)
        cls.foreign = get_or_create_direct_chat(cls.bob, cls.charlie)
        Contact.objects.create(owner=cls.alice, user=cls.bob)
        cls.group = Chat.objects.create(type=Chat.Type.GROUP, title="Group")
        ChatParticipant.objects.create(chat=cls.group, user=cls.alice, role=ChatParticipant.Role.OWNER)
        ChatParticipant.objects.create(chat=cls.group, user=cls.bob)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.alice)
        self.url = reverse("messenger:chat_folders")
        self.manage_url = reverse("messenger:chat_list_action")

    def config(self, **fields):
        return {
            "name": "Work", "categories": [], "included": [], "excluded": [],
            "exclude_muted": False, "exclude_read": False, "exclude_archived": False,
            **fields,
        }

    def post(self, action, payload, account=None):
        return self.client.post(self.url, {
            "account_id": str(self.alice.pk if account is None else account),
            "action": action, "payload": json.dumps(payload),
        })

    def create(self, **fields):
        response = self.post("create", self.config(**fields))
        self.assertEqual(response.status_code, 200, response.content)
        return ChatFolder.objects.get(pk=response.json()["folder"]["id"])

    def folder_ids(self, folder):
        return [chat.pk for chat in _folder_sidebar_context(self.alice, raw_folder=folder.pk)["chats"]]

    def member(self, chat, user=None):
        return ChatParticipant.objects.get(chat=chat, user=user or self.alice)

    def action(self, folder, action, chats):
        return self.client.post(self.manage_url, {
            "account_id": str(self.alice.pk), "folder": "custom", "folder_id": folder.pk,
            "action": action, "chat_ids": json.dumps([chat.pk for chat in chats]),
        })

    def test_live_categories_and_manual_overrides(self):
        folder = self.create(categories=["contacts", "groups"], included=[self.second.pk],
                             excluded=[self.group.pk], exclude_archived=True, exclude_muted=True)
        ChatParticipant.objects.filter(chat=self.second, user=self.alice).update(is_archived=True, is_muted=True)
        self.assertEqual(set(self.folder_ids(folder)), {self.first.pk, self.second.pk})
        ChatParticipant.objects.filter(chat=self.first, user=self.alice).update(is_muted=True)
        self.assertEqual(self.folder_ids(folder), [self.second.pk])
        main = _folder_sidebar_context(self.alice)["chats"]
        self.assertNotIn(self.second.pk, [chat.pk for chat in main])
        self.assertTrue(self.member(self.second).is_archived)
        self.assertEqual(ChatFolder.objects.count(), 1)

    def test_unread_rule_and_badge_follow_actual_read_state(self):
        folder = self.create(categories=["contacts", "noncontacts"], exclude_read=True)
        self.assertEqual(self.folder_ids(folder), [])
        message = Message.objects.create(chat=self.first, sender=self.bob, text="Unread")
        context = _folder_sidebar_context(self.alice, raw_folder=folder.pk)
        self.assertEqual([chat.pk for chat in context["chats"]], [self.first.pk])
        self.assertEqual(context["folder_tabs"][0]["unread"], 1)
        response = self.client.post(reverse("messenger:read_messages", args=[self.first.pk]), {
            "message_id": message.pk, "account_id": self.alice.pk,
        })
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.folder_ids(folder), [])

    def test_folder_pins_are_independent_and_ordered(self):
        folder = self.create(included=[self.first.pk, self.second.pk])
        other = self.create(name="Other", included=[self.first.pk, self.second.pk])
        self.assertEqual(self.action(folder, "pin", [self.first]).status_code, 200)
        self.assertEqual(self.action(folder, "pin", [self.second]).status_code, 200)
        self.assertEqual(self.folder_ids(folder), [self.second.pk, self.first.pk])
        self.assertEqual(self.action(folder, "move_up", [self.first]).status_code, 200)
        self.assertEqual(self.folder_ids(folder), [self.first.pk, self.second.pk])
        self.assertFalse(self.member(self.first).is_pinned)
        other.refresh_from_db()
        self.assertEqual(other.pinned_chat_ids, [])
        self.assertEqual(self.action(folder, "unpin", [self.first]).status_code, 200)
        folder.refresh_from_db()
        self.assertEqual(folder.pinned_chat_ids, [self.second.pk])

    def test_search_sidebar_navigation_and_mark_folder_read_are_scoped(self):
        folder = self.create(included=[self.first.pk])
        one = Message.objects.create(chat=self.first, sender=self.bob, text="FolderSearch")
        two = Message.objects.create(chat=self.second, sender=self.charlie, text="FolderSearch")
        page = self.client.get(reverse("messenger:home"), {"folder": folder.pk})
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'id="chatFolderTabs"')
        self.assertContains(page, 'data-folder-id="%s"' % folder.pk)
        self.assertContains(page, 'href="%s?folder=%s"' % (reverse("messenger:chat", args=[self.first.pk]), folder.pk))
        self.assertEqual([chat.pk for chat in page.context["chats"]], [self.first.pk])
        snapshot = self.client.get(reverse("messenger:sidebar_snapshot"), {"folder": folder.pk})
        self.assertContains(snapshot, 'data-chat-id="%s"' % self.first.pk)
        self.assertNotContains(snapshot, 'data-chat-id="%s"' % self.second.pk)
        results = self.client.get(reverse("messenger:global_search"), {"q": "FolderSearch", "folder": folder.pk}).json()
        self.assertEqual([item["id"] for item in results["messages"]], [one.pk])
        self.assertIn(f"folder={folder.pk}", results["messages"][0]["url"])
        self.assertEqual(results["people"], [])
        self.assertEqual(results["communities"], [])
        response = self.client.post(reverse("messenger:mark_all_chats_read"), {"folder_id": folder.pk})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.member(self.first).read_through_id, one.pk)
        self.assertLess(self.member(self.second).read_through_id, two.pk)

    def test_permissions_and_revision_guard(self):
        folder = self.create(included=[self.first.pk])
        self.assertEqual(self.post("create", self.config(included=[self.foreign.pk])).status_code, 400)
        self.assertEqual(self.action(folder, "pin", [self.second]).status_code, 409)
        self.assertEqual(self.action(folder, "archive", [self.first, self.foreign]).status_code, 404)
        self.assertFalse(self.member(self.first).is_archived)
        self.assertEqual(self.post("delete", {"id": folder.pk, "revision": folder.revision + 1}).status_code, 409)
        self.assertEqual(self.post("delete", {"id": folder.pk, "revision": folder.revision}, self.bob.pk).status_code, 409)
        peer = Client()
        peer.force_login(self.bob)
        self.assertEqual(peer.get(self.url).json()["folders"], [])
        self.assertEqual(peer.get(reverse("messenger:home"), {"folder": folder.pk}).status_code, 404)
        self.assertEqual(peer.post(self.url, {
            "account_id": str(self.bob.pk), "action": "delete",
            "payload": json.dumps({"id": folder.pk, "revision": folder.revision}),
        }).status_code, 404)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.alice)
        self.assertEqual(csrf.post(self.url, {"account_id": self.alice.pk, "action": "create"}).status_code, 403)

    def test_edit_membership_reorder_delete_preserve_chat(self):
        folder = self.create(included=[self.first.pk])
        other = self.create(name="Other")
        response = self.post("membership", {"id": other.pk, "revision": other.revision,
                                            "chat_id": self.first.pk, "mode": "include"})
        self.assertEqual(response.status_code, 200, response.content)
        other.refresh_from_db()
        self.assertEqual(self.folder_ids(other), [self.first.pk])
        self.assertEqual(self.post("move_up", {"id": other.pk, "revision": other.revision}).status_code, 200)
        self.assertEqual(list(ChatFolder.objects.values_list("pk", flat=True)), [other.pk, folder.pk])
        folder.refresh_from_db()
        response = self.post("edit", self.config(id=folder.pk, revision=folder.revision, name="Renamed",
                                                 included=[self.second.pk]))
        self.assertEqual(response.status_code, 200, response.content)
        folder.refresh_from_db()
        self.assertEqual(folder.name, "Renamed")
        self.assertEqual(self.folder_ids(folder), [self.second.pk])
        message = Message.objects.create(chat=self.second, sender=self.charlie, text="Keep me")
        self.assertEqual(self.post("delete", {"id": folder.pk, "revision": folder.revision}).status_code, 200)
        self.assertTrue(Message.objects.filter(pk=message.pk).exists())
        self.assertTrue(ChatParticipant.objects.filter(chat=self.second, user=self.alice).exists())

    def test_archive_setting_keeps_only_chats_matching_a_folder(self):
        self.alice.keep_folder_chats_archived = True
        self.alice.save(update_fields=["keep_folder_chats_archived"])
        folder = self.create(categories=["contacts"], exclude_archived=False)
        ChatParticipant.objects.filter(user=self.alice, chat__in=[self.first, self.second]).update(is_archived=True)
        first = Message.objects.create(chat=self.first, sender=self.bob, text="In folder")
        second = Message.objects.create(chat=self.second, sender=self.charlie, text="Not in folder")
        apply_archive_rules_on_new_message(self.first, first)
        apply_archive_rules_on_new_message(self.second, second)
        self.assertTrue(self.member(self.first).is_archived)
        self.assertFalse(self.member(self.second).is_archived)
        folder.exclude_archived = True
        folder.save(update_fields=["exclude_archived"])
        third = Message.objects.create(chat=self.first, sender=self.bob, text="Not in folder now")
        apply_archive_rules_on_new_message(self.first, third)
        self.assertFalse(self.member(self.first).is_archived)

    def test_mixed_archived_and_main_chat_actions(self):
        folder = self.create(included=[self.first.pk, self.second.pk])
        ChatParticipant.objects.filter(chat=self.first, user=self.alice).update(is_archived=True)
        self.assertEqual(self.action(folder, "archive", [self.first, self.second]).status_code, 200)
        self.assertTrue(self.member(self.first).is_archived)
        self.assertTrue(self.member(self.second).is_archived)
        self.assertEqual(self.action(folder, "unarchive", [self.first, self.second]).status_code, 200)
        self.assertFalse(self.member(self.first).is_archived)
        self.assertFalse(self.member(self.second).is_archived)
        self.assertEqual(set(self.folder_ids(folder)), {self.first.pk, self.second.pk})
