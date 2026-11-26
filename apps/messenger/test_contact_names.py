from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import User
from .models import Contact
from .services import get_or_create_direct_chat


class ContactNameTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alias_alice", "alias-a@example.net", "Password-1945!")
        cls.bob = User.objects.create_user("alias_bob", "alias-b@example.net", "Password-1945!")
        cls.chat = get_or_create_direct_chat(cls.alice, cls.bob)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.alice)
        self.url = reverse("messenger:rename_contact", args=[self.bob.username])
        self.profile = reverse("accounts:public_profile", args=[self.bob.username])

    def test_alias_private_searchable_and_removable(self):
        self.assertEqual(self.client.post(self.url, {"alias":"Саня"}).status_code, 404)
        Contact.objects.create(owner=self.alice, user=self.bob)
        response = self.client.post(self.url, {"alias":"  Саня   Друг  ", "account_id":self.alice.pk})
        self.assertEqual(response.json()["contact_alias"], "Саня Друг")
        profile = self.client.get(self.profile, HTTP_X_REQUESTED_WITH="XMLHttpRequest").json()
        self.assertEqual(profile["contact_alias"], "Саня Друг")
        self.assertEqual(profile["display_name"], self.bob.display_name)
        self.assertContains(self.client.get(reverse("messenger:chat", args=[self.chat.pk])), "Саня Друг")
        self.assertContains(self.client.get(reverse("messenger:contacts")), "Саня Друг")
        result = self.client.get(reverse("messenger:global_search"), {"q":"саня"}).json()
        self.assertEqual(result["chats"][0]["title"], "Саня Друг")
        self.assertEqual(result["people"][0]["display_name"], "Саня Друг")
        peer = Client()
        peer.force_login(self.bob)
        public = peer.get(self.profile, HTTP_X_REQUESTED_WITH="XMLHttpRequest").json()
        self.assertEqual(public["contact_alias"], "")
        self.assertNotContains(peer.get(reverse("messenger:chat", args=[self.chat.pk])), "Саня Друг")
        self.assertEqual(self.client.post(self.url, {"alias":""}).json()["contact_name"], self.bob.display_name)
        self.client.post(self.url, {"alias":"Друг"})
        self.client.post(reverse("messenger:remove_contact", args=[self.bob.username]))
        self.assertFalse(Contact.objects.filter(owner=self.alice, user=self.bob).exists())

    def test_invalid_alias_or_account_change(self):
        Contact.objects.create(owner=self.alice, user=self.bob)
        self.assertEqual(self.client.post(self.url, {"alias":"x"*101}).status_code, 400)
        self.assertEqual(self.client.post(self.url, {"alias":"x\x01"}).status_code, 400)
        self.assertEqual(self.client.post(self.url, {"alias":"x", "account_id":self.bob.pk}).status_code, 409)
        self.assertEqual(Contact.objects.get(owner=self.alice, user=self.bob).alias, "")
