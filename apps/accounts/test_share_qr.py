import base64
from io import BytesIO
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.messenger.models import Chat, ChatInviteLink, ChatParticipant


@override_settings(SOVIETGRAM_PUBLIC_URL="https://share.example")
class ShareQrTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.owner = User.objects.create_user("qr_owner", "owner@example.test", "Test-pass-1945!")
        cls.member = User.objects.create_user("qr_member", "member@example.test", "Test-pass-1945!")
        cls.admin = User.objects.create_user("qr_admin", "admin@example.test", "Test-pass-1945!")
        cls.chat = Chat.objects.create(type=Chat.Type.GROUP, title="Private QR group")
        ChatParticipant.objects.create(chat=cls.chat, user=cls.owner, role=ChatParticipant.Role.OWNER)
        ChatParticipant.objects.create(chat=cls.chat, user=cls.member, role=ChatParticipant.Role.MEMBER)
        cls.admin_member = ChatParticipant.objects.create(
            chat=cls.chat, user=cls.admin, role=ChatParticipant.Role.ADMIN, admin_permissions=["invite_users"],
        )
        cls.invite = ChatInviteLink.objects.create(chat=cls.chat, creator=cls.owner, token="private-qr-token")
        cls.invite_url = reverse("messenger:invite_qr", args=[cls.chat.pk, cls.invite.pk])

    def setUp(self):
        cache.clear()

    def assert_card(self, response, path):
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["share_url"], "https://share.example" + path)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertContains(response, 'download="sovietgram-qr.png"')
        png = base64.b64decode(response.context["qr_png"].split(",", 1)[1])
        with Image.open(BytesIO(png)) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.width, image.height)
            self.assertGreater(image.width, 100)

    def test_public_profile_qr_and_inactive_profile(self):
        path = reverse("accounts:public_profile", args=[self.owner.username])
        qr_url = reverse("accounts:profile_qr", args=[self.owner.username])
        self.assert_card(self.client.get(qr_url), path)
        self.assertContains(self.client.get(path), qr_url)
        self.owner.is_active = False
        self.owner.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(qr_url).status_code, 404)

    def test_invite_requires_authorized_member_and_does_not_consume_link(self):
        self.assertEqual(self.client.get(self.invite_url).status_code, 302)
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(self.invite_url).status_code, 404)
        self.client.force_login(self.owner)
        self.assert_card(self.client.get(self.invite_url), reverse("messenger:join_invite", args=[self.invite.token]))
        self.invite.refresh_from_db()
        self.assertEqual(self.invite.usage_count, 0)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.invite_url).status_code, 200)
        self.admin_member.admin_permissions = []
        self.admin_member.save(update_fields=["admin_permissions"])
        self.assertEqual(self.client.get(self.invite_url).status_code, 404)

    def test_expired_exhausted_and_revoked_invites(self):
        self.client.force_login(self.owner)
        for changes in (
            {"expires_at": timezone.now() - timedelta(seconds=1)},
            {"expires_at": None, "usage_limit": 1, "usage_count": 1},
            {"usage_limit": None, "revoked_at": timezone.now()},
        ):
            ChatInviteLink.objects.filter(pk=self.invite.pk).update(**changes)
            self.assertEqual(self.client.get(self.invite_url).status_code, 404)
