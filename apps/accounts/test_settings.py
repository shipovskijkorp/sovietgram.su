from django.test import Client, TestCase
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
        self.assertContains(response, 'data-settings-screen="blocked"', html=False)
        self.assertContains(response, 'data-settings-screen="sessions"', html=False)
        self.assertContains(response, 'data-settings-screen="privacy-rule"', html=False)
        self.assertContains(response, 'data-settings-screen="privacy-exceptions"', html=False)
        self.assertContains(response, "Время последней активности")
        self.assertContains(response, "Фотография профиля")
        self.assertContains(response, "Пересылка сообщений")
        self.assertContains(response, "Голосовые сообщения")
        self.assertContains(response, "Группы и каналы")
        self.assertNotContains(response, "Облачный пароль")
        self.assertNotContains(response, "Код-пароль")
        self.assertNotContains(response, "Ключи доступа")
        self.assertContains(response, "Редактировать профиль")
        self.assertNotContains(response, 'tg-settings-section-icon--account', html=False)
        self.assertContains(response, 'id="blockedSearchEmpty"', html=False)
        self.assertNotContains(response, 'data-privacy-open="calls"', html=False)
        self.assertContains(response, "Конфиденциальность и безопасность")
        self.assertContains(response, "Настройки чатов")
        # Settings icons must use the native luminance-mask pipeline.
        # The previous custom classes rendered opaque PNGs as solid squares.
        self.assertContains(
            response,
            'tg-native-icon tg-native-icon--lock tg-settings-row__native-icon',
            html=False,
        )
        self.assertContains(
            response,
            'tg-native-icon tg-native-icon--settings tg-settings-row__native-icon',
            html=False,
        )
        self.assertContains(
            response,
            'tg-native-icon tg-native-icon--archive tg-settings-row__native-icon',
            html=False,
        )
        self.assertNotContains(response, "tg-settings-section-icon--lock", html=False)
        self.assertNotContains(response, "tg-settings-section-icon--chat", html=False)
        self.assertNotContains(response, "tg-settings-section-icon--archive", html=False)
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


    def test_login_page_has_persisted_theme_bootstrap_and_toggle(self):
        self.client.logout()
        response = self.client.get(reverse("accounts:login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-auth-theme-toggle', html=False)
        self.assertContains(response, 'sovietgram.theme', html=False)


    def test_every_visible_preference_can_be_saved_and_read_back(self):
        endpoint = reverse("accounts:settings")
        preferences = (
            ("theme", "dark", "dark"),
            ("enter_to_send", "false", False),
            ("keep_archived_chats", "true", True),
            ("archive_unknown_chats", "true", True),
            ("archive_in_main_menu", "true", True),
            ("delete_after_inactive_days", "90", 90),
            ("default_auto_delete_seconds", "604800", 604800),
        )
        for setting, value, expected in preferences:
            with self.subTest(setting=setting):
                response = self.client.post(
                    endpoint,
                    {"setting": setting, "value": value},
                    HTTP_X_REQUESTED_WITH="XMLHttpRequest",
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()["ok"])
                self.assertEqual(response.json()["value"], expected)

        snapshot = self.client.get(
            endpoint, {"action": "privacy_state"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(snapshot.status_code, 200)
        payload = snapshot.json()
        for setting, _value, expected in preferences:
            self.assertEqual(payload["preferences"][setting], expected)

        updated = self.client.get(
            f"{reverse('messenger:home')}?settings=archive"
        )
        self.assertContains(
            updated, 'id="id_archive_in_main_menu" type="checkbox" data-setting="archive_in_main_menu" checked',
            html=False,
        )

    def test_settings_ajax_is_csrf_protected(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        home = client.get(reverse("messenger:home"))
        self.assertEqual(home.status_code, 200)
        csrf = client.cookies["csrftoken"].value
        denied = client.post(
            reverse("accounts:settings"),
            {"setting": "theme", "value": "dark"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(denied.status_code, 403)
        accepted = client.post(
            reverse("accounts:settings"),
            {"setting": "theme", "value": "dark", "csrfmiddlewaretoken": csrf},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(accepted.status_code, 200)

    def test_unknown_ajax_read_is_rejected_in_json(self):
        response = self.client.get(
            reverse("accounts:settings"),
            {"action": "does-not-exist"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])

    def test_terminate_single_session_requires_exact_token(self):
        other = Client()
        another = Client()
        other.force_login(self.user)
        another.force_login(self.user)
        endpoint = reverse("accounts:settings")
        get_state = lambda: self.client.get(
            endpoint, {"action": "privacy_state"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        ).json()["sessions"]

        initial = get_state()
        self.assertEqual(len(initial), 3)
        self.assertEqual(len([s for s in initial if s["current"]]), 1)

        missing = self.client.post(
            endpoint, {"action": "terminate_session"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(len(get_state()), 3)

        unknown = self.client.post(
            endpoint, {"action": "terminate_session", "token": "0" * 24},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(unknown.status_code, 404)
        self.assertEqual(len(get_state()), 3)

        target = next(s for s in initial if not s["current"])
        single = self.client.post(
            endpoint, {"action": "terminate_session", "token": target["token"]},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(single.status_code, 200)
        self.assertEqual(len(single.json()["sessions"]), 2)
        self.assertNotIn(target["token"], [s["token"] for s in get_state()])

        all_others = self.client.post(
            endpoint, {"action": "terminate_other_sessions"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(all_others.status_code, 200)
        self.assertEqual(len(all_others.json()["sessions"]), 1)
        self.assertTrue(all_others.json()["sessions"][0]["current"])

    def test_expired_auth_hash_not_shown_as_active_session(self):
        extra = Client()
        extra.force_login(self.user)
        endpoint = reverse("accounts:settings")
        def sessions():
            return self.client.get(
                endpoint, {"action": "privacy_state"},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            ).json()["sessions"]

        self.assertEqual(len(sessions()), 2)
        self.user.set_password("A-new-secure-password-2026")
        self.user.save(update_fields=["password"])
        # The current browser's old hash is invalid too: log in again.
        self.client.force_login(self.user)
        active = sessions()
        self.assertEqual(len(active), 1)
        self.assertTrue(active[0]["current"])

