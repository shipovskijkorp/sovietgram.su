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

    def test_archive_settings_are_rendered(self):
        response = self.client.get(reverse("accounts:settings"))
        self.assertEqual(response.status_code, 200)
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
        self.assertRedirects(response, reverse("accounts:settings"))

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
        self.assertRedirects(response, reverse("accounts:settings"))

        self.user.refresh_from_db()
        self.assertTrue(self.user.archive_in_main_menu)
