from django.test import TestCase
from django.urls import reverse

from .models import User


class SettingsTests(TestCase):
    password = "Sovietgram-test-1945"

    def setUp(self):
        self.user = User.objects.create_user(
            username="settings_user",
            email="settings@example.com",
            password=self.password,
        )
        self.client.force_login(self.user)

    def test_archive_settings_are_rendered_in_messenger_overlay(self):
        response = self.client.get(f"{reverse('messenger:home')}?settings=archive")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="telegramSettings"', html=False)
        self.assertContains(response, 'id="archiveSettings"', html=False)
        self.assertContains(response, 'id="id_keep_archived_chats"', html=False)
        self.assertContains(response, 'id="id_archive_unknown_chats"', html=False)
        self.assertContains(response, 'id="id_archive_in_main_menu"', html=False)

    def test_archive_preferences_are_saved(self):
        response = self.client.post(
            reverse("accounts:settings"),
            {
                "theme": User.Theme.DARK,
                "enter_to_send": "on",
                "keep_archived_chats": "on",
                "archive_unknown_chats": "on",
            },
        )
        self.assertRedirects(response, f"{reverse('messenger:home')}?settings=main")

        self.user.refresh_from_db()
        self.assertEqual(self.user.theme, User.Theme.DARK)
        self.assertTrue(self.user.enter_to_send)
        self.assertTrue(self.user.keep_archived_chats)
        self.assertTrue(self.user.archive_unknown_chats)
        self.assertFalse(self.user.archive_in_main_menu)

    def test_archive_can_be_placed_in_main_menu(self):
        response = self.client.post(
            reverse("accounts:settings"),
            {
                "theme": User.Theme.LIGHT,
                "archive_in_main_menu": "on",
            },
        )
        self.assertRedirects(response, f"{reverse('messenger:home')}?settings=main")

        self.user.refresh_from_db()
        self.assertTrue(self.user.archive_in_main_menu)


    def test_settings_use_telegram_overlay_without_manual_save(self):
        response = self.client.get(f"{reverse('messenger:home')}?settings=main")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="telegramSettings"', html=False)
        self.assertContains(response, 'data-settings-screen="main"', html=False)
        self.assertContains(response, 'data-settings-screen="privacy"', html=False)
        self.assertContains(response, 'data-settings-screen="chat"', html=False)
        self.assertContains(response, 'data-settings-screen="archive"', html=False)
        self.assertContains(response, 'data-settings-screen="password"', html=False)
        self.assertContains(response, "Мой аккаунт")
        self.assertContains(response, "Конфиденциальность и безопасность")
        self.assertContains(response, "Настройки чатов")
        self.assertContains(response, "js/settings.js", html=False)
        self.assertNotContains(response, "Сохранить настройки")

    def test_ajax_setting_update_changes_only_requested_preference(self):
        self.user.theme = User.Theme.LIGHT
        self.user.enter_to_send = True
        self.user.keep_archived_chats = True
        self.user.archive_unknown_chats = False
        self.user.archive_in_main_menu = True
        self.user.save(
            update_fields=[
                "theme",
                "enter_to_send",
                "keep_archived_chats",
                "archive_unknown_chats",
                "archive_in_main_menu",
            ]
        )

        response = self.client.post(
            reverse("accounts:settings"),
            {
                "setting": "archive_unknown_chats",
                "value": "true",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

        self.user.refresh_from_db()
        self.assertEqual(self.user.theme, User.Theme.LIGHT)
        self.assertTrue(self.user.enter_to_send)
        self.assertTrue(self.user.keep_archived_chats)
        self.assertTrue(self.user.archive_unknown_chats)
        self.assertTrue(self.user.archive_in_main_menu)

    def test_ajax_theme_and_send_mode_are_saved_immediately(self):
        theme = self.client.post(
            reverse("accounts:settings"),
            {
                "setting": "theme",
                "value": User.Theme.DARK,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(theme.status_code, 200)
        self.assertEqual(theme.json()["value"], User.Theme.DARK)

        send_mode = self.client.post(
            reverse("accounts:settings"),
            {
                "setting": "enter_to_send",
                "value": "false",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(send_mode.status_code, 200)
        self.assertFalse(send_mode.json()["value"])

        self.user.refresh_from_db()
        self.assertEqual(self.user.theme, User.Theme.DARK)
        self.assertFalse(self.user.enter_to_send)

    def test_ajax_rejects_unknown_or_invalid_settings(self):
        unknown = self.client.post(
            reverse("accounts:settings"),
            {
                "setting": "imaginary_setting",
                "value": "true",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(unknown.status_code, 400)

        bad_theme = self.client.post(
            reverse("accounts:settings"),
            {
                "setting": "theme",
                "value": "neon",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(bad_theme.status_code, 400)

        bad_bool = self.client.post(
            reverse("accounts:settings"),
            {
                "setting": "keep_archived_chats",
                "value": "maybe",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(bad_bool.status_code, 400)

    def test_password_change_returns_to_privacy_settings(self):
        response = self.client.post(
            reverse("accounts:password_change"),
            {
                "old_password": self.password,
                "new_password1": "Sovietgram-new-password-1945",
                "new_password2": "Sovietgram-new-password-1945",
            },
        )
        self.assertRedirects(
            response,
            f"{reverse('messenger:home')}?settings=privacy",
            fetch_redirect_response=False,
        )


    def test_settings_get_redirects_to_messenger_overlay(self):
        response = self.client.get(reverse("accounts:settings"))
        self.assertRedirects(
            response,
            f"{reverse('messenger:home')}?settings=main",
            fetch_redirect_response=False,
        )

    def test_password_change_supports_ajax_overlay(self):
        response = self.client.post(
            reverse("accounts:password_change"),
            {
                "old_password": self.password,
                "new_password1": "Sovietgram-new-password-1946",
                "new_password2": "Sovietgram-new-password-1946",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Sovietgram-new-password-1946"))
