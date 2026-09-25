from django.test import TestCase
from django.urls import reverse

from .models import User


class AccountFlowTests(TestCase):
    def test_registration_creates_user_and_logs_in(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "username": "ivan",
                "email": "ivan@example.com",
                "password1": "Sovietgram-test-1945",
                "password2": "Sovietgram-test-1945",
            },
        )
        self.assertRedirects(response, reverse("messenger:home"))
        self.assertTrue(User.objects.filter(username="ivan", email="ivan@example.com").exists())
        self.assertEqual(int(self.client.session["_auth_user_id"]), User.objects.get(username="ivan").pk)

    def test_login_accepts_username(self):
        User.objects.create_user("zhukov", "zhukov@example.com", "Sovietgram-test-1945")
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "zhukov", "password": "Sovietgram-test-1945"},
        )
        self.assertRedirects(response, reverse("messenger:home"))

    def test_login_accepts_email(self):
        User.objects.create_user("rokossovsky", "marshal@example.com", "Sovietgram-test-1945")
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "marshal@example.com", "password": "Sovietgram-test-1945"},
        )
        self.assertRedirects(response, reverse("messenger:home"))

    def test_registration_rejects_duplicate_email_case_insensitively(self):
        User.objects.create_user("first", "user@example.com", "Sovietgram-test-1945")
        response = self.client.post(
            reverse("accounts:register"),
            {
                "username": "second",
                "email": "USER@example.com",
                "password1": "Sovietgram-test-1945",
                "password2": "Sovietgram-test-1945",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Эта почта уже используется.")


class UserSettingsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "settings_user",
            "settings@example.com",
            "Sovietgram-test-1945",
        )
        self.client.force_login(self.user)

    def test_settings_page_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("accounts:settings"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_theme_and_enter_preference_are_saved(self):
        response = self.client.post(
            reverse("accounts:settings"),
            {"theme": "dark"},
        )
        self.assertRedirects(response, reverse("accounts:settings"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.theme, User.Theme.DARK)
        self.assertFalse(self.user.enter_to_send)

    def test_enter_to_send_can_be_enabled(self):
        self.user.enter_to_send = False
        self.user.save(update_fields=["enter_to_send"])
        response = self.client.post(
            reverse("accounts:settings"),
            {"theme": "light", "enter_to_send": "on"},
        )
        self.assertRedirects(response, reverse("accounts:settings"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.enter_to_send)
