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

    def test_wrong_password_is_not_a_successful_login(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("accounts:login"), {"username": self.user.username, "password": "wrong"})
        self.assertFalse(SecurityEvent.objects.filter(user=self.user).exists())
        self.assertFalse(mail.outbox)
