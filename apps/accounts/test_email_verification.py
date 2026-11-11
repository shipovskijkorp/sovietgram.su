"""Registration email verification and multi-account regression coverage."""

from datetime import timedelta
from unittest.mock import patch

from django.core import mail, signing
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .email_verification import (
    confirm_verification,
    get_pending_verification,
    verification_token,
)
from .forms import ProfileForm
from .models import User


@override_settings(
    SOVIETGRAM_REQUIRE_EMAIL_VERIFICATION=True,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class EmailVerificationTests(TestCase):
    password = "Sovietgram-test-1945"

    def register(self, username="newuser", email="newuser@example.com"):
        return self.client.post(
            reverse("accounts:register"),
            {
                "username": username, "email": email,
                "password1": self.password, "password2": self.password,
            },
        )

    def test_pending_signup_sends_mail_without_logging_in(self):
        response = self.register()
        self.assertRedirects(response, reverse("accounts:verification_pending"))
        user = User.objects.get(username="newuser")
        self.assertFalse(user.is_active)
        self.assertIsNone(user.email_verified_at)
        self.assertIsNotNone(user.email_verification_sent_at)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["newuser@example.com"])
        self.assertIn(
            reverse("accounts:verify_email", args=[verification_token(user)]),
            mail.outbox[0].body,
        )
        self.assertIn("Проверьте почту", self.client.get(response.url).content.decode())

    def test_verification_email_uses_canonical_https_public_url(self):
        with override_settings(SOVIETGRAM_PUBLIC_URL="https://sovietgram.su"):
            self.register()
        user = User.objects.get(username="newuser")
        expected = (
            "https://sovietgram.su"
            + reverse("accounts:verify_email", args=[verification_token(user)])
        )
        self.assertIn(expected, mail.outbox[0].body)
        self.assertNotIn("http://testserver", mail.outbox[0].body)

    def test_secure_confirmation_sets_cookie_and_allows_same_origin_referer(self):
        self.register()
        user = User.objects.get(username="newuser")
        url = reverse("accounts:verify_email", args=[verification_token(user)])
        client = Client(enforce_csrf_checks=True)

        with override_settings(CSRF_COOKIE_SECURE=True):
            preview = client.get(url, secure=True)
            self.assertEqual(preview.status_code, 200)
            self.assertEqual(preview["Referrer-Policy"], "same-origin")
            self.assertIn("csrftoken", client.cookies)
            self.assertTrue(client.cookies["csrftoken"]["secure"])

            verified = client.post(
                url,
                {"csrfmiddlewaretoken": client.cookies["csrftoken"].value},
                secure=True,
                HTTP_REFERER=f"https://testserver{url}",
            )

        self.assertRedirects(verified, reverse("accounts:login"))
        user.refresh_from_db()
        self.assertTrue(user.is_active)

    def test_activation_requires_explicit_post_and_succeeds_only_once(self):
        self.register()
        user = User.objects.get(username="newuser")
        token = verification_token(user)
        url = reverse("accounts:verify_email", args=[token])

        preview = self.client.get(url)
        self.assertContains(preview, "Подтвердить почту")
        user.refresh_from_db()
        self.assertFalse(user.is_active)

        blocked = self.client.post(
            reverse("accounts:login"),
            {"username": "newuser@example.com", "password": self.password},
        )
        self.assertEqual(blocked.status_code, 200)
        self.assertContains(blocked, "Подтвердите почту")
        self.assertNotIn("_auth_user_id", self.client.session)

        activated = self.client.post(url)
        self.assertRedirects(activated, reverse("accounts:login"))
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertIsNotNone(user.email_verified_at)
        self.assertIsNone(user.email_verification_sent_at)

        self.assertIsNone(get_pending_verification(token))
        self.assertFalse(confirm_verification(token))
        self.assertEqual(self.client.post(url).status_code, 400)

        login = self.client.post(
            reverse("accounts:login"),
            {"username": "newuser@example.com", "password": self.password},
        )
        self.assertRedirects(login, reverse("messenger:home"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_resend_cooldown_and_old_link_invalidation(self):
        self.register()
        user = User.objects.get(username="newuser")
        first = verification_token(user)
        url = reverse("accounts:resend_verification")

        early = self.client.post(url, {"email": user.email})
        self.assertRedirects(early, reverse("accounts:verification_pending"))
        self.assertEqual(len(mail.outbox), 1)

        User.objects.filter(pk=user.pk).update(
            email_verification_sent_at=timezone.now() - timedelta(minutes=3),
        )
        resent = self.client.post(url, {"email": user.email})
        self.assertRedirects(resent, reverse("accounts:verification_pending"))
        self.assertEqual(len(mail.outbox), 2)

        user.refresh_from_db()
        new_token = verification_token(user)
        self.assertNotEqual(first, new_token)
        self.assertIsNone(get_pending_verification(first))
        self.assertIsNotNone(get_pending_verification(new_token))
        self.assertEqual(self.client.post(
            reverse("accounts:verify_email", args=[first])
        ).status_code, 400)

    def test_resend_does_not_disclose_if_email_exists(self):
        self.register()
        other = User.objects.create_user(
            "existing", "existing@example.com", self.password
        )
        self.assertTrue(other.is_active)
        url = reverse("accounts:resend_verification")
        for address in ("missing@example.com", other.email, "newuser@example.com"):
            response = self.client.post(url, {"email": address}, follow=True)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Если адрес ожидает подтверждения")
        self.assertEqual(len(mail.outbox), 1)

    def test_invalid_and_expired_links_never_activate(self):
        self.register()
        user = User.objects.get(username="newuser")
        token = verification_token(user)
        bad = token[:-2] + ("A" if token[-2:] != "AA" else "B")
        self.assertEqual(self.client.get(
            reverse("accounts:verify_email", args=[bad])
        ).status_code, 200)
        self.assertEqual(self.client.post(
            reverse("accounts:verify_email", args=[bad])
        ).status_code, 400)

        with patch(
            "apps.accounts.email_verification.signing.loads",
            side_effect=signing.SignatureExpired("expired"),
        ):
            self.assertIsNone(get_pending_verification(token))
        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_other_account_stays_logged_in_when_new_registration_is_pending(self):
        original = User.objects.create_user(
            "original", "original@example.com", self.password,
        )
        self.client.force_login(original)
        response = self.client.post(
            reverse("accounts:add_account"),
            {
                "mode": "register", "username": "otheraccount",
                "email": "otheraccount@example.com",
                "password1": self.password, "password2": self.password,
            },
        )
        self.assertRedirects(response, reverse("accounts:verification_pending"))
        pending = User.objects.get(username="otheraccount")
        self.assertFalse(pending.is_active)
        self.assertEqual(int(self.client.session["_auth_user_id"]), original.pk)
        self.assertEqual(
            [int(item["user_id"]) for item in self.client.session["sovietgram_accounts_v1"]],
            [original.pk],
        )

        verified = self.client.post(
            reverse("accounts:verify_email", args=[verification_token(pending)])
        )
        self.assertRedirects(verified, reverse("accounts:add_account"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), original.pk)
        added = self.client.post(
            reverse("accounts:add_account"),
            {"mode": "login", "username": pending.username, "password": self.password},
        )
        self.assertRedirects(added, reverse("messenger:home"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), pending.pk)

    def test_mail_failure_still_shows_pending_and_resend_remains_possible(self):
        with patch(
            "apps.accounts.views.send_verification_email",
            side_effect=OSError("SMTP unavailable"),
        ):
            response = self.register()
        self.assertRedirects(response, reverse("accounts:verification_pending"))
        self.assertFalse(User.objects.get(username="newuser").is_active)
        self.assertEqual(len(mail.outbox), 0)

        User.objects.filter(username="newuser").update(
            email_verification_sent_at=timezone.now() - timedelta(minutes=3)
        )
        self.client.post(
            reverse("accounts:resend_verification"),
            {"email": "newuser@example.com"},
        )
        self.assertEqual(len(mail.outbox), 1)

    def test_email_change_cannot_bypass_verification(self):
        user = User.objects.create_user(
            "legacy", "legacy@example.com", self.password,
        )
        form = ProfileForm(
            {
                "username": user.username,
                "email": "unverified@example.com",
                "first_name": "", "last_name": "", "bio": "",
            }, instance=user,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)
        user.refresh_from_db()
        self.assertEqual(user.email, "legacy@example.com")

    def test_legacy_active_user_can_still_log_in(self):
        user = User.objects.create_user(
            "legacy", "legacy@example.com", self.password,
        )
        self.assertIsNone(user.email_verified_at)
        result = self.client.post(
            reverse("accounts:login"),
            {"username": user.username, "password": self.password},
        )
        self.assertRedirects(result, reverse("messenger:home"))

    def test_confirmation_post_requires_csrf(self):
        self.register()
        user = User.objects.get(username="newuser")
        url = reverse(
            "accounts:verify_email", args=[verification_token(user)]
        )
        client = Client(enforce_csrf_checks=True)
        preview = client.get(url)
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(client.post(url).status_code, 403)
        csrf_token = client.cookies["csrftoken"].value
        verified = client.post(url, {"csrfmiddlewaretoken": csrf_token})
        self.assertRedirects(verified, reverse("accounts:login"))
