"""Explicit account deletion requires reauthentication and confirmation."""
from django.contrib.auth import SESSION_KEY
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from apps.messenger.models import Chat, ChatParticipant, Message
from apps.messenger.services import get_or_create_direct_chat
from .models import User


class DeleteAccountTests(TestCase):
    password = "Deletion-test-1945!"

    def setUp(self):
        cache.clear()
        self.alice = User.objects.create_user("delete_alice", "delete-alice@example.com", self.password)
        self.bob = User.objects.create_user("delete_bob", "delete-bob@example.com", self.password)
        self.url = reverse("accounts:delete_account")

    def data(self, user=None, **overrides):
        user = user or self.alice
        return {
            "account_id": user.pk, "username": user.username,
            "password": self.password, "confirm": "on", **overrides,
        }

    def test_requires_authentication_and_get_is_non_destructive(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(self.client.post(self.url, self.data()).status_code, 302)
        self.client.force_login(self.alice)
        response = self.client.get(self.url)
        self.assertContains(response, "Удалить аккаунт навсегда?")
        self.assertContains(response, "у обоих собеседников")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertTrue(User.objects.filter(pk=self.alice.pk).exists())

    def test_settings_exposes_delete_action(self):
        self.client.force_login(self.alice)
        self.assertContains(self.client.get(reverse("messenger:home")), self.url)
        self.assertContains(self.client.get(reverse("messenger:home")), "Удалить аккаунт сейчас")

    def test_wrong_password_name_missing_consent_and_stale_account_are_rejected(self):
        self.client.force_login(self.alice)
        for changes in (
            {"password": "incorrect"}, {"username": self.bob.username},
            {"confirm": ""}, {"account_id": self.bob.pk},
        ):
            with self.subTest(changes=changes):
                response = self.client.post(self.url, self.data(**changes))
                self.assertEqual(response.status_code, 200)
                self.assertTrue(User.objects.filter(pk=self.alice.pk).exists())
                self.assertTrue(User.objects.filter(pk=self.bob.pk).exists())

    def test_delete_uses_lifecycle_and_revokes_old_login(self):
        direct = get_or_create_direct_chat(self.alice, self.bob)
        group = Chat.objects.create(type=Chat.Type.GROUP, title="Keep group")
        ChatParticipant.objects.create(chat=group, user=self.alice, role=ChatParticipant.Role.OWNER)
        ChatParticipant.objects.create(chat=group, user=self.bob, role=ChatParticipant.Role.ADMIN)
        Message.objects.create(chat=group, sender=self.alice, text="remove")
        Message.objects.create(chat=group, sender=self.bob, text="keep")
        another_browser = Client()
        another_browser.force_login(self.alice)
        self.client.force_login(self.alice)

        response = self.client.post(self.url, self.data())
        self.assertRedirects(response, reverse("accounts:login"))
        self.assertFalse(User.objects.filter(pk=self.alice.pk).exists())
        self.assertFalse(Chat.objects.filter(pk=direct.pk).exists())
        self.assertEqual(list(group.messages.values_list("text", flat=True)), ["keep"])
        self.assertEqual(ChatParticipant.objects.get(chat=group, user=self.bob).role, ChatParticipant.Role.OWNER)
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertEqual(another_browser.get(reverse("messenger:home")).status_code, 302)

    def test_delete_preserves_another_saved_account(self):
        self.client.force_login(self.bob)
        self.assertRedirects(self.client.post(reverse("accounts:add_account"), {
            "username": self.alice.username, "password": self.password,
        }), reverse("messenger:home"))
        self.assertEqual(int(self.client.session[SESSION_KEY]), self.alice.pk)
        self.assertRedirects(self.client.post(self.url, self.data()), reverse("messenger:home"))
        self.assertEqual(int(self.client.session[SESSION_KEY]), self.bob.pk)
        self.assertFalse(User.objects.filter(pk=self.alice.pk).exists())
        self.assertEqual(
            [int(item["user_id"]) for item in self.client.session["sovietgram_accounts_v1"]],
            [self.bob.pk],
        )

    def test_delete_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.alice)
        self.assertEqual(client.get(self.url).status_code, 200)
        self.assertEqual(client.post(self.url, self.data()).status_code, 403)
        self.assertTrue(User.objects.filter(pk=self.alice.pk).exists())
