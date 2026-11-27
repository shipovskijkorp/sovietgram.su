from datetime import timedelta

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import User


class NotificationPreferenceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("preferencealice", "preferencealice@example.net", "Strong-test-password")
        cls.other = User.objects.create_user("preferencebob", "preferencebob@example.net", "Strong-test-password")

    def test_preferences_shared_between_devices_and_independent_updates(self):
        first, second = Client(), Client()
        first.force_login(self.user)
        second.force_login(self.user)
        url = reverse("accounts:notification_preferences")
        identity = {"account_id": self.user.pk}
        self.assertTrue(first.get(url, identity).json()["preferences"]["mention"])
        self.assertEqual(first.post(url, {**identity, "key": "mention", "value": "0"}).status_code, 200)
        self.assertEqual(second.post(url, {**identity, "key": "badge", "value": "0"}).status_code, 200)
        data = first.get(url, identity).json()["preferences"]
        self.assertFalse(data["mention"])
        self.assertFalse(data["badge"])
        self.assertTrue(data["sound"])
        self.assertEqual(first.post(url, {**identity, "key": "desktop", "value": "1"}).status_code, 400)
        self.assertEqual(first.get(url, {"account_id": self.other.pk}).status_code, 409)
        self.assertEqual(first.post(url, {"account_id": self.other.pk, "key": "sound", "value": "0"}).status_code, 409)
        self.assertEqual(User.objects.get(pk=self.other.pk).notification_preferences, {})

    def test_legacy_import_only_initializes_once_and_requires_csrf(self):
        self.client.force_login(self.user)
        url = reverse("accounts:notification_preferences")
        data = {"account_id": self.user.pk, "initialize": "1", "sound": "0",
                "message": "1", "mention": "0", "reply": "1", "badge": "1"}
        self.assertFalse(self.client.post(url, data).json()["preferences"]["sound"])
        data["sound"] = "1"
        self.assertFalse(self.client.post(url, data).json()["preferences"]["sound"])
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.user)
        self.assertEqual(protected.post(url, data).status_code, 403)

    def test_background_refresh_does_not_update_presence(self):
        self.client.force_login(self.user)
        previous = timezone.now() - timedelta(minutes=5)
        User.objects.filter(pk=self.user.pk).update(last_seen_at=previous)
        response = self.client.get(reverse("accounts:notification_preferences"), {"account_id": self.user.pk})
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.last_seen_at, previous)

    def test_invalid_values_do_not_initialize_preferences(self):
        self.client.force_login(self.user)
        url = reverse("accounts:notification_preferences")
        for data in ({}, {"key":"sound","value":"yes"}, {"initialize":"1","sound":"0"}):
            response = self.client.post(url, {"account_id": self.user.pk, **data})
            self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.notification_preferences, {})
