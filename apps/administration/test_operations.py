from datetime import timedelta
from io import StringIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pyotp
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.two_factor import encrypt_secret
from config.operations import job_run, job_status, read_heartbeat, write_heartbeat


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class OperationsTests(TestCase):
    def setUp(self):
        cache.clear()
        work = TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.enterContext(override_settings(SOVIETGRAM_OPS_DIR=work.name,
                                            SOVIETGRAM_BACKGROUND_MAINTENANCE=True))

    def user(self, name, role):
        return User.objects.create_user(name, name+"@example.net", "Password-1945!",
            platform_role=role, two_factor_secret=encrypt_secret(pyotp.random_base32()) if role else "")

    def test_operations_requires_admin_role_and_two_factor(self):
        url = reverse("administration:operations")
        self.assertEqual(self.client.get(url).status_code, 302)
        for name, role, code in (("member", "", 403), ("moderator", "moderator", 403),
                                 ("admin", "admin", 200), ("owner", "owner", 200)):
            with self.subTest(role=role):
                self.client.force_login(self.user(name, role))
                response = self.client.get(url)
                self.assertEqual(response.status_code, code)
                if code == 200:
                    self.assertContains(response, "Состояние сервера")
                    self.assertContains(response, "Резервное копирование")
                    self.assertIn("no-store", response["Cache-Control"])
        owner = User.objects.get(username="owner")
        owner.two_factor_secret = ""
        owner.save(update_fields=["two_factor_secret"])
        self.client.force_login(owner)
        self.assertRedirects(self.client.get(url), reverse("accounts:two_factor"),
                             fetch_redirect_response=False)

    def test_liveness_is_public_minimal_and_skips_cleanup(self):
        with patch("apps.accounts.middleware._purge_inactive_accounts") as cleanup:
            response = self.client.get(reverse("healthz"))
            self.assertEqual(response.json(), {"ok": True})
            self.assertEqual(response.status_code, 200)
            cleanup.assert_not_called()

    def test_heartbeat_success_failure_staleness_and_disabled_cleanup(self):
        now = timezone.now()
        self.assertEqual(job_status("scheduled", now)["state"], "unknown")
        with job_run("scheduled"):
            self.assertEqual(read_heartbeat("scheduled")["state"], "running")
        success = read_heartbeat("scheduled")["success_at"]
        self.assertEqual(job_status("scheduled", timezone.now())["state"], "ok")
        self.assertEqual(job_status("scheduled", now+timedelta(hours=1))["state"], "warning")
        with self.assertRaises(RuntimeError):
            with job_run("scheduled"):
                raise RuntimeError("secret diagnostic not persisted")
        self.assertEqual(read_heartbeat("scheduled")["success_at"], success)
        self.assertEqual(job_status("scheduled", timezone.now())["state"], "error")
        self.assertNotIn("secret diagnostic", str(read_heartbeat("scheduled")))
        with self.settings(SOVIETGRAM_BACKGROUND_MAINTENANCE=False):
            self.assertEqual(job_status("maintenance", now)["status"], "Фоновый режим выключен")

    def test_task_commands_record_success(self):
        call_command("deliver_scheduled_messages", stdout=StringIO())
        call_command("run_maintenance", stdout=StringIO())
        for job in ("scheduled", "maintenance"):
            self.assertEqual(read_heartbeat(job)["state"], "ok")

    def test_healthcheck_reports_failure_without_secret_details(self):
        with patch("apps.messenger.management.commands.healthcheck.check_database",
                   return_value={"state":"error","engine":"postgresql"}):
            with self.assertRaises(CommandError):
                call_command("healthcheck", stdout=StringIO())
