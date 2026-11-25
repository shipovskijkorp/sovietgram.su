"""Regression tests for login, session invalidation, enrollment and recovery."""
from datetime import timedelta
from unittest.mock import patch

import pyotp
from django.contrib.auth import SESSION_KEY, authenticate
from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import User
from .two_factor import decrypt_secret, encrypt_secret, matching_step, new_recovery_codes, recovery_hash
from .two_factor_views import PENDING


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class TwoFactorTests(TestCase):
    password = "Sovietgram-test-1945!"
    new_password = "Sovietgram-updated-2687!"

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("factor", "factor@example.net", self.password,
                                             email_verified_at=timezone.now())
        self.other = User.objects.create_user("otherfactor", "other@example.net", self.password)
        self.url = reverse("accounts:two_factor")
        self.login_url = reverse("accounts:login")
        self.client.force_login(self.user)

    def act(self, action, **data):
        return self.client.post(self.url, {"account_id":self.user.pk,"action":action,**data})

    def protect(self):
        self.secret = pyotp.random_base32()
        self.codes, hashes = new_recovery_codes()
        User.objects.filter(pk=self.user.pk).update(
            two_factor_secret=encrypt_secret(self.secret), two_factor_recovery_hashes=hashes,
            security_version=1,
        )
        self.user.refresh_from_db()
        self.client.force_login(self.user)

    def test_enrollment_requires_password_and_valid_code_revokes_old_sessions(self):
        old = Client()
        old.force_login(self.user)
        self.assertEqual(self.act("start",password="bad").status_code,400)
        self.assertNotIn(PENDING,self.client.session)
        self.assertEqual(self.act("start",password=self.password).status_code,302)
        setup = self.client.get(self.url)
        self.assertContains(setup,"data:image/png;base64,")
        secret = setup.context["secret"]
        self.assertNotEqual(self.client.session[PENDING]["secret"],secret)
        self.assertIn("no-store",setup["Cache-Control"])
        self.assertEqual(self.act("enable",otp="not-code").status_code,400)
        enrollment_time = timezone.now()
        enrollment_code = pyotp.TOTP(secret).at(int(enrollment_time.timestamp()))
        with patch("apps.accounts.two_factor.timezone.now",return_value=enrollment_time):
            response = self.act("enable",otp=enrollment_code)
        self.assertEqual(response.status_code,200,response.content)
        codes = response.context["codes"]
        self.assertEqual(len(codes),10)
        self.assertContains(response, f'<a class="primary-button" href="{reverse("messenger:home")}">Я сохранил коды</a>', html=True)
        self.assertNotContains(response, "Назад к настройкам")
        self.user.refresh_from_db()
        self.assertTrue(self.user.two_factor_enabled)
        self.assertEqual(decrypt_secret(self.user.two_factor_secret),secret)
        self.assertEqual(self.user.two_factor_recovery_hashes,[recovery_hash(code) for code in codes])
        self.assertNotIn(PENDING,self.client.session)
        self.assertEqual(self.client.get(self.url).status_code,200)
        self.assertNotContains(self.client.get(self.url),codes[0])
        self.assertEqual(old.get(reverse("messenger:home")).status_code,302)
        self.assertIsNone(authenticate(username=self.user.username,password=self.password))
        with patch("apps.accounts.two_factor.timezone.now",return_value=enrollment_time):
            self.assertIsNone(authenticate(username=self.user.username,password=self.password,otp=enrollment_code))
        fresh = Client()
        self.assertTrue(fresh.login(username=self.user.email,password=self.password,otp=codes[0]))
        self.assertFalse(Client().login(username=self.user.email,password=self.password,otp=codes[0]))
        self.assertEqual(len(User.objects.get(pk=self.user.pk).two_factor_recovery_hashes),9)

    def test_login_and_multiaccount_cannot_skip_factor(self):
        self.protect()
        guest = Client()
        self.assertEqual(guest.post(self.login_url,{"username":self.user.username,"password":self.password}).status_code,200)
        self.assertNotIn(SESSION_KEY,guest.session)
        self.assertEqual(guest.post(self.login_url,{"username":self.user.username,"password":self.password,"otp":self.codes[0]}).status_code,302)
        second = Client()
        second.force_login(self.other)
        data = {"username":self.user.username,"password":self.password}
        self.assertEqual(second.post(reverse("accounts:add_account"),data).status_code,200)
        self.assertEqual(int(second.session[SESSION_KEY]),self.other.pk)
        data["otp"] = self.codes[1]
        self.assertEqual(second.post(reverse("accounts:add_account"),data).status_code,302)
        self.assertEqual(int(second.session[SESSION_KEY]),self.user.pk)
        self.assertEqual(second.post(reverse("accounts:switch_account",args=[self.other.pk])).status_code,302)
        self.assertEqual(second.post(reverse("accounts:switch_account",args=[self.user.pk])).status_code,302)
        self.assertEqual(int(second.session[SESSION_KEY]),self.user.pk)

    def test_admin_factor_is_required(self):
        self.protect()
        User.objects.filter(pk=self.user.pk).update(is_staff=True,is_superuser=True)
        client = Client()
        url = reverse("admin:login")
        self.assertContains(client.get(url),"name=\"otp\"")
        data = {"username":self.user.username,"password":self.password,"next":reverse("admin:index")}
        self.assertEqual(client.post(url,data).status_code,200)
        self.assertNotIn(SESSION_KEY,client.session)
        data["otp"] = self.codes[0]
        self.assertEqual(client.post(url,data).status_code,302)
        self.assertEqual(int(client.session[SESSION_KEY]),self.user.pk)

    def test_rate_limit_shared_between_clients_and_step_replay(self):
        self.protect()
        invalid = "not-a-code"
        for _ in range(5):
            self.assertFalse(Client().login(username=self.user.username,password=self.password,otp=invalid))
        self.user.refresh_from_db()
        self.assertEqual(self.user.two_factor_failures,5)
        self.assertFalse(Client().login(username=self.user.username,password=self.password,otp=self.codes[0]))
        User.objects.filter(pk=self.user.pk).update(two_factor_failure_window=timezone.now()-timedelta(minutes=6))
        now = timezone.now()
        code = pyotp.TOTP(self.secret).at(int(now.timestamp()))
        with patch("apps.accounts.two_factor.timezone.now",return_value=now):
            self.assertTrue(Client().login(username=self.user.username,password=self.password,otp=code))
            self.assertFalse(Client().login(username=self.user.username,password=self.password,otp=code))
        self.assertTrue(Client().login(username=self.user.username,password=self.password,otp=self.codes[0]))

    def test_regeneration_revokes_saved_slots_and_disable_requires_factor(self):
        self.protect()
        second = Client()
        second.force_login(self.other)
        second.post(reverse("accounts:add_account"),{"username":self.user.username,"password":self.password,"otp":self.codes[0]})
        second.post(reverse("accounts:switch_account",args=[self.other.pk]))
        self.assertEqual(self.act("disable",password=self.password).status_code,400)
        response = self.act("regenerate",password=self.password,otp=self.codes[1])
        self.assertEqual(response.status_code,200,response.content)
        replacement = response.context["codes"]
        self.assertContains(response, f'<a class="primary-button" href="{self.url}">Я сохранил коды</a>', html=True)
        self.assertNotEqual(replacement,self.codes)
        self.assertFalse(Client().login(username=self.user.username,password=self.password,otp=self.codes[2]))
        second.post(reverse("accounts:switch_account",args=[self.user.pk]))
        self.assertEqual(int(second.session[SESSION_KEY]),self.other.pk)
        self.assertEqual(self.act("disable",password=self.password,otp=replacement[0]).status_code,302)
        self.user.refresh_from_db()
        self.assertFalse(self.user.two_factor_enabled)
        self.assertEqual(self.user.two_factor_recovery_hashes,[])
        self.assertTrue(Client().login(username=self.user.username,password=self.password))

    def test_sensitive_actions_require_fresh_factor(self):
        self.protect()
        email = {"email":"replacement@example.net","password":self.password}
        self.client.post(reverse("accounts:email_change"),email)
        self.assertEqual(len(mail.outbox),0)
        self.client.post(reverse("accounts:email_change"),{**email,"otp":self.codes[0]})
        self.assertEqual(len(mail.outbox),1)
        change = {"old_password":self.password,"new_password1":self.new_password,"new_password2":self.new_password}
        url = reverse("accounts:password_change")
        denied = self.client.post(url,change,HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(denied.status_code,400)
        done = self.client.post(url,{**change,"otp":self.codes[1]},HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(done.status_code,200,done.content)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.new_password))
        self.assertTrue(self.user.two_factor_enabled)
        data = {"account_id":self.user.pk,"username":self.user.username,"password":self.new_password,"confirm":"on"}
        self.client.post(reverse("accounts:delete_account"),data)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())
        self.client.post(reverse("accounts:delete_account"),{**data,"otp":self.codes[2]})
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())

    def test_password_reset_does_not_disable_factor(self):
        self.protect()
        client = Client()
        client.post(reverse("accounts:password_reset"),{"email":self.user.email})
        self.assertEqual(len(mail.outbox),1)
        import re
        from urllib.parse import urlsplit
        url = urlsplit(re.search(r"https?://[^\s]+",mail.outbox[0].body).group()).path
        response = client.post(url,{"new_password1":self.new_password,"new_password2":self.new_password})
        self.assertEqual(response.status_code,302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.two_factor_enabled)
        self.assertFalse(client.login(username=self.user.username,password=self.new_password))
        self.assertTrue(client.login(username=self.user.username,password=self.new_password,otp=self.codes[0]))

    def test_pending_setup_is_bound_to_account_and_expires(self):
        self.assertEqual(self.act("start",password=self.password).status_code,302)
        pending = dict(self.client.session[PENDING])
        session = self.client.session
        pending["created"] -= 601
        session[PENDING] = pending
        session.save()
        self.assertEqual(self.act("enable",otp="123456").status_code,400)
        self.assertNotIn(PENDING,self.client.session)
        self.assertEqual(self.act("start",password=self.password,account_id=self.other.pk).status_code,409)
        self.assertFalse(User.objects.get(pk=self.user.pk).two_factor_enabled)
