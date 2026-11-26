import io
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from PIL import Image

from apps.accounts.models import User


class PWATests(TestCase):
    def test_public_manifest_icons_and_worker(self):
        manifest = self.client.get(reverse("pwa_manifest"))
        self.assertEqual(manifest.status_code, 200)
        self.assertEqual(manifest.json()["display"], "standalone")
        self.assertEqual(manifest.json()["scope"], "/")
        for icon in manifest.json()["icons"]:
            response = self.client.get(icon["src"])
            self.assertEqual(response.status_code, 200)
            with Image.open(io.BytesIO(response.content)) as image:
                self.assertEqual(f"{image.width}x{image.height}", icon["sizes"])
        worker = self.client.get(reverse("pwa_worker"))
        self.assertEqual(worker["Service-Worker-Allowed"], "/")
        self.assertIn("no-cache", worker["Cache-Control"])
        self.assertContains(worker, "sovietgram-public-shell-v1")
        self.assertEqual(self.client.get(reverse("pwa_icon", args=[1])).status_code, 404)

    def test_offline_shell_is_independent_of_account(self):
        anonymous = self.client.get(reverse("pwa_offline")).content
        user = User.objects.create_user("pwa_private", "pwa@example.net", "Password-1945!")
        self.client.force_login(user)
        with patch("apps.accounts.middleware._purge_inactive_accounts") as cleanup:
            response = self.client.get(reverse("pwa_offline"))
            cleanup.assert_not_called()
        self.assertEqual(response.content, anonymous)
        self.assertNotContains(response, user.username)
        self.assertNotContains(response, user.email)
        self.assertContains(response, "Нет подключения")
