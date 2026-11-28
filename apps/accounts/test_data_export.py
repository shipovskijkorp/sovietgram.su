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

    def test_comment_export_excludes_other_people_and_protected_posts(self):
        from uuid import uuid4
        from apps.messenger.models import ChannelComment, ChannelCommentAttachment, ChannelCommentReaction
        from apps.messenger.test_gif_and_formatting import gif_bytes

        channel=Chat.objects.create(type=Chat.Type.CHANNEL,title="Open channel",comments_enabled=True)
        ChatParticipant.objects.create(chat=channel,user=self.alice)
        ChatParticipant.objects.create(chat=channel,user=self.bob,role="owner")
        post=Message.objects.create(chat=channel,sender=self.bob,text="Public post")
        own=ChannelComment.objects.create(post=post,author=self.alice,text="My comment",client_id=uuid4())
        other=ChannelComment.objects.create(post=post,author=self.bob,text="Other comment",client_id=uuid4())
        attachment=ChannelCommentAttachment.objects.create(comment=own,original_name="cat.gif",kind="image",
            mime_type="image/gif",size=len(gif_bytes()),file=ContentFile(gif_bytes(),name="cat.gif"))
        foreign=ChannelCommentAttachment.objects.create(comment=other,original_name="foreign.gif",kind="image",
            mime_type="image/gif",size=len(gif_bytes()),file=ContentFile(gif_bytes(),name="foreign.gif"))
        ChannelCommentReaction.objects.create(comment=other,user=self.alice,emoji="👍")
        ChannelCommentReaction.objects.create(comment=own,user=self.bob,emoji="🔥")
        fields={"account_id":self.alice.pk,"password":"Password-1945!","include_files":"on"}
        response=self.client.post(self.url,fields)
        self.assertEqual(response.status_code,200)
        with zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content))) as bundle:
            comments=[json.loads(line) for line in bundle.read("channel_comments.jsonl").splitlines()]
            self.assertEqual([row["id"] for row in comments],[own.pk])
            media=[json.loads(line) for line in bundle.read("comment_attachments.jsonl").splitlines()]
            self.assertEqual([row["id"] for row in media],[attachment.pk])
            self.assertEqual(bundle.read(media[0]["archive_path"]),gif_bytes())
            self.assertNotIn(f"comments/attachment-{foreign.pk}.bin",bundle.namelist())
            reactions=[json.loads(line) for line in bundle.read("comment_reactions.jsonl").splitlines()]
            self.assertEqual([(row["comment_id"],row["emoji"]) for row in reactions],[(other.pk,"👍")])
        channel.protect_content=True
        channel.save(update_fields=["protect_content"])
        response=self.client.post(self.url,fields)
        self.assertEqual(response.status_code,200)
        with zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content))) as bundle:
            for name in ("channel_comments.jsonl","comment_attachments.jsonl","comment_reactions.jsonl"):
                self.assertEqual(bundle.read(name),b"")
            self.assertNotIn(f"comments/attachment-{attachment.pk}.bin",bundle.namelist())

    def test_two_factor_is_required_and_export_limit_is_explicit(self):
        import pyotp
        from unittest.mock import patch
        from .two_factor import encrypt_secret

        secret = pyotp.random_base32()
        User.objects.filter(pk=self.alice.pk).update(two_factor_secret=encrypt_secret(secret))
        self.alice.refresh_from_db()
        self.client.force_login(self.alice)
        fields = {"account_id": self.alice.pk, "password": "Password-1945!"}
        self.assertFalse(self.client.post(self.url, fields).streaming)
        now = timezone.now()
        code = pyotp.TOTP(secret).at(int(now.timestamp()))
        with patch("apps.accounts.two_factor.timezone.now", return_value=now), \
             patch("apps.accounts.data_export.MAX_BYTES", 1):
            response = self.client.post(self.url, {**fields, "otp": code})
        self.assertFalse(response.streaming)
        self.assertContains(response, "Экспорт превышает")
        self.alice.refresh_from_db()
        self.assertGreaterEqual(self.alice.two_factor_last_step, 0)

    def test_credentials_account_guard_and_auth_required(self):
        for data in (
            {"account_id":self.alice.pk, "password":"bad"},
            {"account_id":self.bob.pk, "password":"Password-1945!"},
        ):
            response = self.client.post(self.url, data)
            self.assertFalse(response.streaming)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
