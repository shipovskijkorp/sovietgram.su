from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import SecurityEvent, User
from .security_events import record_event, HISTORY_LIMIT


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class SecurityEventTests(TestCase):
    password = "Security-test-password-1945!"
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("securityalice", "securityalice@example.net", cls.password)
        cls.other = User.objects.create_user("securitybob", "securitybob@example.net", cls.password)
        User.objects.filter(pk=cls.user.pk).update(email_verified_at=timezone.now())

    def sign_in(self, user, **kwargs):
        return Client().post(reverse("accounts:login"),
            {"username": user.username, "password": self.password}, **kwargs)

    def test_login_alert_verified_email_and_cooldown(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.sign_in(self.user, HTTP_USER_AGENT="test-device")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        self.assertEqual(SecurityEvent.objects.filter(user=self.user, kind="login").count(), 1)
        with self.captureOnCommitCallbacks(execute=True):
            self.sign_in(self.user)
            self.sign_in(self.other)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(SecurityEvent.objects.filter(user=self.user, kind="login").count(), 2)
        self.assertEqual(SecurityEvent.objects.filter(user=self.other, kind="login").count(), 1)
        User.objects.filter(pk=self.user.pk).update(last_login_alert_at=timezone.now()-timedelta(minutes=16))
        with self.captureOnCommitCallbacks(execute=True):
            self.sign_in(self.user)
        self.assertEqual(len(mail.outbox), 2)

    def test_history_private_escaped_and_bounded(self):
        request = RequestFactory().get("/", HTTP_USER_AGENT="<script>alert(1)</script>")
        for _ in range(HISTORY_LIMIT + 1):
            record_event(request, self.user, SecurityEvent.Kind.PASSWORD)
        record_event(RequestFactory().get("/", HTTP_USER_AGENT="other-private-device"),
                     self.other, SecurityEvent.Kind.PASSWORD)
        self.assertEqual(SecurityEvent.objects.filter(user=self.user).count(), HISTORY_LIMIT)
        self.client.force_login(self.user)
        page = self.client.get(reverse("accounts:security_history"))
        self.assertContains(page, "&lt;script&gt;alert(1)&lt;/script&gt;")
        self.assertNotContains(page, "other-private-device")
        self.client.logout()
        self.assertEqual(self.client.get(reverse("accounts:security_history")).status_code, 302)

    def test_smtp_failure_does_not_block_login(self):
        with patch("apps.accounts.security_events.send_mail", side_effect=OSError("unavailable")):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.sign_in(self.user)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(SecurityEvent.objects.filter(user=self.user, kind="login").exists())

    def test_revocation_is_logged_only_for_actual_other_sessions(self):
        from apps.accounts.privacy import active_sessions_payload
        current = Client()
        current.force_login(self.user)
        other = Client()
        other.force_login(self.user)
        token = next(row["token"] for row in active_sessions_payload(
            self.user, current.session.session_key) if not row["current"])
        url = reverse("accounts:settings")
        ajax = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
        self.assertEqual(current.post(url, {"action":"terminate_session", "token":token}, **ajax).status_code, 200)
        self.assertEqual(SecurityEvent.objects.filter(user=self.user, kind="session_revoke").count(), 1)
        self.assertEqual(current.post(url, {"action":"terminate_session", "token":token}, **ajax).status_code, 404)
        self.assertEqual(SecurityEvent.objects.filter(user=self.user, kind="session_revoke").count(), 1)
        another = Client()
        another.force_login(self.user)
        self.assertEqual(current.post(url, {"action":"terminate_other_sessions"}, **ajax).status_code, 200)
        self.assertEqual(SecurityEvent.objects.filter(user=self.user, kind="sessions_revoke").count(), 1)
        self.assertEqual(current.post(url, {"action":"terminate_other_sessions"}, **ajax).status_code, 200)
        self.assertEqual(SecurityEvent.objects.filter(user=self.user, kind="sessions_revoke").count(), 1)

    def test_sign_in_ip_ignores_untrusted_forwarded_prefix(self):
        from apps.accounts.privacy import remember_session_device
        request = RequestFactory().get("/", REMOTE_ADDR="127.0.0.1",
            HTTP_X_REAL_IP="203.0.113.9", HTTP_X_FORWARDED_FOR="198.51.100.7, 203.0.113.9")
        request.user = self.user
        class MemorySession(dict):
            modified = False
        request.session = MemorySession()
        remember_session_device(request)
        self.assertEqual(request.session["sovietgram_session_ip"], "203.0.113.9")
        request.META["REMOTE_ADDR"] = "192.0.2.4"
        remember_session_device(request)
        self.assertEqual(request.session["sovietgram_session_ip"], "192.0.2.4")

    def test_wrong_password_is_not_a_successful_login(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("accounts:login"), {"username": self.user.username, "password": "wrong"})
        self.assertFalse(SecurityEvent.objects.filter(user=self.user).exists())
        self.assertFalse(mail.outbox)
