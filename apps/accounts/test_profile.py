from datetime import date
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image
from django.urls import reverse

from apps.messenger.models import Chat, ChatParticipant, Message

from .models import User


class ProfileTests(TestCase):
    password = "Sovietgram-test-1945"

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

    def test_authenticated_public_profile_opens_in_messenger_overlay(self):
        self.client.force_login(self.user)
        other = User.objects.create_user(
            username="overlay_target",
            email="overlay-target@example.com",
            password=self.password,
        )

        response = self.client.get(
            reverse("accounts:public_profile", args=[other.username])
        )
        self.assertRedirects(
            response,
            f"{reverse('messenger:home')}?profile={other.username}",
            fetch_redirect_response=False,
        )

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
        self.assertIn("birthday", payload)
        self.assertIn("personal_channel", payload)
        self.assertEqual(
            payload["profile_url"],
            reverse("accounts:public_profile", args=[other.username]),
        )
        self.assertEqual(payload["remove_avatar_url"], "")
        self.assertNotIn("email", payload)
        self.assertNotIn("phone", payload)

    def test_messenger_profile_overlay_omits_forbidden_telegram_extras(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("messenger:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="userProfileOverlay"', html=False)
        self.assertContains(response, "Имя пользователя")
        self.assertNotContains(response, "tg-profile__row-icon", html=False)
        self.assertNotContains(response, ">Фамилия<", html=False)
        self.assertContains(response, 'id="userProfileChannelPicker"', html=False)
        self.assertContains(response, 'id="userProfileChannelOpen"', html=False)
        self.assertContains(response, 'id="userProfileFieldEditor"', html=False)
        self.assertContains(response, 'id="userProfilePhotoViewer"', html=False)
        self.assertContains(response, 'id="userProfileUsernameRow"', html=False)
        self.assertNotContains(response, 'id="userProfileEditSave"', html=False)
        self.assertContains(
            response,
            'id="userProfileEdit" type="button" aria-label="Редактировать" hidden',
            html=False,
        )
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
        self.assertContains(response, 'id="userProfileNameOpen"', html=False)
        self.assertContains(response, 'id="userProfileUsernameOpen"', html=False)
        self.assertContains(response, 'id="userProfileBirthdayOpen"', html=False)
        self.assertContains(response, "О себе")
        self.assertContains(response, "Имя пользователя")
        self.assertNotContains(response, "Номер телефона")
        self.assertNotContains(response, "Подарки")
        self.assertNotContains(response, "QR")
        self.assertNotContains(response, "Истории")
        self.assertNotContains(response, "Автоматизация чатов")
        self.assertNotContains(response, "Цвет имени")

    def test_overlay_profile_edit_updates_public_fields_without_email(self):
        self.user.last_name = "Сохранённая"
        self.user.save(update_fields=["last_name"])
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:profile"),
            {
                "first_name": "Иван",
                "username": "ivan_overlay",
                "bio": "Редактировано из виджета.",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["display_name"], "Иван Сохранённая")
        self.assertEqual(payload["username"], "ivan_overlay")
        self.assertNotIn("email", payload)

        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Иван")
        self.assertEqual(self.user.last_name, "Сохранённая")
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
        self.assertEqual(
            payload["profile_url"],
            reverse("accounts:public_profile", args=[self.user.username]),
        )
        self.assertEqual(payload["remove_avatar_url"], reverse("accounts:remove_avatar"))
        self.assertIn("first_name", payload)
        self.assertIn("last_name", payload)
        self.assertNotIn("email", payload)
        self.assertNotIn("phone", payload)

    def test_personal_channel_profile_payload_contains_telegram_summary(self):
        channel = Chat.objects.create(
            type=Chat.Type.CHANNEL,
            title="Shipovskijkorp Technologies",
            username="shiptech",
            description="Новости проекта",
        )
        ChatParticipant.objects.create(
            chat=channel,
            user=self.user,
            role=ChatParticipant.Role.OWNER,
        )
        other = User.objects.create_user(
            username="subscriber",
            email="subscriber@example.com",
            password=self.password,
        )
        ChatParticipant.objects.create(
            chat=channel,
            user=other,
            role=ChatParticipant.Role.MEMBER,
        )
        Message.objects.create(
            chat=channel,
            sender=self.user,
            text="Industrial Legacy Version: Alpha 0.1.9 Dev Blog",
        )
        self.user.personal_channel = channel
        self.user.save(update_fields=["personal_channel"])

        self.client.force_login(self.user)
        response = self.client.get(
            reverse("accounts:public_profile", args=[self.user.username]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        personal = response.json()["personal_channel"]
        self.assertEqual(personal["title"], "Shipovskijkorp Technologies")
        self.assertEqual(
            personal["last_message_preview"],
            "Industrial Legacy Version: Alpha 0.1.9 Dev Blog",
        )
        self.assertEqual(personal["subscriber_count"], 2)
        self.assertEqual(personal["subscriber_text"], "2 подписчика")
        self.assertTrue(personal["last_message_time"])

        page = self.client.get(reverse("messenger:home"))
        self.assertContains(page, 'id="userProfileChannelCard"', html=False)
        self.assertContains(page, 'id="userProfileChannelPreview"', html=False)
        self.assertContains(page, 'id="userProfileChannelMeta"', html=False)
        self.assertNotContains(page, 'id="userProfileChannelRow"', html=False)

    def test_personal_channel_profile_link_opens_joined_channel_directly(self):
        channel = Chat.objects.create(
            type=Chat.Type.CHANNEL,
            title="Joined channel",
            username="joined_channel",
        )
        ChatParticipant.objects.create(
            chat=channel,
            user=self.user,
            role=ChatParticipant.Role.OWNER,
        )
        self.user.personal_channel = channel
        self.user.save(update_fields=["personal_channel"])

        self.client.force_login(self.user)
        response = self.client.get(
            reverse("accounts:public_profile", args=[self.user.username]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        personal = response.json()["personal_channel"]
        self.assertEqual(personal["open_method"], "get")
        self.assertEqual(
            personal["open_url"],
            reverse("messenger:chat", args=[channel.pk]),
        )

    def test_personal_channel_profile_link_joins_public_channel_for_non_member(self):
        owner = User.objects.create_user(
            username="owner",
            email="owner@example.com",
            password=self.password,
        )
        channel = Chat.objects.create(
            type=Chat.Type.CHANNEL,
            title="Public channel",
            username="public_channel",
        )
        ChatParticipant.objects.create(
            chat=channel,
            user=owner,
            role=ChatParticipant.Role.OWNER,
        )
        owner.personal_channel = channel
        owner.save(update_fields=["personal_channel"])

        self.client.force_login(self.user)
        response = self.client.get(
            reverse("accounts:public_profile", args=[owner.username]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        personal = response.json()["personal_channel"]
        self.assertEqual(personal["open_method"], "post")
        self.assertEqual(
            personal["open_url"],
            reverse("messenger:join_public_chat", args=[channel.username]),
        )

    def test_overlay_profile_edit_updates_birthday_and_owned_personal_channel(self):
        channel = Chat.objects.create(
            type=Chat.Type.CHANNEL,
            title="Shipovskijkorp Technologies",
            username="shiptech",
        )
        ChatParticipant.objects.create(
            chat=channel,
            user=self.user,
            role=ChatParticipant.Role.OWNER,
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("accounts:profile"),
            {
                "first_name": "",
                "username": self.user.username,
                "bio": "",
                "birthday": "2000-09-10",
                "personal_channel": str(channel.pk),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["birthday"], "2000-09-10")
        self.assertEqual(payload["personal_channel"]["id"], channel.pk)

        self.user.refresh_from_db()
        self.assertEqual(self.user.birthday, date(2000, 9, 10))
        self.assertEqual(self.user.personal_channel_id, channel.pk)

    def test_overlay_rejects_private_owned_personal_channel(self):
        channel = Chat.objects.create(
            type=Chat.Type.CHANNEL,
            title="Private owned channel",
            username=None,
        )
        ChatParticipant.objects.create(
            chat=channel,
            user=self.user,
            role=ChatParticipant.Role.OWNER,
        )

        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:profile"),
            {
                "first_name": "",
                "username": self.user.username,
                "bio": "",
                "birthday": "",
                "personal_channel": str(channel.pk),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("personal_channel", response.json()["errors"])

    def test_private_legacy_personal_channel_is_not_exposed_in_profile(self):
        channel = Chat.objects.create(
            type=Chat.Type.CHANNEL,
            title="Legacy private channel",
            username=None,
        )
        ChatParticipant.objects.create(
            chat=channel,
            user=self.user,
            role=ChatParticipant.Role.OWNER,
        )
        self.user.personal_channel = channel
        self.user.save(update_fields=["personal_channel"])

        self.client.force_login(self.user)
        response = self.client.get(
            reverse("accounts:public_profile", args=[self.user.username]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsNone(payload["personal_channel"])
        self.assertEqual(payload["owned_channels"], [])

    def test_overlay_rejects_foreign_personal_channel(self):
        other = User.objects.create_user(
            username="other",
            email="other@example.com",
            password=self.password,
        )
        channel = Chat.objects.create(
            type=Chat.Type.CHANNEL,
            title="Чужой канал",
            username="other_channel",
        )
        ChatParticipant.objects.create(
            chat=channel,
            user=other,
            role=ChatParticipant.Role.OWNER,
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("accounts:profile"),
            {
                "first_name": "",
                "username": self.user.username,
                "bio": "",
                "birthday": "",
                "personal_channel": str(channel.pk),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("personal_channel", response.json()["errors"])

    def test_overlay_edit_keeps_existing_avatar_when_no_new_file_is_uploaded(self):
        buffer = BytesIO()
        Image.new("RGB", (64, 64), "red").save(buffer, format="PNG")
        self.user.avatar = SimpleUploadedFile(
            "existing.png",
            buffer.getvalue(),
            content_type="image/png",
        )
        self.user.save(update_fields=["avatar"])
        original_name = self.user.avatar.name

        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:profile"),
            {
                "first_name": "Иван",
                "username": self.user.username,
                "bio": "Изменено без нового аватара.",
                "birthday": "",
                "personal_channel": "",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

        self.user.refresh_from_db()
        self.assertEqual(self.user.avatar.name, original_name)
        self.assertEqual(self.user.bio, "Изменено без нового аватара.")

    def test_ajax_avatar_removal_updates_profile_without_redirect(self):
        buffer = BytesIO()
        Image.new("RGB", (64, 64), "green").save(buffer, format="PNG")
        self.user.avatar = SimpleUploadedFile(
            "remove-me.png",
            buffer.getvalue(),
            content_type="image/png",
        )
        self.user.save(update_fields=["avatar"])

        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:remove_avatar"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["avatar_url"], "")

        self.user.refresh_from_db()
        self.assertFalse(bool(self.user.avatar))

    def test_fallback_profile_edit_keeps_existing_avatar_without_revalidation(self):
        buffer = BytesIO()
        Image.new("RGB", (64, 64), "blue").save(buffer, format="PNG")
        self.user.avatar = SimpleUploadedFile(
            "existing-fallback.png",
            buffer.getvalue(),
            content_type="image/png",
        )
        self.user.save(update_fields=["avatar"])
        original_name = self.user.avatar.name

        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:profile"),
            {
                "first_name": "Иван",
                "last_name": "",
                "username": self.user.username,
                "bio": "Fallback update.",
                "email": self.user.email,
                "birthday": "",
            },
        )
        self.assertRedirects(response, reverse("accounts:profile"))

        self.user.refresh_from_db()
        self.assertEqual(self.user.avatar.name, original_name)
        self.assertEqual(self.user.bio, "Fallback update.")

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
