from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.messenger.models import Chat, ChatParticipant, Message
from apps.messenger.services import get_or_create_direct_chat, purge_expired_messages

from .models import User, UserBlock
from .privacy import privacy_allows, set_privacy_rule


class PrivacySettingsTests(TestCase):
    password = "Sovietgram-test-1945"

    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice_privacy",
            email="alice-privacy@example.com",
            password=self.password,
            bio="Секретная биография",
            birthday="2000-01-02",
        )
        self.bob = User.objects.create_user(
            username="bob_privacy",
            email="bob-privacy@example.com",
            password=self.password,
        )

    def test_privacy_rule_is_saved_with_exceptions(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("accounts:settings"),
            {
                "action": "privacy_rule",
                "key": "messages",
                "option": "nobody",
                "always": f"[{self.bob.pk}]",
                "never": "[]",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.alice.refresh_from_db()
        self.assertTrue(privacy_allows(self.alice, self.bob, "messages"))

        response = self.client.post(
            reverse("accounts:settings"),
            {
                "action": "privacy_rule",
                "key": "messages",
                "option": "everyone",
                "always": "[]",
                "never": f"[{self.bob.pk}]",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.alice.refresh_from_db()
        self.assertFalse(privacy_allows(self.alice, self.bob, "messages"))

    def test_messages_privacy_blocks_new_direct_chat(self):
        set_privacy_rule(self.alice, "messages", "nobody")
        self.client.force_login(self.bob)
        response = self.client.post(
            reverse("messenger:start_chat", args=[self.alice.username]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            Chat.objects.filter(
                direct_key=f"{min(self.alice.pk, self.bob.pk)}:{max(self.alice.pk, self.bob.pk)}"
            ).exists()
        )

    def test_block_prevents_messages_in_existing_chat(self):
        chat = get_or_create_direct_chat(self.alice, self.bob)
        UserBlock.objects.create(blocker=self.alice, blocked=self.bob)

        self.client.force_login(self.bob)
        response = self.client.post(
            reverse("messenger:send_message", args=[chat.pk]),
            {"text": "Попытка связи"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(chat.messages.exists())

    def test_profile_privacy_hides_bio_and_birthday(self):
        set_privacy_rule(self.alice, "bio", "nobody")
        set_privacy_rule(self.alice, "birthday", "nobody")

        self.client.force_login(self.bob)
        response = self.client.get(
            reverse("accounts:public_profile", args=[self.alice.username]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["bio"], "")
        self.assertEqual(payload["birthday"], "")
        self.assertEqual(payload["birthday_display"], "")

    def test_invite_privacy_is_enforced_by_member_action(self):
        group = Chat.objects.create(type=Chat.Type.GROUP, title="Закрытая группа")
        ChatParticipant.objects.create(
            chat=group,
            user=self.alice,
            role=ChatParticipant.Role.OWNER,
        )
        set_privacy_rule(self.bob, "invites", "nobody")

        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("messenger:community_member_action", args=[group.pk]),
            {"action": "add", "username": self.bob.username},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            ChatParticipant.objects.filter(chat=group, user=self.bob).exists()
        )

    def test_block_and_unblock_actions_update_block_list(self):
        self.client.force_login(self.alice)
        blocked = self.client.post(
            reverse("accounts:settings"),
            {"action": "block", "username": self.bob.username},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(blocked.status_code, 200)
        self.assertTrue(
            UserBlock.objects.filter(blocker=self.alice, blocked=self.bob).exists()
        )

        unblocked = self.client.post(
            reverse("accounts:settings"),
            {"action": "unblock", "username": self.bob.username},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(unblocked.status_code, 200)
        self.assertFalse(
            UserBlock.objects.filter(blocker=self.alice, blocked=self.bob).exists()
        )

    def test_active_sessions_state_contains_current_session(self):
        self.client.force_login(self.alice)
        response = self.client.get(
            reverse("accounts:settings"),
            {"action": "privacy_state"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        sessions = response.json()["sessions"]
        self.assertTrue(sessions)
        self.assertTrue(any(item["current"] for item in sessions))

    def test_default_auto_delete_is_applied_to_new_direct_chat(self):
        self.alice.default_auto_delete_seconds = 86400
        self.alice.save(update_fields=["default_auto_delete_seconds"])
        chat = get_or_create_direct_chat(self.alice, self.bob)
        self.assertEqual(chat.auto_delete_seconds, 86400)

        message = Message.objects.create(
            chat=chat,
            sender=self.alice,
            text="Временное сообщение",
        )
        self.assertIsNotNone(message.expires_at)
        self.assertGreater(message.expires_at, timezone.now())

        message.expires_at = timezone.now() - timedelta(seconds=1)
        message.save(update_fields=["expires_at"])
        self.assertEqual(purge_expired_messages(), 1)
        self.assertFalse(Message.objects.filter(pk=message.pk).exists())

    def test_inactivity_and_auto_delete_settings_are_saved(self):
        self.client.force_login(self.alice)
        inactivity = self.client.post(
            reverse("accounts:settings"),
            {"setting": "delete_after_inactive_days", "value": "30"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(inactivity.status_code, 200)
        self.assertEqual(inactivity.json()["label"], "1 месяц")

        auto_delete = self.client.post(
            reverse("accounts:settings"),
            {"setting": "default_auto_delete_seconds", "value": "604800"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(auto_delete.status_code, 200)
        self.assertEqual(auto_delete.json()["label"], "1 неделя")

        self.alice.refresh_from_db()
        self.assertEqual(self.alice.delete_after_inactive_days, 30)
        self.assertEqual(self.alice.default_auto_delete_seconds, 604800)
