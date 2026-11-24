"""Regression coverage for account recovery and verified email changes."""
import hashlib
import re
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlsplit

from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AccountSecurityRequest, User

RESET = AccountSecurityRequest.Purpose.PASSWORD_RESET
CHANGE = AccountSecurityRequest.Purpose.EMAIL_CHANGE


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    SOVIETGRAM_PUBLIC_URL="https://sovietgram.su",
)
class AccountSecurityTests(TestCase):
    password = "Original-password-1945!"
    new_password = "Updated-password-2687!"

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="ivan",
            email="ivan@example.com",
            password=self.password,
            email_verified_at=timezone.now(),
        )

    def link(self, index=-1):
        match = re.search(r"https://sovietgram\.su/[^\s]+", mail.outbox[index].body)
        self.assertIsNotNone(match)
        return urlsplit(match.group()).path

    def request_reset(self, email=None, client=None):
        return (client or self.client).post(
            reverse("accounts:password_reset"),
            {"email": email if email is not None else self.user.email},
        )

    def request_change(self, email="new@example.net", password=None):
        self.client.force_login(self.user)
        return self.client.post(
            reverse("accounts:email_change"),
            {"email": email, "password": self.password if password is None else password},
        )

    def reset_data(self):
        return {"new_password1": self.new_password, "new_password2": self.new_password}

    def test_entry_points(self):
        self.assertContains(self.client.get(reverse("accounts:login")), reverse("accounts:password_reset"))
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("messenger:home")), reverse("accounts:email_change"))

    def test_password_reset_is_one_use_and_invalidates_sessions(self):
        old_client = Client()
        old_client.force_login(self.user)
        self.assertRedirects(self.request_reset(), reverse("accounts:password_reset_sent"))
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        url = self.link()
        token = url.rstrip("/").split("/")[-1]
        pending = AccountSecurityRequest.objects.get(user=self.user, purpose=RESET)
        self.assertEqual(pending.token_digest, hashlib.sha256(token.encode()).hexdigest())
        self.assertNotEqual(token, pending.token_digest)
        preview = self.client.get(url)
        self.assertContains(preview, "Установите новый пароль")
        self.assertIn("no-store", preview["Cache-Control"])
        self.assertEqual(preview["Referrer-Policy"], "same-origin")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.password))
        response = self.client.post(url, self.reset_data())
        self.assertRedirects(response, reverse("accounts:login"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.new_password))
        self.assertFalse(self.user.check_password(self.password))
        self.assertIsNone(AccountSecurityRequest.objects.get(pk=pending.pk).token_digest)
        self.assertEqual(old_client.get(reverse("messenger:home")).status_code, 302)
        self.assertEqual(self.client.post(url, self.reset_data()).status_code, 400)
        self.assertTrue(self.client.login(username=self.user.email, password=self.new_password))

    def test_reset_does_not_disclose_unknown_inactive_or_unverified_users(self):
        User.objects.create_user("legacy", "legacy@example.net", self.password)
        User.objects.create_user(
            "inactive", "inactive@example.net", self.password,
            is_active=False, email_verified_at=timezone.now(),
        )
        sent = reverse("accounts:password_reset_sent")
        for email in ("absent@example.net", "legacy@example.net", "inactive@example.net"):
            with self.subTest(email=email):
                self.assertRedirects(self.request_reset(email), sent)
        self.assertEqual(len(mail.outbox), 0)
        self.assertRedirects(self.request_reset(), sent)
        self.assertEqual(len(mail.outbox), 1)

    def test_reset_cooldown_expiry_and_resend(self):
        self.request_reset()
        first = self.link()
        self.request_reset(email=self.user.email.upper())
        self.assertEqual(len(mail.outbox), 1)
        AccountSecurityRequest.objects.filter(user=self.user, purpose=RESET).update(
            issued_at=timezone.now() - timedelta(minutes=3),
        )
        self.request_reset()
        self.assertEqual(len(mail.outbox), 2)
        second = self.link()
        self.assertNotEqual(first, second)
        self.assertEqual(self.client.post(first, self.reset_data()).status_code, 400)
        AccountSecurityRequest.objects.filter(user=self.user, purpose=RESET).update(
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        self.assertContains(self.client.get(second), "Ссылка недействительна")
        self.assertEqual(self.client.post(second, self.reset_data()).status_code, 400)

    def test_reset_checks_password_validators_and_csrf(self):
        self.request_reset()
        url = self.link()
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.get(url, secure=True).status_code, 200)
        self.assertEqual(client.post(url, self.reset_data(), secure=True).status_code, 403)
        csrf = client.cookies["csrftoken"].value
        response = client.post(url, {
            "new_password1": "123", "new_password2": "123", "csrfmiddlewaretoken": csrf,
        }, secure=True, HTTP_REFERER="https://testserver" + url)
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.password))
        response = client.post(url, {
            **self.reset_data(), "csrfmiddlewaretoken": csrf,
        }, secure=True, HTTP_REFERER="https://testserver" + url)
        self.assertEqual(response.status_code, 302)

    def test_email_change_requires_authentication_and_correct_password(self):
        self.assertEqual(self.client.get(reverse("accounts:email_change")).status_code, 302)
        response = self.request_change(password="incorrect")
        self.assertContains(response, "Неверный пароль.")
        self.assertEqual(len(mail.outbox), 0)
        User.objects.create_user("other", "new@example.net", self.password)
        response = self.request_change(email="NEW@example.net")
        self.assertContains(response, "Этот адрес недоступен.")
        self.assertEqual(len(mail.outbox), 0)

    def test_email_change_only_after_explicit_confirmation_and_notifies_old_address(self):
        self.assertRedirects(self.request_change("NEW@example.net"), reverse("accounts:email_change"))
        url = self.link()
        self.assertEqual(mail.outbox[0].to, ["new@example.net"])
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "ivan@example.com")
        other_device = Client()
        self.assertContains(other_device.get(url), "Подтвердить адрес?")
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "ivan@example.com")
        self.assertRedirects(other_device.post(url), reverse("accounts:login"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "new@example.net")
        self.assertIsNotNone(self.user.email_verified_at)
        self.assertEqual(mail.outbox[-1].to, ["ivan@example.com"])
        self.assertIsNone(AccountSecurityRequest.objects.get(user=self.user, purpose=CHANGE).token_digest)
        self.assertEqual(other_device.post(url).status_code, 400)
        self.assertFalse(other_device.login(username="ivan@example.com", password=self.password))
        self.assertTrue(other_device.login(username="new@example.net", password=self.password))

    def test_legacy_account_can_confirm_its_current_email(self):
        self.user.email_verified_at = None
        self.user.save(update_fields=["email_verified_at"])
        self.assertRedirects(self.request_change(self.user.email), reverse("accounts:email_change"))
        self.assertEqual(self.client.post(self.link()).status_code, 302)
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.email_verified_at)
        self.assertEqual(len(mail.outbox), 1)
        self.request_reset()
        self.assertEqual(len(mail.outbox), 2)

    def test_changed_email_invalidates_pending_password_reset(self):
        self.request_reset()
        reset_url = self.link()
        self.request_change()
        self.assertEqual(self.client.post(self.link()).status_code, 302)
        self.assertEqual(self.client.post(reset_url, self.reset_data()).status_code, 400)

    def test_changed_password_invalidates_pending_email_change(self):
        self.request_change()
        change_url = self.link()
        self.request_reset()
        reset_url = self.link()
        self.assertEqual(Client().post(reset_url, self.reset_data()).status_code, 302)
        self.assertEqual(Client().post(change_url).status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "ivan@example.com")

    def test_email_change_rechecks_uniqueness_at_confirmation(self):
        self.request_change()
        url = self.link()
        User.objects.create_user("other", "new@example.net", self.password)
        self.assertEqual(self.client.post(url).status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "ivan@example.com")

    def test_email_change_cooldown_and_resend_invalidate_old_link(self):
        self.request_change()
        first = self.link()
        response = self.request_change("another@example.net")
        self.assertContains(response, "Подождите две минуты")
        self.assertEqual(len(mail.outbox), 1)
        AccountSecurityRequest.objects.filter(user=self.user, purpose=CHANGE).update(
            issued_at=timezone.now() - timedelta(minutes=3),
        )
        self.request_change("another@example.net")
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(Client().post(first).status_code, 400)
        self.assertEqual(Client().post(self.link()).status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "another@example.net")

    def test_email_confirmation_post_requires_csrf(self):
        self.request_change()
        url = self.link()
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.get(url, secure=True).status_code, 200)
        self.assertEqual(client.post(url, secure=True).status_code, 403)
        csrf = client.cookies["csrftoken"].value
        response = client.post(
            url, {"csrfmiddlewaretoken": csrf}, secure=True,
            HTTP_REFERER="https://testserver" + url,
        )
        self.assertEqual(response.status_code, 302)

    def test_smtp_failure_does_not_change_credentials(self):
        with patch("apps.accounts.account_security.send_mail", side_effect=OSError("SMTP unavailable")):
            self.assertRedirects(self.request_reset(), reverse("accounts:password_reset_sent"))
            response = self.request_change()
            self.assertContains(response, "Не удалось отправить письмо")
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(AccountSecurityRequest.objects.filter(user=self.user, token_digest__isnull=False).exists())
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "ivan@example.com")
        self.assertTrue(self.user.check_password(self.password))

    @override_settings(SOVIETGRAM_REQUIRE_EMAIL_VERIFICATION=False)
    def test_profile_cannot_bypass_verified_email_change_even_when_signup_verification_disabled(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("accounts:profile"), {
            "username": self.user.username, "email": "unverified@example.net",
            "first_name": "", "last_name": "", "bio": "",
        })
        self.assertContains(response, "Измените почту через настройки безопасности")
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "ivan@example.com")
