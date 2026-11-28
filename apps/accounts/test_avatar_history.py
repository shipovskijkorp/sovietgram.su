from io import BytesIO
from tempfile import TemporaryDirectory

from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import AvatarHistory, User
from .avatar_history import archive_previous, HISTORY_LIMIT
from .storage_views import storage_summary


def picture(name, color):
    buffer = BytesIO()
    Image.new("RGB", (24, 24), color).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class AvatarHistoryTests(TestCase):
    def setUp(self):
        work = TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.enterContext(override_settings(MEDIA_ROOT=work.name))
        self.alice = User.objects.create_user("historyalice", "historyalice@example.net", "Password-1945!")
        self.bob = User.objects.create_user("historybob", "historybob@example.net", "Password-1945!")
        self.client.force_login(self.alice)
        self.alice.avatar.save("old.png", picture("old.png", "red"), save=True)

    def replace_avatar(self):
        old = self.alice.avatar.name
        response = self.client.post(reverse("accounts:profile"), {
            "first_name": "Alice", "last_name": "", "username": self.alice.username, "bio": "",
            "avatar": picture("new.png", "blue"),
        }, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200, response.content)
        self.alice.refresh_from_db()
        self.assertNotEqual(self.alice.avatar.name, old)
        return AvatarHistory.objects.get(user=self.alice, image=old)

    def test_replace_restore_delete_and_private_image(self):
        photo = self.replace_avatar()
        old, new = photo.image.name, self.alice.avatar.name
        image_url = reverse("accounts:avatar_history_image", args=[photo.pk])
        action_url = reverse("accounts:avatar_history_action", args=[photo.pk])
        self.assertTrue(self.alice.avatar.storage.exists(old))
        self.assertContains(self.client.get(reverse("accounts:avatar_history")), image_url)
        response = self.client.get(image_url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("private", response["Cache-Control"])
        self.assertIn("no-store", response["Cache-Control"])
        response.close()
        outsider = Client()
        outsider.force_login(self.bob)
        self.assertEqual(outsider.get(image_url).status_code, 404)
        self.assertEqual(outsider.post(action_url, {"account_id":self.bob.pk, "action":"restore"}).status_code, 404)
        self.assertEqual(self.client.post(action_url, {"account_id":self.bob.pk, "action":"restore"}).status_code, 400)
        self.assertEqual(self.client.post(action_url, {"account_id":self.alice.pk, "action":"restore"}).status_code, 302)
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.avatar.name, old)
        archived = AvatarHistory.objects.get(user=self.alice, image=new)
        self.assertEqual(storage_summary(self.alice)["archived_avatar_count"], 1)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.client.post(reverse("accounts:avatar_history_action", args=[archived.pk]),
                {"account_id":self.alice.pk, "action":"delete"}).status_code, 302)
        self.assertFalse(self.alice.avatar.storage.exists(new))
        self.assertTrue(self.alice.avatar.storage.exists(old))
        self.assertFalse(self.alice.avatar_history.exists())

    def test_shared_gallery_is_opt_in_and_respects_photo_privacy(self):
        from .privacy import set_privacy_rule
        photo = self.replace_avatar()
        action = reverse("accounts:avatar_history_action", args=[photo.pk])
        gallery = reverse("accounts:profile_gallery", args=[self.alice.username])
        image = reverse("accounts:gallery_image", args=[self.alice.username, photo.pk])
        url = reverse("accounts:public_profile", args=[self.alice.username])
        outsider = Client()
        outsider.force_login(self.bob)
        def photos():
            return outsider.get(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest").json()["profile_photos"]
        self.assertEqual(len(photos()), 1)
        self.assertEqual(outsider.get(image).status_code, 404)
        self.assertEqual(outsider.post(action, {"account_id": self.bob.pk, "action":"share"}).status_code,404)
        self.assertEqual(self.client.post(action, {"account_id":self.alice.pk,"action":"share"}).status_code,302)
        self.assertEqual(len(photos()),2)
        self.assertContains(outsider.get(gallery),image)
        response=outsider.get(image)
        self.assertEqual(response.status_code,200)
        self.assertIn("no-store",response["Cache-Control"])
        response.close()
        # The owner-only image endpoint never becomes public.
        self.assertEqual(outsider.get(reverse("accounts:avatar_history_image",args=[photo.pk])).status_code,404)
        set_privacy_rule(self.alice,"profile_photo","nobody")
        self.assertEqual(photos(),[])
        self.assertEqual(outsider.get(gallery).status_code,404)
        self.assertEqual(outsider.get(image).status_code,404)
        set_privacy_rule(self.alice,"profile_photo","everyone")
        self.assertEqual(self.client.post(action, {"account_id":self.alice.pk,"action":"unshare"}).status_code,302)
        self.assertEqual(outsider.get(image).status_code,404)
        self.assertEqual(len(photos()),1)
        self.assertTrue(AvatarHistory.objects.filter(pk=photo.pk).exists())

    def test_archive_bounded_and_explicit_current_removal(self):
        current = self.alice.avatar.name
        with self.captureOnCommitCallbacks(execute=True):
            for index in range(HISTORY_LIMIT + 1):
                archive_previous(self.alice, f"avatars/old-{index}.png")
        self.assertEqual(self.alice.avatar_history.count(), HISTORY_LIMIT)
        self.assertFalse(self.alice.avatar_history.filter(image="avatars/old-0.png").exists())
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("accounts:remove_avatar"), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertFalse(self.alice.avatar.storage.exists(current))
        self.assertFalse(self.alice.avatar_history.filter(image=current).exists())
