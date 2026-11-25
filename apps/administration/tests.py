from datetime import timedelta
from io import StringIO
from uuid import uuid4

import pyotp
from django.contrib.auth import SESSION_KEY
from django.core.cache import cache
from django.core.management import call_command, CommandError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.two_factor import encrypt_secret
from apps.messenger.models import Chat, ChatInviteLink, ChatJoinRequest, ChatParticipant, Message, MessageHiddenForUser
from apps.messenger.services import get_or_create_direct_chat

from .models import PlatformAudit, PlatformReport


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class PlatformAdministrationTests(TestCase):
    password = "Test-password-1945!"

    @classmethod
    def setUpTestData(cls):
        def user(name, role=""):
            return User.objects.create_user(name, name+"@example.net", cls.password,
                platform_role=role, two_factor_secret=encrypt_secret(pyotp.random_base32()) if role else "")
        cls.owner = user("platformowner","owner")
        cls.admin = user("platformadmin","admin")
        cls.mod = user("platformmod","moderator")
        cls.member = user("platformmember")
        cls.peer = user("platformpeer")
        cls.outside = user("platformoutside")
        cls.group = Chat.objects.create(type="group",title="Test public group",username="publictest")
        ChatParticipant.objects.create(chat=cls.group,user=cls.member,role="owner")
        ChatParticipant.objects.create(chat=cls.group,user=cls.peer)
        cls.direct = get_or_create_direct_chat(cls.member,cls.peer)
        cls.reported = Message.objects.create(chat=cls.direct,sender=cls.peer,text="Reported content")
        cls.secret = Message.objects.create(chat=cls.direct,sender=cls.peer,text="Unreported private content")

    def setUp(self):
        cache.clear()
        self.clients = {}

    def client_for(self,user):
        if user.pk not in self.clients:
            client = Client()
            client.force_login(user)
            self.clients[user.pk] = client
        return self.clients[user.pk]

    def route(self,name,*args):
        return reverse("administration:"+name,args=args)

    def act(self,user,name,pk,action,**extra):
        return self.client_for(user).post(self.route(name,pk), {
            "account_id":user.pk,"action":action,"reason":"Test moderation",**extra,
        })

    def report(self,kind="message",target=None,reporter=None,**extra):
        reporter = reporter or self.member
        target = target or self.reported
        return self.client_for(reporter).post(self.route("submit_report",kind,target.pk),
            {"account_id":reporter.pk,"reason":"spam","details":"Test report",**extra})

    def test_role_hierarchy_and_two_factor_requirement(self):
        dashboard = self.route("dashboard")
        self.assertEqual(Client().get(dashboard).status_code,302)
        self.assertEqual(self.client_for(self.member).get(dashboard).status_code,403)
        self.assertEqual(self.client_for(self.mod).get(dashboard).status_code,200)
        for name in ("users","communities","audit"):
            self.assertEqual(self.client_for(self.mod).get(self.route(name)).status_code,403)
            self.assertEqual(self.client_for(self.admin).get(self.route(name)).status_code,200)
        self.assertEqual(self.client_for(self.mod).get(self.route("reports")).status_code,200)
        User.objects.filter(pk=self.mod.pk).update(two_factor_secret="")
        self.assertRedirects(self.client_for(self.mod).get(dashboard),reverse("accounts:two_factor"),fetch_redirect_response=False)
        self.assertEqual(self.act(self.mod,"report_action",1,"dismissed").status_code,403)
        self.assertFalse(self.owner.is_staff)
        self.assertFalse(self.admin.is_superuser)

    def test_grant_revoke_roles_and_forbid_escalation(self):
        self.assertEqual(self.act(self.admin,"user_action",self.member.pk,"role",role="admin").status_code,403)
        self.assertEqual(self.act(self.owner,"user_action",self.member.pk,"role",role="admin").status_code,400)
        self.member.two_factor_secret = encrypt_secret(pyotp.random_base32())
        self.member.save(update_fields=["two_factor_secret"])
        old = self.client_for(self.member)
        self.assertEqual(self.act(self.owner,"user_action",self.member.pk,"role",role="moderator").status_code,302)
        self.member.refresh_from_db()
        self.assertEqual(self.member.platform_role,"moderator")
        self.assertEqual(old.get(reverse("messenger:home")).status_code,302)
        self.assertFalse(self.member.is_staff)
        self.assertEqual(self.act(self.owner,"user_action",self.owner.pk,"role",role="").status_code,403)
        self.assertEqual(self.act(self.owner,"user_action",self.member.pk,"role",role="owner").status_code,403)
        self.assertEqual(self.act(self.admin,"user_action",self.member.pk,"suspend").status_code,403)
        self.assertEqual(self.act(self.owner,"user_action",self.member.pk,"role",role="").status_code,302)
        self.member.refresh_from_db()
        self.assertEqual(self.member.platform_role,"")
        self.assertEqual(PlatformAudit.objects.filter(action="role",target_id=self.member.pk).count(),2)

    def test_suspension_invalidates_sessions_and_restore_does_not_revalidate(self):
        old = self.client_for(self.member)
        multi = Client()
        multi.force_login(self.peer)
        multi.post(reverse("accounts:add_account"),{"username":self.member.username,"password":self.password})
        multi.post(reverse("accounts:switch_account",args=[self.peer.pk]))
        self.assertEqual(self.act(self.admin,"user_action",self.member.pk,"suspend").status_code,302)
        self.member.refresh_from_db()
        self.assertFalse(self.member.is_active)
        self.assertIsNotNone(self.member.platform_suspended_at)
        self.assertEqual(old.get(reverse("messenger:home")).status_code,302)
        self.assertFalse(Client().login(username=self.member.username,password=self.password))
        denied = Client().post(reverse("accounts:login"),{"username":self.member.username,"password":self.password})
        self.assertContains(denied,"Аккаунт заблокирован")
        multi.post(reverse("accounts:switch_account",args=[self.member.pk]))
        self.assertEqual(int(multi.session[SESSION_KEY]),self.peer.pk)
        self.assertTrue(Message.objects.filter(pk=self.reported.pk).exists())
        self.assertEqual(self.act(self.admin,"user_action",self.member.pk,"restore").status_code,302)
        self.member.refresh_from_db()
        self.assertTrue(self.member.is_active)
        self.assertIsNone(self.member.platform_suspended_at)
        self.assertEqual(old.get(reverse("messenger:home")).status_code,302)
        self.assertTrue(Client().login(username=self.member.username,password=self.password))

    def test_revoke_sessions_protected_accounts_and_stale_account(self):
        old = self.client_for(self.member)
        self.assertEqual(self.act(self.admin,"user_action",self.member.pk,"revoke_sessions",account_id=self.owner.pk).status_code,400)
        self.assertEqual(self.act(self.admin,"user_action",self.owner.pk,"suspend").status_code,403)
        self.assertEqual(self.act(self.admin,"user_action",self.mod.pk,"revoke_sessions").status_code,403)
        User.objects.filter(pk=self.outside.pk).update(is_staff=True)
        self.assertEqual(self.act(self.owner,"user_action",self.outside.pk,"suspend").status_code,403)
        self.assertEqual(self.act(self.admin,"user_action",self.member.pk,"revoke_sessions",reason="").status_code,400)
        self.assertEqual(self.act(self.admin,"user_action",self.member.pk,"revoke_sessions").status_code,302)
        self.assertEqual(old.get(reverse("messenger:home")).status_code,302)

    def test_public_restriction_persists_and_invites_are_revoked(self):
        invite = ChatInviteLink.objects.create(chat=self.group,creator=self.member,token=uuid4().hex)
        join = ChatJoinRequest.objects.create(chat=self.group,user=self.outside,invite=invite)
        self.assertEqual(self.act(self.mod,"community_action",self.group.pk,"restrict_public").status_code,403)
        self.assertEqual(self.act(self.admin,"community_action",self.direct.pk,"restrict_public").status_code,404)
        self.assertEqual(self.act(self.admin,"community_action",self.group.pk,"restrict_public").status_code,302)
        self.group.refresh_from_db()
        self.assertTrue(self.group.platform_public_restricted)
        self.assertIsNone(self.group.username)
        owner = self.client_for(self.member)
        response = owner.post(reverse("messenger:community_settings",args=[self.group.pk]),
            {"section":"type","visibility":"public","username":"newpublic"})
        self.assertEqual(response.status_code,400,response.content)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Chat.objects.filter(pk=self.group.pk).update(username="bypass")
        self.assertEqual(self.act(self.admin,"community_action",self.group.pk,"revoke_invites").status_code,302)
        invite.refresh_from_db()
        join.refresh_from_db()
        self.assertIsNotNone(invite.revoked_at)
        self.assertEqual(join.status,"rejected")
        self.assertEqual(self.act(self.admin,"community_action",self.group.pk,"restore_public").status_code,302)
        self.assertEqual(owner.post(reverse("messenger:community_settings",args=[self.group.pk]),
            {"section":"type","visibility":"public","username":"newpublic"}).status_code,200)

    def test_reporting_checks_visibility_duplicates_and_rate_limit(self):
        self.assertEqual(self.report(reporter=self.outside).status_code,404)
        self.assertEqual(self.report(reporter=self.peer).status_code,404)
        self.assertEqual(self.report(account_id=self.outside.pk).status_code,409)
        self.assertEqual(self.report(reason="invalid").status_code,400)
        self.assertEqual(self.report().status_code,302)
        self.assertEqual(self.report().status_code,302)
        self.assertEqual(PlatformReport.objects.count(),1)
        MessageHiddenForUser.objects.create(message=self.secret,user=self.member)
        self.assertEqual(self.report(target=self.secret).status_code,404)
        self.assertEqual(self.report("user",self.peer).status_code,302)
        self.assertEqual(self.report("community",self.group,reporter=self.outside).status_code,302)
        self.group.username=None
        self.group.save(update_fields=["username"])
        self.assertEqual(self.report("community",self.group,reporter=self.outside).status_code,404)
        PlatformReport.objects.bulk_create([
            PlatformReport(reporter=self.member,kind="user",target_id=100+i,target_label="Other",reason="spam",status="resolved") for i in range(8)
        ])
        self.assertEqual(self.report("user",self.outside).status_code,429)

    def test_moderator_can_only_view_and_delete_reported_message(self):
        self.assertEqual(self.report().status_code,302)
        row = PlatformReport.objects.get()
        url = self.route("report_detail",row.pk)
        self.assertEqual(self.client_for(self.member).get(url).status_code,403)
        response = self.client_for(self.mod).get(url)
        self.assertContains(response,"Reported content")
        self.assertNotContains(response,"Unreported private content")
        self.assertIn("no-store",response["Cache-Control"])
        self.assertEqual(self.act(self.mod,"report_action",row.pk,"delete_message",revision="0").status_code,409)
        self.assertEqual(self.act(self.mod,"report_action",row.pk,"delete_message",revision=self.reported.sync_revision).status_code,302)
        row.refresh_from_db()
        self.reported.refresh_from_db()
        self.assertEqual(row.status,"resolved")
        self.assertTrue(self.reported.is_deleted)
        self.assertEqual(self.reported.text,"")
        self.assertTrue(Message.objects.filter(pk=self.secret.pk,is_deleted=False).exists())
        self.assertEqual(self.act(self.mod,"report_action",row.pk,"dismissed").status_code,409)
        self.assertTrue(PlatformAudit.objects.filter(action="delete_reported_message",target_id=self.reported.pk).exists())
        self.assertNotContains(self.client_for(self.mod).get(url),"Reported content")

    def test_resolved_reports_no_longer_expose_current_message(self):
        self.report()
        row = PlatformReport.objects.get()
        self.assertEqual(self.act(self.mod,"report_action",row.pk,"dismissed").status_code,302)
        self.assertNotContains(self.client_for(self.mod).get(self.route("report_detail",row.pk)),"Reported content")
        self.assertTrue(Message.objects.filter(pk=self.reported.pk,is_deleted=False).exists())

    def test_owner_bootstrap_and_no_last_owner_removal(self):
        out = StringIO()
        with self.assertRaises(CommandError):
            call_command("platform_admin",self.member.username,reason="Bootstrap",stdout=out)
        with self.assertRaises(CommandError):
            call_command("platform_admin",self.owner.username,role="member",reason="Remove",stdout=out)
        self.member.two_factor_secret = encrypt_secret(pyotp.random_base32())
        self.member.save(update_fields=["two_factor_secret"])
        call_command("platform_admin",self.member.username,reason="Bootstrap",stdout=out)
        self.member.refresh_from_db()
        self.assertEqual(self.member.platform_role,"owner")
        call_command("platform_admin",self.owner.username,role="member",reason="Transfer",stdout=out)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.platform_role,"")
        self.assertTrue(PlatformAudit.objects.filter(actor_label="server CLI",action="role_change").exists())

    def test_admin_accounts_cannot_be_auto_deleted_or_self_deleted(self):
        from apps.accounts.lifecycle import delete_user_account
        from apps.accounts.privacy import account_expired_for_inactivity
        User.objects.filter(pk=self.owner.pk).update(date_joined=timezone.now()-timedelta(days=500),last_seen_at=None)
        self.owner.refresh_from_db()
        self.assertFalse(account_expired_for_inactivity(self.owner))
        delete_user_account(self.owner)
        self.assertTrue(User.objects.filter(pk=self.owner.pk).exists())
        response = self.client_for(self.owner).post(reverse("accounts:delete_account"),
            {"account_id":self.owner.pk,"username":self.owner.username,"password":self.password,"confirm":"on"})
        self.assertContains(response,"Сначала необходимо снять административные полномочия")
        self.assertTrue(User.objects.filter(pk=self.owner.pk).exists())

    def test_csrf_and_search_filters(self):
        client=Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(self.route("user_action",self.member.pk),{"account_id":self.admin.pk,"action":"suspend","reason":"test"}).status_code,403)
        self.assertEqual(self.client_for(self.admin).get(self.route("user_action",self.member.pk)).status_code,405)
        response = self.client_for(self.admin).get(self.route("users"),{"q":"platformmember"})
        self.assertContains(response,"platformmember")
        self.assertNotContains(response,"platformpeer")
        response = self.client_for(self.admin).get(self.route("communities"),{"q":"Test public"})
        self.assertContains(response,"Test public group")
        self.assertNotContains(response,"Личный чат")
