import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.messenger.services import get_or_create_direct_chat

from .models import User
from .privacy import set_privacy_rule


class ProfileAvatarPrivacyTests(TestCase):
    password = "Sovietgram-test-1945"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media_dir = tempfile.TemporaryDirectory()
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_dir.name)
        cls._media_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._media_override.disable()
        cls._media_dir.cleanup()
        super().tearDownClass()

    def setUp(self):
        self.alice = User.objects.create_user(
            username="avatar_alice",
            email="avatar-alice@example.com",
            password=self.password,
        )
        self.bob = User.objects.create_user(
            username="avatar_bob",
            email="avatar-bob@example.com",
            password=self.password,
        )
        self.alice.avatar.save(
            "avatar.png",
            SimpleUploadedFile(
                "avatar.png",
                b"private-avatar",
                content_type="image/png",
            ),
            save=True,
        )

    def test_avatar_url_uses_protected_view_not_storage_path(self):
        self.assertEqual(
            self.alice.avatar_url,
            reverse("accounts:profile_avatar", args=[self.alice.username]),
        )
        self.assertNotIn("/media/avatars/", self.alice.avatar_url)

    def test_profile_photo_privacy_is_enforced_when_file_is_requested(self):
        set_privacy_rule(self.alice, "profile_photo", "nobody")
        url = reverse("accounts:profile_avatar", args=[self.alice.username])

        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(url).status_code, 404)

        self.client.force_login(self.alice)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_everyone_rule_allows_public_avatar_request(self):
        set_privacy_rule(self.alice, "profile_photo", "everyone")
        response = self.client.get(
            reverse("accounts:profile_avatar", args=[self.alice.username])
        )
        self.assertEqual(response.status_code, 200)

    def test_private_chat_start_card_does_not_leak_hidden_avatar(self):
        set_privacy_rule(self.alice, "profile_photo", "nobody")
        chat = get_or_create_direct_chat(self.alice, self.bob)

        self.client.force_login(self.bob)
        response = self.client.get(reverse("messenger:chat", args=[chat.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.alice.avatar.name)
        self.assertNotContains(
            response,
            reverse("accounts:profile_avatar", args=[self.alice.username]),
        )
