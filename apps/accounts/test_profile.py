from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image
from django.urls import reverse

from .models import User


class ProfileTests(TestCase):
    password = "Stalingram-test-1945"

    def setUp(self):
        self.user = User.objects.create_user(
            username="ivan",
            email="ivan@example.com",
            password=self.password,
        )

    def test_profile_requires_login(self):
        response = self.client.get(reverse("accounts:profile"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_profile_can_be_edited(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:profile"),
            {
                "first_name": "Иван",
                "last_name": "Петров",
                "username": "ivan_petrov",
                "bio": "На связи.",
                "email": "petrov@example.com",
            },
        )
        self.assertRedirects(response, reverse("accounts:profile"))

        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Иван")
        self.assertEqual(self.user.last_name, "Петров")
        self.assertEqual(self.user.username, "ivan_petrov")
        self.assertEqual(self.user.bio, "На связи.")
        self.assertEqual(self.user.email, "petrov@example.com")
        self.assertEqual(self.user.display_name, "Иван Петров")

    def test_profile_rejects_case_insensitive_username_collision(self):
        User.objects.create_user(
            username="Petrov",
            email="other@example.com",
            password=self.password,
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:profile"),
            {
                "first_name": "",
                "last_name": "",
                "username": "PETROV",
                "bio": "",
                "email": self.user.email,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Пользователь с таким именем уже существует.")

    def test_public_profile_is_visible_without_login_and_hides_email(self):
        self.user.first_name = "Иван"
        self.user.bio = "Публичное описание"
        self.user.save(update_fields=["first_name", "bio"])

        response = self.client.get(
            reverse("accounts:public_profile", args=[self.user.username])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Иван")
        self.assertContains(response, "Публичное описание")
        self.assertNotContains(response, self.user.email)

    def test_public_profile_ajax_returns_compact_safe_payload(self):
        self.user.first_name = "Иван"
        self.user.bio = "Публичное описание"
        self.user.save(update_fields=["first_name", "bio"])

        self.client.force_login(self.user)
        other = User.objects.create_user(
            username="petr",
            email="petr@example.com",
            password=self.password,
            first_name="Пётр",
            bio="Собираю BuildCraft.",
        )

        response = self.client.get(
            reverse("accounts:public_profile", args=[other.username]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["display_name"], "Пётр")
        self.assertEqual(payload["username"], "petr")
        self.assertEqual(payload["bio"], "Собираю BuildCraft.")
        self.assertIn("status", payload)
        self.assertNotIn("email", payload)
        self.assertNotIn("phone", payload)
        self.assertNotIn("birthday", payload)

    def test_messenger_profile_overlay_omits_forbidden_telegram_extras(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("messenger:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="userProfileOverlay"', html=False)
        self.assertContains(response, "Имя пользователя")
        self.assertNotContains(response, "Номер телефона")
        self.assertNotContains(response, "Подарки")
        self.assertNotContains(response, "QR")
        self.assertNotContains(response, "Истории")
        self.assertNotContains(response, "Автоматизация чатов")
        self.assertNotContains(response, "Цвет имени")

    def test_own_profile_opens_in_messenger_overlay(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("messenger:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'href="{reverse("accounts:public_profile", args=[self.user.username])}" data-user-profile',
            html=False,
        )
        self.assertContains(response, 'id="userProfileEdit"', html=False)
        self.assertContains(response, 'id="userProfileEditForm"', html=False)
        self.assertContains(response, "О себе")
        self.assertContains(response, "Имя пользователя")
        self.assertNotContains(response, "Номер телефона")
        self.assertNotContains(response, "Подарки")
        self.assertNotContains(response, "QR")
        self.assertNotContains(response, "Истории")
        self.assertNotContains(response, "Автоматизация чатов")
        self.assertNotContains(response, "Цвет имени")

    def test_overlay_profile_edit_updates_public_fields_without_email(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:profile"),
            {
                "first_name": "Иван",
                "last_name": "Шиповский",
                "username": "ivan_overlay",
                "bio": "Редактировано из виджета.",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["display_name"], "Иван Шиповский")
        self.assertEqual(payload["username"], "ivan_overlay")
        self.assertNotIn("email", payload)

        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Иван")
        self.assertEqual(self.user.last_name, "Шиповский")
        self.assertEqual(self.user.username, "ivan_overlay")
        self.assertEqual(self.user.bio, "Редактировано из виджета.")
        self.assertEqual(self.user.email, "ivan@example.com")

    def test_self_profile_ajax_exposes_edit_fields_but_not_private_account_data(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("accounts:public_profile", args=[self.user.username]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["is_self"])
        self.assertEqual(payload["edit_url"], reverse("accounts:profile"))
        self.assertIn("first_name", payload)
        self.assertIn("last_name", payload)
        self.assertNotIn("email", payload)
        self.assertNotIn("phone", payload)

    def test_profile_rejects_oversized_avatar_dimensions(self):
        self.client.force_login(self.user)
        buffer = BytesIO()
        Image.new("RGB", (5000, 1), "white").save(buffer, format="PNG")
        avatar = SimpleUploadedFile(
            "too-wide.png",
            buffer.getvalue(),
            content_type="image/png",
        )
        response = self.client.post(
            reverse("accounts:profile"),
            {
                "first_name": "",
                "last_name": "",
                "username": self.user.username,
                "bio": "",
                "email": self.user.email,
                "avatar": avatar,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Фотография слишком большая")

    def test_password_can_be_changed(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:password_change"),
            {
                "old_password": self.password,
                "new_password1": "Much-better-password-2026",
                "new_password2": "Much-better-password-2026",
            },
        )
        self.assertRedirects(response, reverse("accounts:profile"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Much-better-password-2026"))
