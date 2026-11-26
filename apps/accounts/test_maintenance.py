from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.messenger.models import Message
from apps.messenger.services import get_or_create_direct_chat
from .lifecycle import delete_user_account
from .maintenance import purge_inactive_accounts
from .models import User


@override_settings(SOVIETGRAM_BACKGROUND_MAINTENANCE=True)
class MaintenanceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.now = timezone.now()
        self.alice = User.objects.create_user("maint_alice", "maint-a@example.net", "Password-1945!")
        self.bob = User.objects.create_user("maint_bob", "maint-b@example.net", "Password-1945!")
        self.chat = get_or_create_direct_chat(self.alice, self.bob)

    def expired_user(self, name, **fields):
        user = User.objects.create_user(name, name + "@example.net", "Password-1945!")
        User.objects.filter(pk=user.pk).update(
            last_seen_at=self.now - timedelta(days=40), delete_after_inactive_days=30, **fields,
        )
        return user

    def test_background_mode_does_not_run_bulk_cleanup_in_requests(self):
        self.client.force_login(self.alice)
        expired = Message.objects.create(
            chat=self.chat, sender=self.bob, text="expired",
            expires_at=self.now - timedelta(seconds=1),
        )
        with patch("apps.accounts.middleware._purge_expired_messages") as messages, \
             patch("apps.accounts.middleware._purge_inactive_accounts") as accounts:
            self.assertEqual(self.client.get(reverse("messenger:home")).status_code, 200)
            messages.assert_not_called()
            accounts.assert_not_called()
        self.assertTrue(Message.objects.filter(pk=expired.pk).exists())

    def test_legacy_mode_keeps_cleanup_until_timer_is_installed(self):
        with self.settings(SOVIETGRAM_BACKGROUND_MAINTENANCE=False):
            with patch("apps.accounts.middleware._purge_expired_messages") as messages, \
                 patch("apps.accounts.middleware._purge_inactive_accounts") as accounts:
                self.client.get(reverse("accounts:login"))
                messages.assert_called_once()
                accounts.assert_called_once()

    def test_command_limits_and_protects_non_expired_messages(self):
        past = self.now - timedelta(seconds=1)
        for _ in range(3):
            Message.objects.create(chat=self.chat, sender=self.bob, text="old", expires_at=past)
        valid = Message.objects.create(chat=self.chat, sender=self.bob, text="new")
        first = self.expired_user("maint_expired1")
        second = self.expired_user("maint_expired2")
        protected = self.expired_user("maint_admin", platform_role=User.PlatformRole.ADMIN)
        suspended = self.expired_user("maint_suspended", platform_suspended_at=self.now)
        output = StringIO()
        call_command("run_maintenance", message_limit=2, account_limit=1, stdout=output)
        self.assertIn("2 expired message(s), 1 inactive account(s)", output.getvalue())
        self.assertEqual(Message.objects.filter(chat=self.chat, expires_at__lte=self.now).count(), 1)
        self.assertFalse(User.objects.filter(pk=first.pk).exists())
        self.assertTrue(User.objects.filter(pk=second.pk).exists())
        call_command("run_maintenance", stdout=StringIO())
        self.assertTrue(Message.objects.filter(pk=valid.pk).exists())
        self.assertFalse(User.objects.filter(pk=second.pk).exists())
        self.assertTrue(User.objects.filter(pk=protected.pk).exists())
        self.assertTrue(User.objects.filter(pk=suspended.pk).exists())
        self.assertEqual(purge_inactive_accounts(now=self.now), 0)

    def test_rechecks_inactivity_before_deletion(self):
        user = self.expired_user("maint_race")
        User.objects.filter(pk=user.pk).update(last_seen_at=self.now)
        self.assertFalse(delete_user_account(user, inactive_at=self.now))
        self.assertTrue(User.objects.filter(pk=user.pk).exists())

    def test_expired_active_session_still_rejected(self):
        self.client.force_login(self.alice)
        User.objects.filter(pk=self.alice.pk).update(
            last_seen_at=self.now - timedelta(days=400),
        )
        self.assertRedirects(self.client.get(reverse("messenger:home")), reverse("accounts:login"),
                             fetch_redirect_response=False)
        self.assertFalse(User.objects.filter(pk=self.alice.pk).exists())

    def test_invalid_batch_limits(self):
        with self.assertRaises(CommandError):
            call_command("run_maintenance", message_limit=-1)
