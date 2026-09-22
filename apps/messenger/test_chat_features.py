import tempfile

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User

from .models import Chat, ChatParticipant, Message, MessageAttachment, PinnedMessage
from .services import get_or_create_direct_chat


class ChatFeatureTests(TestCase):
    password = "Stalingram-test-1945"

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
        cache.clear()
        self.alice = User.objects.create_user("alice", "alice@example.com", self.password)
        self.bob = User.objects.create_user("bob", "bob@example.com", self.password)
        self.charlie = User.objects.create_user("charlie", "charlie@example.com", self.password)
        self.chat = get_or_create_direct_chat(self.alice, self.bob)
        self.client.force_login(self.alice)

    def test_direct_chat_uses_private_type_and_member_roles(self):
        self.assertEqual(self.chat.type, Chat.Type.PRIVATE)
        roles = set(
            self.chat.memberships.values_list("role", flat=True)
        )
        self.assertEqual(roles, {ChatParticipant.Role.MEMBER})

    def test_group_and_channel_types_and_roles_are_available(self):
        group = Chat.objects.create(type=Chat.Type.GROUP)
        channel = Chat.objects.create(type=Chat.Type.CHANNEL)
        owner = ChatParticipant.objects.create(
            chat=group,
            user=self.alice,
            role=ChatParticipant.Role.OWNER,
        )
        admin = ChatParticipant.objects.create(
            chat=group,
            user=self.bob,
            role=ChatParticipant.Role.ADMIN,
        )
        member = ChatParticipant.objects.create(
            chat=channel,
            user=self.charlie,
        )

        self.assertEqual(group.type, "group")
        self.assertEqual(channel.type, "channel")
        self.assertEqual(owner.role, "owner")
        self.assertEqual(admin.role, "admin")
        self.assertEqual(member.role, "member")

    def test_group_creation_adds_owner_and_requested_members(self):
        response = self.client.post(
            reverse("messenger:create_community"),
            {
                "type": Chat.Type.GROUP,
                "title": "Совет разработчиков",
                "username": "",
                "description": "Обсуждаем великие стройки.",
                "members": "@bob, @charlie",
            },
        )
        group = Chat.objects.get(type=Chat.Type.GROUP)
        self.assertRedirects(response, reverse("messenger:chat", args=[group.pk]))
        self.assertEqual(group.title, "Совет разработчиков")
        self.assertEqual(group.memberships.count(), 3)
        self.assertEqual(
            group.memberships.get(user=self.alice).role,
            ChatParticipant.Role.OWNER,
        )
        self.assertEqual(
            group.memberships.get(user=self.bob).role,
            ChatParticipant.Role.MEMBER,
        )

    def test_channel_can_be_found_joined_and_is_read_only_for_member(self):
        response = self.client.post(
            reverse("messenger:create_community"),
            {
                "type": Chat.Type.CHANNEL,
                "title": "Радио Stalingram",
                "username": "radio_stalingram",
                "description": "Вести с цифровых полей.",
                "members": "",
            },
        )
        channel = Chat.objects.get(type=Chat.Type.CHANNEL)
        self.assertRedirects(response, reverse("messenger:chat", args=[channel.pk]))

        search = self.client.get(
            reverse("messenger:contacts"),
            {"q": "radio_stalingram"},
        )
        self.assertContains(search, "Радио Stalingram")
        self.assertContains(search, "@radio_stalingram")

        self.client.force_login(self.charlie)
        join = self.client.post(
            reverse("messenger:join_public_chat", args=[channel.username])
        )
        self.assertRedirects(join, reverse("messenger:chat", args=[channel.pk]))
        membership = channel.memberships.get(user=self.charlie)
        self.assertEqual(membership.role, ChatParticipant.Role.MEMBER)

        forbidden = self.client.post(
            reverse("messenger:send_message", args=[channel.pk]),
            {"text": "Попытка захватить эфир"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(forbidden.status_code, 403)
        self.assertFalse(Message.objects.filter(chat=channel).exists())

        source_chat = get_or_create_direct_chat(self.charlie, self.bob)
        source = Message.objects.create(
            chat=source_chat,
            sender=self.charlie,
            text="Обход через пересылку",
        )
        forwarded = self.client.post(
            reverse(
                "messenger:forward_message",
                args=[source_chat.pk, source.pk],
            ),
            {"target_chat_id": channel.pk},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(forwarded.status_code, 403)
        self.assertFalse(Message.objects.filter(chat=channel).exists())

        self.client.force_login(self.alice)
        allowed = self.client.post(
            reverse("messenger:send_message", args=[channel.pk]),
            {"text": "Говорит Stalingram."},
        )
        self.assertEqual(allowed.status_code, 302)
        self.assertTrue(
            Message.objects.filter(chat=channel, text="Говорит Stalingram.").exists()
        )

    def test_group_and_channel_pages_render_without_private_chat_assumptions(self):
        group = Chat.objects.create(type=Chat.Type.GROUP, title="Монтажный отдел")
        ChatParticipant.objects.create(
            chat=group,
            user=self.alice,
            role=ChatParticipant.Role.OWNER,
        )
        channel = Chat.objects.create(
            type=Chat.Type.CHANNEL,
            title="Красный эфир",
            username="red_air",
        )
        ChatParticipant.objects.create(
            chat=channel,
            user=self.alice,
            role=ChatParticipant.Role.OWNER,
        )

        group_response = self.client.get(
            reverse("messenger:chat", args=[group.pk])
        )
        channel_response = self.client.get(
            reverse("messenger:chat", args=[channel.pk])
        )
        self.assertEqual(group_response.status_code, 200)
        self.assertContains(group_response, "Монтажный отдел")
        self.assertEqual(channel_response.status_code, 200)
        self.assertContains(channel_response, "Красный эфир")
        self.assertContains(channel_response, "@red_air")

    def test_calls_page_is_available_without_call_history(self):
        response = self.client.get(reverse("messenger:calls"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Звонков пока нет")

    def test_saved_messages_chat_is_single_participant_chat(self):
        response = self.client.get(reverse("messenger:saved_messages"))
        self.assertEqual(response.status_code, 302)
        saved = self.alice.messenger_chats.get(direct_key=f"self:{self.alice.pk}")
        self.assertEqual(saved.participants.count(), 1)
        self.assertEqual(saved.participants.first(), self.alice)

    def test_message_can_reply_to_message_from_same_chat(self):
        original = Message.objects.create(chat=self.chat, sender=self.bob, text="Исходное")
        response = self.client.post(
            reverse("messenger:send_message", args=[self.chat.pk]),
            {"text": "Ответ", "reply_to": original.pk},
        )
        self.assertEqual(response.status_code, 302)
        reply = Message.objects.exclude(pk=original.pk).get()
        self.assertEqual(reply.reply_to, original)

    def test_reply_to_foreign_chat_is_rejected(self):
        other_chat = get_or_create_direct_chat(self.alice, self.charlie)
        foreign = Message.objects.create(chat=other_chat, sender=self.charlie, text="Не отсюда")
        response = self.client.post(
            reverse("messenger:send_message", args=[self.chat.pk]),
            {"text": "Ответ", "reply_to": foreign.pk},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Message.objects.filter(chat=self.chat).count(), 0)

    def test_sender_can_edit_text_and_caption(self):
        message = Message.objects.create(chat=self.chat, sender=self.alice, text="Старый текст")
        response = self.client.post(
            reverse("messenger:edit_message", args=[self.chat.pk, message.pk]),
            {"text": "Новый текст"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        message.refresh_from_db()
        self.assertEqual(message.text, "Новый текст")
        self.assertIsNotNone(message.edited_at)

    def test_other_user_cannot_edit_message(self):
        message = Message.objects.create(chat=self.chat, sender=self.bob, text="Чужое")
        response = self.client.post(
            reverse("messenger:edit_message", args=[self.chat.pk, message.pk]),
            {"text": "Подмена"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 404)

    def test_other_participant_cannot_delete_message(self):
        message = Message.objects.create(chat=self.chat, sender=self.alice, text="Не трогать")
        self.client.force_login(self.bob)
        response = self.client.post(
            reverse("messenger:delete_message", args=[self.chat.pk, message.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 404)
        message.refresh_from_db()
        self.assertFalse(message.is_deleted)
        self.assertEqual(message.text, "Не трогать")

    def test_sender_can_delete_own_message(self):
        message = Message.objects.create(chat=self.chat, sender=self.alice, text="Удалить")
        response = self.client.post(
            reverse("messenger:delete_message", args=[self.chat.pk, message.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        message.refresh_from_db()
        self.assertTrue(message.is_deleted)
        self.assertEqual(message.text, "")

    def test_forward_copies_message_and_attachment(self):
        source = Message.objects.create(chat=self.chat, sender=self.bob, text="Перешли меня")
        MessageAttachment.objects.create(
            message=source,
            file=SimpleUploadedFile("doc.txt", b"test-content", content_type="text/plain"),
            kind=MessageAttachment.Kind.FILE,
            original_name="doc.txt",
            mime_type="text/plain",
            size=12,
        )
        target = get_or_create_direct_chat(self.alice, self.charlie)
        response = self.client.post(
            reverse("messenger:forward_message", args=[self.chat.pk, source.pk]),
            {"target_chat_id": target.pk},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        forwarded = Message.objects.filter(chat=target).get()
        self.assertEqual(forwarded.text, source.text)
        self.assertEqual(forwarded.forwarded_from, source)
        self.assertEqual(forwarded.forwarded_from_username, "bob")
        self.assertEqual(forwarded.attachments.count(), 1)

    def test_message_pin_toggles(self):
        message = Message.objects.create(chat=self.chat, sender=self.bob, text="Закрепить")
        url = reverse("messenger:pin_message", args=[self.chat.pk, message.pk])
        self.client.post(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertTrue(PinnedMessage.objects.filter(chat=self.chat, message=message).exists())
        self.client.post(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertFalse(PinnedMessage.objects.filter(chat=self.chat, message=message).exists())

    def test_chat_pin_mute_and_archive_are_per_user(self):
        url = reverse("messenger:chat_action", args=[self.chat.pk])
        self.client.post(url, {"action": "pin"})
        self.client.post(url, {"action": "mute"})
        membership = ChatParticipant.objects.get(chat=self.chat, user=self.alice)
        self.assertTrue(membership.is_pinned)
        self.assertTrue(membership.is_muted)

        self.client.post(url, {"action": "archive"})
        membership.refresh_from_db()
        self.assertTrue(membership.is_archived)
        self.assertFalse(ChatParticipant.objects.get(chat=self.chat, user=self.bob).is_archived)

    def test_draft_and_typing_state_are_saved(self):
        draft_url = reverse("messenger:save_draft", args=[self.chat.pk])
        typing_url = reverse("messenger:typing", args=[self.chat.pk])
        self.assertEqual(self.client.post(draft_url, {"text": "Черновик"}).status_code, 200)
        self.assertEqual(self.client.post(typing_url).status_code, 200)
        membership = ChatParticipant.objects.get(chat=self.chat, user=self.alice)
        self.assertEqual(membership.draft_text, "Черновик")
        self.assertIsNotNone(membership.last_typing_at)

    def test_search_finds_message_text_and_filename(self):
        text_message = Message.objects.create(chat=self.chat, sender=self.bob, text="секретный план")
        file_message = Message.objects.create(chat=self.chat, sender=self.alice, text="")
        MessageAttachment.objects.create(
            message=file_message,
            file=SimpleUploadedFile("report.pdf", b"pdf", content_type="application/pdf"),
            kind=MessageAttachment.Kind.FILE,
            original_name="report.pdf",
            mime_type="application/pdf",
            size=3,
        )
        url = reverse("messenger:search_messages", args=[self.chat.pk])
        by_text = self.client.get(url, {"q": "секретный"}).json()["results"]
        by_file = self.client.get(url, {"q": "report"}).json()["results"]
        self.assertEqual(by_text[0]["id"], text_message.pk)
        self.assertEqual(by_file[0]["id"], file_message.pk)

    @override_settings(
        STALINGRAM_RATE_LIMITS={
            "send_message": {"limit": 2, "window": 60},
        }
    )
    def test_message_send_is_rate_limited(self):
        url = reverse("messenger:send_message", args=[self.chat.pk])
        first = self.client.post(url, {"text": "Первое"})
        second = self.client.post(url, {"text": "Второе"})
        limited = self.client.post(
            url,
            {"text": "Третье"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(limited.status_code, 429)
        self.assertTrue(limited.json()["rate_limited"])
        self.assertEqual(limited["Retry-After"], "60")
        self.assertEqual(Message.objects.filter(chat=self.chat).count(), 2)

    @override_settings(
        STALINGRAM_RATE_LIMITS={
            "search_messages": {"limit": 2, "window": 60},
        }
    )
    def test_message_search_is_rate_limited(self):
        url = reverse("messenger:search_messages", args=[self.chat.pk])
        self.assertEqual(self.client.get(url, {"q": "test"}).status_code, 200)
        self.assertEqual(self.client.get(url, {"q": "test"}).status_code, 200)
        limited = self.client.get(url, {"q": "test"})

        self.assertEqual(limited.status_code, 429)
        self.assertTrue(limited.json()["rate_limited"])

    @override_settings(
        STALINGRAM_RATE_LIMITS={
            "typing": {"limit": 2, "window": 60},
        }
    )
    def test_typing_updates_are_rate_limited(self):
        url = reverse("messenger:typing", args=[self.chat.pk])
        self.assertEqual(self.client.post(url).status_code, 200)
        self.assertEqual(self.client.post(url).status_code, 200)
        limited = self.client.post(url)

        self.assertEqual(limited.status_code, 429)
        self.assertTrue(limited.json()["rate_limited"])

    def test_wrong_http_method_does_not_consume_send_rate_limit(self):
        with override_settings(
            STALINGRAM_RATE_LIMITS={
                "send_message": {"limit": 1, "window": 60},
            }
        ):
            url = reverse("messenger:send_message", args=[self.chat.pk])
            self.assertEqual(self.client.get(url).status_code, 405)
            sent = self.client.post(url, {"text": "Разрешённое сообщение"})
            self.assertEqual(sent.status_code, 302)

    def test_inline_attachment_requires_chat_membership(self):
        message = Message.objects.create(chat=self.chat, sender=self.alice, text="")
        attachment = MessageAttachment.objects.create(
            message=message,
            file=SimpleUploadedFile("photo.png", b"stored-media", content_type="image/png"),
            kind=MessageAttachment.Kind.IMAGE,
            original_name="photo.png",
            mime_type="image/png",
            size=12,
        )
        view_url = reverse("messenger:view_attachment", args=[attachment.pk])
        self.assertEqual(self.client.get(view_url).status_code, 200)

        self.client.force_login(self.charlie)
        self.assertEqual(self.client.get(view_url).status_code, 404)
        self.assertEqual(
            self.client.get(
                reverse("messenger:download_attachment", args=[attachment.pk])
            ).status_code,
            404,
        )

    def test_media_upload_rejects_invalid_image_content(self):
        upload = SimpleUploadedFile(
            "fake.png",
            b"<html>not an image</html>",
            content_type="image/png",
        )
        response = self.client.post(
            reverse("messenger:send_message", args=[self.chat.pk]),
            {"attachment_mode": "media", "attachments": upload},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Message.objects.exists())

    def test_media_upload_rejects_mime_extension_mismatch(self):
        upload = SimpleUploadedFile(
            "fake.png",
            b"not-an-image",
            content_type="image/jpeg",
        )
        response = self.client.post(
            reverse("messenger:send_message", args=[self.chat.pk]),
            {"attachment_mode": "media", "attachments": upload},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Message.objects.exists())

    def test_gif_upload_is_rejected(self):
        upload = SimpleUploadedFile("animation.gif", b"GIF89a", content_type="image/gif")
        response = self.client.post(
            reverse("messenger:send_message", args=[self.chat.pk]),
            {"attachment_mode": "file", "attachments": upload},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Message.objects.exists())
