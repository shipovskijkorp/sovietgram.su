import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.messenger.models import (
    Chat,
    ChatAdminLog,
    ChatParticipant,
    Message,
    MessageAttachment,
)
from apps.messenger.services import get_or_create_direct_chat

from .lifecycle import delete_user_account
from .models import User


class AccountLifecycleTests(TestCase):
    password = "Sovietgram-test-1945"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media_dir = tempfile.TemporaryDirectory()
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_dir.name)
        cls._media_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._media_override.disable()
        cls._media_dir.cleanup()
        super().tearDownClass()

    def setUp(self):
        self.alice = User.objects.create_user(
            username="lifecycle_alice",
            email="lifecycle-alice@example.com",
            password=self.password,
        )
        self.bob = User.objects.create_user(
            username="lifecycle_bob",
            email="lifecycle-bob@example.com",
            password=self.password,
        )
        self.charlie = User.objects.create_user(
            username="lifecycle_charlie",
            email="lifecycle-charlie@example.com",
            password=self.password,
        )

    def test_account_deletion_removes_private_chat_and_stored_files(self):
        chat = get_or_create_direct_chat(self.alice, self.bob)
        message = Message.objects.create(
            chat=chat,
            sender=self.alice,
            text="private payload",
        )
        attachment = MessageAttachment.objects.create(
            message=message,
            file=SimpleUploadedFile(
                "secret.txt",
                b"private-data",
                content_type="text/plain",
            ),
            kind=MessageAttachment.Kind.FILE,
            original_name="secret.txt",
            mime_type="text/plain",
            size=12,
        )
        file_name = attachment.file.name
        storage = attachment.file.storage
        self.assertTrue(storage.exists(file_name))

        delete_user_account(self.alice)

        self.assertFalse(User.objects.filter(pk=self.alice.pk).exists())
        self.assertFalse(Chat.objects.filter(pk=chat.pk).exists())
        self.assertFalse(storage.exists(file_name))

    def test_account_deletion_transfers_owned_community_to_admin(self):
        group = Chat.objects.create(type=Chat.Type.GROUP, title="Lifecycle group")
        ChatParticipant.objects.create(
            chat=group,
            user=self.alice,
            role=ChatParticipant.Role.OWNER,
        )
        ChatParticipant.objects.create(
            chat=group,
            user=self.bob,
            role=ChatParticipant.Role.ADMIN,
        )
        ChatParticipant.objects.create(
            chat=group,
            user=self.charlie,
            role=ChatParticipant.Role.MEMBER,
        )
        message = Message.objects.create(
            chat=group,
            sender=self.alice,
            text="owner file",
        )
        attachment = MessageAttachment.objects.create(
            message=message,
            file=SimpleUploadedFile(
                "owner.txt",
                b"owner-data",
                content_type="text/plain",
            ),
            kind=MessageAttachment.Kind.FILE,
            original_name="owner.txt",
            mime_type="text/plain",
            size=10,
        )
        file_name = attachment.file.name
        storage = attachment.file.storage

        delete_user_account(self.alice)

        group.refresh_from_db()
        self.assertEqual(
            ChatParticipant.objects.get(chat=group, user=self.bob).role,
            ChatParticipant.Role.OWNER,
        )
        self.assertEqual(
            ChatParticipant.objects.get(chat=group, user=self.charlie).role,
            ChatParticipant.Role.MEMBER,
        )
        self.assertFalse(
            ChatParticipant.objects.filter(chat=group, user_id=self.alice.pk).exists()
        )
        self.assertFalse(storage.exists(file_name))
        self.assertTrue(
            ChatAdminLog.objects.filter(
                chat=group,
                action="owner_transfer",
                target_user=self.bob,
            ).exists()
        )

    def test_account_deletion_promotes_oldest_member_when_no_admin_exists(self):
        channel = Chat.objects.create(type=Chat.Type.CHANNEL, title="Lifecycle channel")
        ChatParticipant.objects.create(
            chat=channel,
            user=self.alice,
            role=ChatParticipant.Role.OWNER,
        )
        first = ChatParticipant.objects.create(
            chat=channel,
            user=self.bob,
            role=ChatParticipant.Role.MEMBER,
        )
        ChatParticipant.objects.create(
            chat=channel,
            user=self.charlie,
            role=ChatParticipant.Role.MEMBER,
        )

        delete_user_account(self.alice)

        first.refresh_from_db()
        self.assertEqual(first.role, ChatParticipant.Role.OWNER)

    def test_account_deletion_removes_empty_owned_community_and_avatar_files(self):
        self.alice.avatar.save(
            "avatar.png",
            SimpleUploadedFile("avatar.png", b"avatar-bytes", content_type="image/png"),
            save=True,
        )
        avatar_name = self.alice.avatar.name
        avatar_storage = self.alice.avatar.storage

        channel = Chat.objects.create(type=Chat.Type.CHANNEL, title="Empty channel")
        channel.avatar.save(
            "channel.png",
            SimpleUploadedFile("channel.png", b"channel-avatar", content_type="image/png"),
            save=True,
        )
        channel_avatar_name = channel.avatar.name
        channel_avatar_storage = channel.avatar.storage
        ChatParticipant.objects.create(
            chat=channel,
            user=self.alice,
            role=ChatParticipant.Role.OWNER,
        )

        delete_user_account(self.alice)

        self.assertFalse(Chat.objects.filter(pk=channel.pk).exists())
        self.assertFalse(avatar_storage.exists(avatar_name))
        self.assertFalse(channel_avatar_storage.exists(channel_avatar_name))
