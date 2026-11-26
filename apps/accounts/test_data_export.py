import io
import json
import zipfile
from datetime import timedelta
from tempfile import TemporaryDirectory

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.messenger.models import Chat, ChatParticipant, Contact, Message, MessageAttachment, MessageHiddenForUser
from apps.messenger.services import get_or_create_direct_chat
from .models import User


class AccountExportTests(TestCase):
    def setUp(self):
        cache.clear()
        work = TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.enterContext(override_settings(MEDIA_ROOT=work.name))
        self.alice = User.objects.create_user("export_alice", "export-a@example.net", "Password-1945!")
        self.bob = User.objects.create_user("export_bob", "export-b@example.net", "Password-1945!")
        self.chat = get_or_create_direct_chat(self.alice, self.bob)
        self.url = reverse("accounts:account_export")
        self.client.force_login(self.alice)

    def test_zip_scope_files_and_no_credentials(self):
        Contact.objects.create(owner=self.alice, user=self.bob, alias="Personal label")
        own = Message.objects.create(chat=self.chat, sender=self.alice, text="Own message")
        Message.objects.create(chat=self.chat, sender=self.bob, text="Other private text")
        hidden = Message.objects.create(chat=self.chat, sender=self.alice, text="Hidden message")
        MessageHiddenForUser.objects.create(user=self.alice, message=hidden)
        Message.objects.create(chat=self.chat, sender=self.alice, text="Expired message",
                               expires_at=timezone.now()-timedelta(seconds=1))
        protected = Chat.objects.create(type=Chat.Type.GROUP, title="Protected", protect_content=True)
        ChatParticipant.objects.create(chat=protected, user=self.alice, role="owner")
        Message.objects.create(chat=protected, sender=self.alice, text="Protected content")
        attachment = MessageAttachment.objects.create(
            message=own, file=ContentFile(b"test file", name="example.txt"),
            original_name="example.txt", size=9, kind="file",
        )
        response = self.client.post(self.url, {"account_id":self.alice.pk,
            "password":"Password-1945!", "include_files":"on"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertIn("no-store", response["Cache-Control"])
        with zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content))) as bundle:
            profile = json.loads(bundle.read("profile.json"))
            self.assertEqual(profile["email"], self.alice.email)
            for field in ("password", "two_factor_secret", "two_factor_recovery_hashes", "security_version"):
                self.assertNotIn(field, profile)
            entries = [json.loads(line) for line in bundle.read("messages.jsonl").splitlines()]
            self.assertEqual([row["text"] for row in entries], ["Own message"])
            self.assertIn("Personal label", bundle.read("contacts.jsonl").decode())
            self.assertEqual(bundle.read(f"media/attachment-{attachment.pk}.bin"), b"test file")

    def test_credentials_account_guard_and_auth_required(self):
        for data in (
            {"account_id":self.alice.pk, "password":"bad"},
            {"account_id":self.bob.pk, "password":"Password-1945!"},
        ):
            response = self.client.post(self.url, data)
            self.assertFalse(response.streaming)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
