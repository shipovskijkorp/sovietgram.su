from django.contrib.auth import SESSION_KEY
from django.test import TestCase
from django.urls import reverse

from .models import User


class MultiAccountTests(TestCase):
    password = "Sovietgram-test-1945"

    def setUp(self):
        self.first = User.objects.create_user(
            username="first",
            email="first@example.com",
            password=self.password,
        )
        self.second = User.objects.create_user(
            username="second",
            email="second@example.com",
            password=self.password,
        )
        self.client.force_login(self.first)

    def test_add_account_keeps_first_session_and_switches_to_second(self):
        response = self.client.post(
            reverse("accounts:add_account"),
            {
                "username": self.second.username,
                "password": self.password,
            },
        )
        self.assertRedirects(response, reverse("messenger:home"))

        session = self.client.session
        self.assertEqual(int(session[SESSION_KEY]), self.second.pk)
        account_ids = {
            int(item["user_id"])
            for item in session["sovietgram_accounts_v1"]
        }
        self.assertEqual(account_ids, {self.first.pk, self.second.pk})

    def test_switch_account_does_not_require_password_again(self):
        self.client.post(
            reverse("accounts:add_account"),
            {
                "username": self.second.username,
                "password": self.password,
            },
        )

        response = self.client.post(
            reverse("accounts:switch_account", args=[self.first.pk])
        )
        self.assertRedirects(response, reverse("messenger:home"))
        self.assertEqual(int(self.client.session[SESSION_KEY]), self.first.pk)

    def test_logout_removes_only_current_account_when_another_slot_exists(self):
        self.client.post(
            reverse("accounts:add_account"),
            {
                "username": self.second.username,
                "password": self.password,
            },
        )

        response = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(response, reverse("messenger:home"))
        self.assertEqual(int(self.client.session[SESSION_KEY]), self.first.pk)
        remaining = self.client.session["sovietgram_accounts_v1"]
        self.assertEqual([int(item["user_id"]) for item in remaining], [self.first.pk])

    def test_sidebar_uses_single_full_header_account_toggle(self):
        response = self.client.get(reverse("messenger:home"))
        self.assertContains(
            response,
            'class="profile-account-header" id="profileAccountToggle" type="button"',
            html=False,
        )
        self.assertContains(
            response,
            'class="profile-account-header__chevron"',
            html=False,
        )
        self.assertContains(
            response,
            'id="profileAccountList" hidden',
            html=False,
        )
        self.assertNotContains(response, "profileAccountToggleInput", html=False)
        self.assertNotContains(response, "profile-accounts__toggle", html=False)
        self.assertNotContains(response, "profile-drawer__username", html=False)
        self.assertContains(response, "Добавить аккаунт")
        self.assertContains(response, "Создать группу")
        self.assertContains(response, "Создать канал")
        self.assertContains(response, "Звонки")
        self.assertNotContains(response, "Кошелёк")
        self.assertNotContains(response, "Ночной режим")
        self.assertNotContains(response, "эмодзи-статус")

    def test_saved_account_avatar_has_hard_dimensions(self):
        self.client.post(
            reverse("accounts:add_account"),
            {
                "username": self.second.username,
                "password": self.password,
            },
        )
        response = self.client.get(reverse("messenger:home"))
        self.assertContains(response, 'class="profile-account-avatar"', html=False)
        self.assertContains(response, 'width="36" height="36"', html=False)

    def test_sidebar_lists_saved_accounts(self):
        self.client.post(
            reverse("accounts:add_account"),
            {
                "username": self.second.username,
                "password": self.password,
            },
        )
        response = self.client.get(reverse("messenger:home"))
        self.assertContains(response, "@first")
        self.assertContains(response, "@second")
        self.assertContains(response, "Добавить аккаунт")
