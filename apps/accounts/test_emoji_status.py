from datetime import timedelta

from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import User
from .privacy import set_privacy_rule


class EmojiStatusTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner=User.objects.create_user("emojiowner","emojiowner@example.test","Test-pass-1945!")
        self.peer=User.objects.create_user("emojipeer","emojipeer@example.test","Test-pass-1945!")
        self.client.force_login(self.owner)
        self.other=Client()
        self.other.force_login(self.peer)
        self.url=reverse("accounts:emoji_status")
        self.profile=reverse("accounts:public_profile",args=[self.owner.username])

    def set_status(self,emoji,duration,account=None):
        return self.client.post(self.url,{"account_id":account or self.owner.pk,"emoji":emoji,"duration":duration},HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def get_status(self,client):
        return client.get(self.profile,HTTP_X_REQUESTED_WITH="XMLHttpRequest").json()["emoji_status"]

    def test_temporary_status_and_privacy(self):
        now=timezone.now()
        response=self.set_status("💻","3600")
        self.assertEqual(response.status_code,200,response.content)
        self.owner.refresh_from_db()
        self.assertGreater(self.owner.emoji_status_until,now+timedelta(minutes=59))
        self.assertEqual(self.get_status(self.other)["emoji"],"💻")
        set_privacy_rule(self.owner,"bio","nobody")
        self.assertEqual(self.get_status(self.other),{"emoji":"","until":""})
        self.assertEqual(self.get_status(self.client)["emoji"],"💻")
        set_privacy_rule(self.owner,"bio","everyone")
        User.objects.filter(pk=self.owner.pk).update(emoji_status_until=now-timedelta(seconds=1))
        self.assertEqual(self.get_status(self.other),{"emoji":"","until":""})
        self.assertEqual(self.get_status(self.client),{"emoji":"","until":""})

    def test_validation_account_guard_and_clear(self):
        self.assertEqual(self.set_status("<script>","0").status_code,400)
        self.assertEqual(self.set_status("🔥","999").status_code,400)
        self.assertEqual(self.set_status("🔥","0",self.peer.pk).status_code,400)
        self.assertEqual(self.set_status("🔥","0").status_code,200)
        self.assertEqual(self.get_status(self.other),{"emoji":"🔥","until":""})
        self.assertEqual(self.set_status("","3600").status_code,200)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.emoji_status,"")
        self.assertIsNone(self.owner.emoji_status_until)
        self.assertEqual(Client().get(self.url).status_code,302)
