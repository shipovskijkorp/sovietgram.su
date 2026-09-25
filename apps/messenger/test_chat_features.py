import json
import tempfile
from io import BytesIO

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.accounts.models import User

from .models import (
    Chat,
    ChatAdminLog,
    ChatInviteLink,
    ChatParticipant,
    Contact,
    Message,
    MessageAttachment,
    MessageHiddenForUser,
    PinnedMessage,
)
from .services import get_or_create_direct_chat


class ChatFeatureTests(TestCase):
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

    def test_community_creation_is_exposed_as_overlay_on_messenger(self):
        response = self.client.get(reverse("messenger:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="communityWizard"', html=False)
        self.assertContains(response, 'data-community-open="group"', html=False)
        self.assertContains(response, 'data-community-open="channel"', html=False)
        self.assertContains(response, "Добавить участников")
        self.assertContains(response, self.bob.display_name)

    def test_community_creation_get_redirects_to_overlay(self):
        response = self.client.get(
            reverse("messenger:create_community"),
            {"type": Chat.Type.CHANNEL},
        )
        self.assertRedirects(
            response,
            f"{reverse('messenger:home')}?create=channel",
            fetch_redirect_response=False,
        )

    def test_group_creation_ajax_returns_chat_url(self):
        response = self.client.post(
            reverse("messenger:create_community"),
            {
                "type": Chat.Type.GROUP,
                "title": "Группа из виджета",
                "description": "",
                "username": "",
                "members": "@bob",
                "visibility": "public",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        group = Chat.objects.get(title="Группа из виджета")
        self.assertEqual(payload["redirect_url"], reverse("messenger:chat", args=[group.pk]))
        self.assertTrue(group.memberships.filter(user=self.bob).exists())

    def test_private_channel_does_not_require_public_username(self):
        response = self.client.post(
            reverse("messenger:create_community"),
            {
                "type": Chat.Type.CHANNEL,
                "title": "Закрытый канал",
                "description": "",
                "username": "",
                "members": "",
                "visibility": "private",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        channel = Chat.objects.get(title="Закрытый канал")
        self.assertIsNone(channel.username)

        search = self.client.get(reverse("messenger:contacts"), {"q": "Закрытый"})
        self.assertNotContains(search, "Закрытый канал")

    def test_public_channel_ajax_requires_username(self):
        response = self.client.post(
            reverse("messenger:create_community"),
            {
                "type": Chat.Type.CHANNEL,
                "title": "Публичный канал",
                "description": "",
                "username": "",
                "members": "",
                "visibility": "public",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("username", response.json()["errors"])
        self.assertFalse(Chat.objects.filter(title="Публичный канал").exists())

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
                "title": "Радио Sovietgram",
                "username": "radio_sovietgram",
                "description": "Вести с цифровых полей.",
                "members": "",
            },
        )
        channel = Chat.objects.get(type=Chat.Type.CHANNEL)
        self.assertRedirects(response, reverse("messenger:chat", args=[channel.pk]))

        search = self.client.get(
            reverse("messenger:contacts"),
            {"q": "radio_sovietgram"},
        )
        self.assertContains(search, "Радио Sovietgram")
        self.assertContains(search, "@radio_sovietgram")

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
            {"text": "Говорит Sovietgram."},
        )
        self.assertEqual(allowed.status_code, 302)
        self.assertTrue(
            Message.objects.filter(chat=channel, text="Говорит Sovietgram.").exists()
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

    def test_private_message_can_be_deleted_only_for_current_user(self):
        message = Message.objects.create(
            chat=self.chat,
            sender=self.alice,
            text="Локальное удаление",
        )
        self.client.force_login(self.bob)
        response = self.client.post(
            reverse("messenger:delete_message", args=[self.chat.pk, message.pk]),
            {"scope": "me"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["scope"], "me")
        message.refresh_from_db()
        self.assertFalse(message.is_deleted)
        self.assertTrue(
            MessageHiddenForUser.objects.filter(
                message=message,
                user=self.bob,
            ).exists()
        )

        bob_page = self.client.get(
            reverse("messenger:chat", args=[self.chat.pk])
        )
        self.assertNotContains(bob_page, "Локальное удаление")

        self.client.force_login(self.alice)
        alice_page = self.client.get(
            reverse("messenger:chat", args=[self.chat.pk])
        )
        self.assertContains(alice_page, "Локальное удаление")

    def test_private_message_can_be_deleted_for_everyone(self):
        message = Message.objects.create(
            chat=self.chat,
            sender=self.bob,
            text="Удаление у обоих",
        )
        response = self.client.post(
            reverse("messenger:delete_message", args=[self.chat.pk, message.pk]),
            {"scope": "everyone"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["scope"], "everyone")
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

    def test_incoming_message_unarchives_unmuted_chat_by_default(self):
        membership = self.chat.memberships.get(user=self.alice)
        membership.is_archived = True
        membership.is_muted = False
        membership.save(update_fields=["is_archived", "is_muted"])

        self.client.force_login(self.bob)
        response = self.client.post(
            reverse("messenger:send_message", args=[self.chat.pk]),
            {"text": "Вернись из архива"},
        )
        self.assertEqual(response.status_code, 302)

        membership.refresh_from_db()
        self.assertFalse(membership.is_archived)

    def test_always_keep_archived_prevents_unarchive_on_new_message(self):
        self.alice.keep_archived_chats = True
        self.alice.save(update_fields=["keep_archived_chats"])
        membership = self.chat.memberships.get(user=self.alice)
        membership.is_archived = True
        membership.is_muted = False
        membership.save(update_fields=["is_archived", "is_muted"])

        self.client.force_login(self.bob)
        self.client.post(
            reverse("messenger:send_message", args=[self.chat.pk]),
            {"text": "Оставайся в архиве"},
        )

        membership.refresh_from_db()
        self.assertTrue(membership.is_archived)

    def test_muted_archived_chat_stays_archived_on_new_message(self):
        membership = self.chat.memberships.get(user=self.alice)
        membership.is_archived = True
        membership.is_muted = True
        membership.save(update_fields=["is_archived", "is_muted"])

        self.client.force_login(self.bob)
        self.client.post(
            reverse("messenger:send_message", args=[self.chat.pk]),
            {"text": "Без уведомлений"},
        )

        membership.refresh_from_db()
        self.assertTrue(membership.is_archived)
        self.assertTrue(membership.is_muted)

    def test_sender_does_not_unarchive_own_archived_chat(self):
        membership = self.chat.memberships.get(user=self.alice)
        membership.is_archived = True
        membership.save(update_fields=["is_archived"])

        response = self.client.post(
            reverse("messenger:send_message", args=[self.chat.pk]),
            {"text": "Исходящее из архива"},
        )
        self.assertEqual(response.status_code, 302)

        membership.refresh_from_db()
        self.assertTrue(membership.is_archived)

    def test_unknown_first_message_is_archived_and_muted_when_enabled(self):
        self.alice.archive_unknown_chats = True
        self.alice.save(update_fields=["archive_unknown_chats"])

        self.client.force_login(self.bob)
        response = self.client.post(
            reverse("messenger:send_message", args=[self.chat.pk]),
            {"text": "Первое сообщение"},
        )
        self.assertEqual(response.status_code, 302)

        membership = self.chat.memberships.get(user=self.alice)
        self.assertTrue(membership.is_archived)
        self.assertTrue(membership.is_muted)

    def test_contact_first_message_is_not_auto_archived(self):
        self.alice.archive_unknown_chats = True
        self.alice.save(update_fields=["archive_unknown_chats"])
        Contact.objects.create(owner=self.alice, user=self.bob)

        self.client.force_login(self.bob)
        self.client.post(
            reverse("messenger:send_message", args=[self.chat.pk]),
            {"text": "Я в контактах"},
        )

        membership = self.chat.memberships.get(user=self.alice)
        self.assertFalse(membership.is_archived)
        self.assertFalse(membership.is_muted)

    def test_archive_location_switches_between_drawer_and_chat_list(self):
        membership = self.chat.memberships.get(user=self.alice)
        membership.is_archived = True
        membership.save(update_fields=["is_archived"])

        in_menu = self.client.get(reverse("messenger:home"))
        self.assertContains(in_menu, "Архив")
        self.assertNotContains(in_menu, 'class="archive-folder-row"', html=False)

        self.alice.archive_in_main_menu = False
        self.alice.save(update_fields=["archive_in_main_menu"])
        in_list = self.client.get(reverse("messenger:home"))
        self.assertContains(in_list, 'class="archive-folder-row"', html=False)
        self.assertContains(in_list, self.bob.display_name)

        archive = self.client.get(reverse("messenger:home"), {"archived": "1"})
        self.assertContains(archive, 'class="archive-page-heading"', html=False)
        self.assertContains(archive, self.bob.display_name)

    def test_archive_action_keeps_user_in_current_folder_context(self):
        url = reverse("messenger:chat_action", args=[self.chat.pk])
        response = self.client.post(
            url,
            {"action": "archive", "next": reverse("messenger:home")},
        )
        self.assertRedirects(
            response,
            reverse("messenger:home"),
            fetch_redirect_response=False,
        )

        response = self.client.post(
            url,
            {
                "action": "archive",
                "next": f"{reverse('messenger:home')}?archived=1",
            },
        )
        self.assertRedirects(
            response,
            f"{reverse('messenger:home')}?archived=1",
            fetch_redirect_response=False,
        )

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
        SOVIETGRAM_RATE_LIMITS={
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
        SOVIETGRAM_RATE_LIMITS={
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
        SOVIETGRAM_RATE_LIMITS={
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
            SOVIETGRAM_RATE_LIMITS={
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


    def test_collective_profile_overlay_and_json_permissions(self):
        group = Chat.objects.create(
            type=Chat.Type.GROUP,
            title="Проектный комитет",
            description="Обсуждаем текущие задачи.",
        )
        ChatParticipant.objects.create(
            chat=group,
            user=self.alice,
            role=ChatParticipant.Role.OWNER,
        )
        ChatParticipant.objects.create(
            chat=group,
            user=self.bob,
            role=ChatParticipant.Role.MEMBER,
        )

        page = self.client.get(reverse("messenger:chat", args=[group.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'id="communityProfile"', html=False)
        self.assertContains(page, "data-community-profile-open", html=False)

        response = self.client.get(
            reverse("messenger:community_profile", args=[group.pk])
        )
        self.assertEqual(response.status_code, 200)
        profile = response.json()["profile"]
        self.assertEqual(profile["title"], "Проектный комитет")
        self.assertEqual(profile["viewer_role"], ChatParticipant.Role.OWNER)
        self.assertTrue(profile["can_manage"])
        self.assertTrue(profile["members_visible"])
        self.assertEqual(profile["member_count"], 2)

        self.client.force_login(self.charlie)
        forbidden = self.client.get(
            reverse("messenger:community_profile", args=[group.pk])
        )
        self.assertEqual(forbidden.status_code, 404)

    def test_collective_profile_update_and_member_role_permissions(self):
        channel = Chat.objects.create(
            type=Chat.Type.CHANNEL,
            title="Старый эфир",
            username="old_air",
            description="Старое описание",
        )
        ChatParticipant.objects.create(
            chat=channel,
            user=self.alice,
            role=ChatParticipant.Role.OWNER,
        )
        ChatParticipant.objects.create(
            chat=channel,
            user=self.bob,
            role=ChatParticipant.Role.MEMBER,
        )

        updated = self.client.post(
            reverse("messenger:community_profile_update", args=[channel.pk]),
            {
                "title": "Новый эфир",
                "description": "Новое описание",
                "visibility": "public",
                "username": "new_air",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(updated.status_code, 200)
        channel.refresh_from_db()
        self.assertEqual(channel.title, "Новый эфир")
        self.assertEqual(channel.username, "new_air")

        promoted = self.client.post(
            reverse("messenger:community_member_action", args=[channel.pk]),
            {
                "action": "role",
                "username": self.bob.username,
                "role": ChatParticipant.Role.ADMIN,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(promoted.status_code, 200)
        self.assertEqual(
            ChatParticipant.objects.get(chat=channel, user=self.bob).role,
            ChatParticipant.Role.ADMIN,
        )

        self.client.force_login(self.bob)
        denied_update = self.client.post(
            reverse("messenger:community_profile_update", args=[channel.pk]),
            {
                "title": "Админское название",
                "description": "Допустимое изменение",
                "visibility": "public",
                "username": "new_air",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(denied_update.status_code, 200)

        denied_role = self.client.post(
            reverse("messenger:community_member_action", args=[channel.pk]),
            {
                "action": "role",
                "username": self.alice.username,
                "role": ChatParticipant.Role.MEMBER,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(denied_role.status_code, 403)

    def test_channel_member_profile_hides_subscriber_list(self):
        channel = Chat.objects.create(
            type=Chat.Type.CHANNEL,
            title="Закрытая подписка",
            username="closed_subs",
        )
        ChatParticipant.objects.create(
            chat=channel,
            user=self.alice,
            role=ChatParticipant.Role.OWNER,
        )
        ChatParticipant.objects.create(
            chat=channel,
            user=self.bob,
            role=ChatParticipant.Role.MEMBER,
        )

        self.client.force_login(self.bob)
        response = self.client.get(
            reverse("messenger:community_profile", args=[channel.pk])
        )
        self.assertEqual(response.status_code, 200)
        profile = response.json()["profile"]
        self.assertFalse(profile["members_visible"])
        self.assertEqual(profile["members"], [])
        self.assertEqual(profile["member_count"], 2)

    def test_collective_profile_leave_rules(self):
        group = Chat.objects.create(
            type=Chat.Type.GROUP,
            title="Группа выхода",
        )
        ChatParticipant.objects.create(
            chat=group,
            user=self.alice,
            role=ChatParticipant.Role.OWNER,
        )
        ChatParticipant.objects.create(
            chat=group,
            user=self.bob,
            role=ChatParticipant.Role.MEMBER,
        )

        owner_leave = self.client.post(
            reverse("messenger:community_profile_action", args=[group.pk]),
            {"action": "leave"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(owner_leave.status_code, 403)
        self.assertTrue(
            ChatParticipant.objects.filter(chat=group, user=self.alice).exists()
        )

        self.client.force_login(self.bob)
        member_leave = self.client.post(
            reverse("messenger:community_profile_action", args=[group.pk]),
            {"action": "leave"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(member_leave.status_code, 200)
        self.assertTrue(member_leave.json()["left"])
        self.assertFalse(
            ChatParticipant.objects.filter(chat=group, user=self.bob).exists()
        )


    def test_group_and_channel_management_controls_render_for_admins(self):
        group = Chat.objects.create(type=Chat.Type.GROUP, title="Управляемая группа")
        ChatParticipant.objects.create(
            chat=group,
            user=self.alice,
            role=ChatParticipant.Role.OWNER,
        )
        ChatParticipant.objects.create(
            chat=group,
            user=self.bob,
            role=ChatParticipant.Role.MEMBER,
        )

        owner_page = self.client.get(reverse("messenger:chat", args=[group.pk]))
        self.assertContains(owner_page, 'id="communityProfileSettingsOpen"', html=False)
        self.assertContains(owner_page, 'id="communitySettingsPermissionsForm"', html=False)
        self.assertContains(owner_page, "Ссылки-приглашения")
        self.assertContains(owner_page, "Недавние действия")

        self.client.force_login(self.bob)
        member_page = self.client.get(reverse("messenger:chat", args=[group.pk]))
        self.assertNotContains(member_page, 'id="communityProfileSettingsOpen"', html=False)
        denied = self.client.get(reverse("messenger:community_settings", args=[group.pk]))
        self.assertEqual(denied.status_code, 403)

    def test_group_settings_permissions_are_enforced(self):
        group = Chat.objects.create(type=Chat.Type.GROUP, title="Группа с правилами")
        ChatParticipant.objects.create(
            chat=group,
            user=self.alice,
            role=ChatParticipant.Role.OWNER,
        )
        ChatParticipant.objects.create(
            chat=group,
            user=self.bob,
            role=ChatParticipant.Role.MEMBER,
        )

        response = self.client.post(
            reverse("messenger:community_settings", args=[group.pk]),
            {
                "section": "permissions",
                "send_messages": "1",
                "add_members": "1",
                "pin_messages": "1",
                "history_visible": "1",
                "slow_mode_seconds": "30",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        group.refresh_from_db()
        self.assertTrue(group.members_can_send_messages)
        self.assertFalse(group.members_can_send_media)
        self.assertFalse(group.members_can_send_links)
        self.assertTrue(group.members_can_add_members)
        self.assertTrue(group.members_can_pin_messages)
        self.assertEqual(group.slow_mode_seconds, 30)

        self.client.force_login(self.bob)
        linked = self.client.post(
            reverse("messenger:send_message", args=[group.pk]),
            {"text": "https://example.com"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(linked.status_code, 403)

        media = SimpleUploadedFile(
            "rules.pdf",
            b"pdf",
            content_type="application/pdf",
        )
        blocked_media = self.client.post(
            reverse("messenger:send_message", args=[group.pk]),
            {
                "text": "",
                "attachment_mode": "file",
                "attachments": media,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(blocked_media.status_code, 403)

        first = self.client.post(
            reverse("messenger:send_message", args=[group.pk]),
            {"text": "Первое разрешённое"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(first.status_code, 200)
        first_message = Message.objects.get(chat=group, text="Первое разрешённое")

        pinned = self.client.post(
            reverse("messenger:pin_message", args=[group.pk, first_message.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(pinned.status_code, 200)
        self.assertTrue(pinned.json()["pinned"])

        slowed = self.client.post(
            reverse("messenger:send_message", args=[group.pk]),
            {"text": "Слишком быстро"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(slowed.status_code, 403)
        self.assertIn("Retry-After", slowed)

        candidate = self.client.get(
            reverse("messenger:community_member_candidates", args=[group.pk]),
            {"q": "charlie"},
        )
        self.assertEqual(candidate.status_code, 200)
        added = self.client.post(
            reverse("messenger:community_member_action", args=[group.pk]),
            {"action": "add", "username": self.charlie.username},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(added.status_code, 200)
        self.assertTrue(
            ChatParticipant.objects.filter(chat=group, user=self.charlie).exists()
        )

    def test_hidden_history_only_applies_to_members_joining_after_setting_change(self):
        group = Chat.objects.create(type=Chat.Type.GROUP, title="История группы")
        ChatParticipant.objects.create(
            chat=group,
            user=self.alice,
            role=ChatParticipant.Role.OWNER,
        )
        existing = ChatParticipant.objects.create(
            chat=group,
            user=self.bob,
            role=ChatParticipant.Role.MEMBER,
        )
        old_message = Message.objects.create(
            chat=group,
            sender=self.alice,
            text="Старое сообщение",
        )

        settings_response = self.client.post(
            reverse("messenger:community_settings", args=[group.pk]),
            {
                "section": "permissions",
                "send_messages": "1",
                "send_media": "1",
                "send_links": "1",
                "slow_mode_seconds": "0",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(settings_response.status_code, 200)
        group.refresh_from_db()
        self.assertFalse(group.history_visible_to_new_members)

        existing.refresh_from_db()
        self.assertTrue(existing.can_see_pre_join_history)

        self.client.force_login(self.bob)
        existing_page = self.client.get(reverse("messenger:chat", args=[group.pk]))
        self.assertContains(existing_page, old_message.text)

        self.client.force_login(self.alice)
        added = self.client.post(
            reverse("messenger:community_member_action", args=[group.pk]),
            {"action": "add", "username": self.charlie.username},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(added.status_code, 200)
        new_membership = ChatParticipant.objects.get(chat=group, user=self.charlie)
        self.assertFalse(new_membership.can_see_pre_join_history)

        self.client.force_login(self.charlie)
        new_page = self.client.get(reverse("messenger:chat", args=[group.pk]))
        self.assertNotContains(new_page, old_message.text)

        self.client.force_login(self.alice)
        new_message = Message.objects.create(
            chat=group,
            sender=self.alice,
            text="Новое сообщение",
        )
        self.client.force_login(self.charlie)
        refreshed = self.client.get(reverse("messenger:chat", args=[group.pk]))
        self.assertContains(refreshed, new_message.text)

    def test_channel_signatures_setting_renders_author_name(self):
        channel = Chat.objects.create(
            type=Chat.Type.CHANNEL,
            title="Подписанный эфир",
            username="signed_air",
        )
        ChatParticipant.objects.create(
            chat=channel,
            user=self.alice,
            role=ChatParticipant.Role.OWNER,
        )
        unsigned = Message.objects.create(
            chat=channel,
            sender=self.alice,
            text="Старая публикация",
        )

        changed = self.client.post(
            reverse("messenger:community_settings", args=[channel.pk]),
            {"section": "signatures", "enabled": "1"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(changed.status_code, 200)
        channel.refresh_from_db()
        self.assertTrue(channel.signatures_enabled)

        sent = self.client.post(
            reverse("messenger:send_message", args=[channel.pk]),
            {"text": "Подписанная публикация"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(sent.status_code, 200)
        signed = Message.objects.get(chat=channel, text="Подписанная публикация")
        self.assertEqual(signed.signature_name, self.alice.display_name)
        unsigned.refresh_from_db()
        self.assertEqual(unsigned.signature_name, "")

        page = self.client.get(reverse("messenger:chat", args=[channel.pk]))
        self.assertContains(page, "message-channel-signature")
        self.assertContains(page, self.alice.display_name)

    def test_invite_links_join_limits_and_recent_actions(self):
        group = Chat.objects.create(type=Chat.Type.GROUP, title="Группа по ссылке")
        ChatParticipant.objects.create(
            chat=group,
            user=self.alice,
            role=ChatParticipant.Role.OWNER,
        )

        created = self.client.post(
            reverse("messenger:community_invite_action", args=[group.pk]),
            {
                "action": "create",
                "name": "Одноразовая",
                "expires_hours": "24",
                "usage_limit": "1",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(created.status_code, 200)
        invite = ChatInviteLink.objects.get(chat=group)
        self.assertTrue(invite.is_active)

        self.client.force_login(self.charlie)
        joined = self.client.get(
            reverse("messenger:join_invite", args=[invite.token])
        )
        self.assertRedirects(
            joined,
            reverse("messenger:chat", args=[group.pk]),
            fetch_redirect_response=False,
        )
        self.assertTrue(
            ChatParticipant.objects.filter(chat=group, user=self.charlie).exists()
        )
        invite.refresh_from_db()
        self.assertEqual(invite.usage_count, 1)
        self.assertFalse(invite.is_active)

        self.client.force_login(self.alice)
        settings_payload = self.client.get(
            reverse("messenger:community_settings", args=[group.pk])
        ).json()["settings"]
        self.assertTrue(settings_payload["recent_actions"])
        self.assertTrue(
            ChatAdminLog.objects.filter(chat=group, action="join_invite").exists()
        )

    def test_group_can_be_made_public_and_found_in_community_search(self):
        group = Chat.objects.create(type=Chat.Type.GROUP, title="Открытая группа")
        ChatParticipant.objects.create(
            chat=group,
            user=self.alice,
            role=ChatParticipant.Role.OWNER,
        )

        changed = self.client.post(
            reverse("messenger:community_settings", args=[group.pk]),
            {
                "section": "type",
                "visibility": "public",
                "username": "open_group",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(changed.status_code, 200)
        group.refresh_from_db()
        self.assertEqual(group.username, "open_group")

        self.client.force_login(self.bob)
        search = self.client.get(
            reverse("messenger:contacts"),
            {"q": "open_group"},
        )
        self.assertContains(search, "Открытая группа")
        self.assertContains(search, "Вступить")

    def test_only_owner_can_delete_collective(self):
        group = Chat.objects.create(type=Chat.Type.GROUP, title="Удаляемая группа")
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

        self.client.force_login(self.bob)
        denied = self.client.post(
            reverse("messenger:community_profile_action", args=[group.pk]),
            {"action": "delete"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(denied.status_code, 403)
        self.assertTrue(Chat.objects.filter(pk=group.pk).exists())

        self.client.force_login(self.alice)
        deleted = self.client.post(
            reverse("messenger:community_profile_action", args=[group.pk]),
            {"action": "delete"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(deleted.json()["deleted"])
        self.assertFalse(Chat.objects.filter(pk=group.pk).exists())


    def test_global_search_covers_chats_people_communities_and_messages(self):
        Message.objects.create(
            chat=self.chat,
            sender=self.bob,
            text="Секретная телеметрия спутника",
        )
        public_group = Chat.objects.create(
            type=Chat.Type.GROUP,
            title="Спутниковый кружок",
            username="sputnik_club",
        )
        ChatParticipant.objects.create(
            chat=public_group,
            user=self.charlie,
            role=ChatParticipant.Role.OWNER,
        )

        people_response = self.client.get(
            reverse("messenger:global_search"),
            {"q": "bob"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(people_response.status_code, 200)
        people_payload = people_response.json()
        self.assertTrue(
            any(item["username"] == self.bob.username for item in people_payload["people"])
        )
        self.assertTrue(
            any(item["id"] == self.chat.pk for item in people_payload["chats"])
        )

        community_response = self.client.get(
            reverse("messenger:global_search"),
            {"q": "sputnik"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(community_response.status_code, 200)
        self.assertTrue(
            any(
                item["id"] == public_group.pk
                for item in community_response.json()["communities"]
            )
        )

        message_response = self.client.get(
            reverse("messenger:global_search"),
            {"q": "телеметрия"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(message_response.status_code, 200)
        self.assertTrue(
            any(
                item["preview"] == "Секретная телеметрия спутника"
                for item in message_response.json()["messages"]
            )
        )

    def test_chat_header_menu_and_global_search_are_available_for_collectives(self):
        group = Chat.objects.create(type=Chat.Type.GROUP, title="Меню группы")
        ChatParticipant.objects.create(
            chat=group,
            user=self.alice,
            role=ChatParticipant.Role.OWNER,
        )
        response = self.client.get(reverse("messenger:chat", args=[group.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="chatMenuButton"', html=False)
        self.assertContains(response, 'data-open-chat-search', html=False)
        self.assertContains(response, 'data-open-community-settings', html=False)
        self.assertContains(response, 'id="sidebarGlobalSearch"', html=False)
        self.assertContains(response, 'data-global-search-url=', html=False)
        self.assertContains(response, "js/chat-controls.js", html=False)
        self.assertNotContains(response, "js/messenger.js", html=False)

    def test_member_can_leave_collective_from_chat_menu_action(self):
        group = Chat.objects.create(type=Chat.Type.GROUP, title="Выход из меню")
        ChatParticipant.objects.create(
            chat=group,
            user=self.alice,
            role=ChatParticipant.Role.OWNER,
        )
        ChatParticipant.objects.create(
            chat=group,
            user=self.bob,
            role=ChatParticipant.Role.MEMBER,
        )

        self.client.force_login(self.bob)
        response = self.client.post(
            reverse("messenger:chat_action", args=[group.pk]),
            {"action": "leave"},
        )
        self.assertRedirects(
            response,
            reverse("messenger:home"),
            fetch_redirect_response=False,
        )
        self.assertFalse(
            ChatParticipant.objects.filter(chat=group, user=self.bob).exists()
        )


    def test_private_chat_clear_for_me_preserves_peer_history(self):
        old_message = Message.objects.create(
            chat=self.chat,
            sender=self.bob,
            text="История для одного",
        )
        response = self.client.post(
            reverse("messenger:chat_action", args=[self.chat.pk]),
            {"action": "clear", "scope": "me"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        membership = ChatParticipant.objects.get(
            chat=self.chat,
            user=self.alice,
        )
        self.assertGreaterEqual(
            membership.cleared_before_message_id,
            old_message.pk,
        )
        alice_page = self.client.get(
            reverse("messenger:chat", args=[self.chat.pk])
        )
        self.assertNotContains(alice_page, "История для одного")

        self.client.force_login(self.bob)
        bob_page = self.client.get(
            reverse("messenger:chat", args=[self.chat.pk])
        )
        self.assertContains(bob_page, "История для одного")

    def test_private_chat_delete_for_me_hides_chat_until_new_message(self):
        Message.objects.create(
            chat=self.chat,
            sender=self.bob,
            text="Перед удалением",
        )
        response = self.client.post(
            reverse("messenger:chat_action", args=[self.chat.pk]),
            {"action": "delete_chat", "scope": "me"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        membership = ChatParticipant.objects.get(
            chat=self.chat,
            user=self.alice,
        )
        self.assertTrue(membership.is_hidden)

        home = self.client.get(reverse("messenger:home"))
        self.assertNotContains(
            home,
            reverse("messenger:chat", args=[self.chat.pk]),
        )

        self.client.force_login(self.bob)
        sent = self.client.post(
            reverse("messenger:send_message", args=[self.chat.pk]),
            {"text": "Возвращаем чат"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(sent.status_code, 200)

        membership.refresh_from_db()
        self.assertFalse(membership.is_hidden)

        self.client.force_login(self.alice)
        reopened = self.client.get(
            reverse("messenger:chat", args=[self.chat.pk])
        )
        self.assertContains(reopened, "Возвращаем чат")
        self.assertNotContains(reopened, "Перед удалением")

    def test_private_chat_delete_for_everyone_hides_both_sides(self):
        message = Message.objects.create(
            chat=self.chat,
            sender=self.bob,
            text="Удалить чат у обоих",
        )
        response = self.client.post(
            reverse("messenger:chat_action", args=[self.chat.pk]),
            {"action": "delete_chat", "scope": "everyone"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        message.refresh_from_db()
        self.assertTrue(message.is_deleted)
        self.assertEqual(
            ChatParticipant.objects.filter(
                chat=self.chat,
                is_hidden=True,
            ).count(),
            2,
        )

    def test_group_admin_can_delete_any_message_for_everyone(self):
        group = Chat.objects.create(
            type=Chat.Type.GROUP,
            title="Админское удаление",
        )
        ChatParticipant.objects.create(
            chat=group,
            user=self.alice,
            role=ChatParticipant.Role.ADMIN,
        )
        ChatParticipant.objects.create(
            chat=group,
            user=self.bob,
            role=ChatParticipant.Role.MEMBER,
        )
        message = Message.objects.create(
            chat=group,
            sender=self.bob,
            text="Сообщение участника",
        )
        response = self.client.post(
            reverse("messenger:delete_message", args=[group.pk, message.pk]),
            {"scope": "everyone"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        message.refresh_from_db()
        self.assertTrue(message.is_deleted)

    def test_group_member_cannot_delete_someone_elses_message(self):
        group = Chat.objects.create(
            type=Chat.Type.GROUP,
            title="Обычный участник",
        )
        ChatParticipant.objects.create(
            chat=group,
            user=self.alice,
            role=ChatParticipant.Role.MEMBER,
        )
        ChatParticipant.objects.create(
            chat=group,
            user=self.bob,
            role=ChatParticipant.Role.MEMBER,
        )
        message = Message.objects.create(
            chat=group,
            sender=self.bob,
            text="Чужое групповое сообщение",
        )
        response = self.client.post(
            reverse("messenger:delete_message", args=[group.pk, message.pk]),
            {"scope": "everyone"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 403)
        message.refresh_from_db()
        self.assertFalse(message.is_deleted)

    def test_chat_menu_contains_telegram_style_selection_and_delete_actions(self):
        response = self.client.get(
            reverse("messenger:chat", args=[self.chat.pk])
        )
        self.assertContains(response, "data-select-messages", html=False)
        self.assertContains(response, "data-clear-chat-history", html=False)
        self.assertContains(response, "data-delete-chat", html=False)
        self.assertContains(response, 'id="deleteMessageModal"', html=False)
        self.assertContains(response, 'id="deleteChatModal"', html=False)
        self.assertContains(response, 'id="messageSelectionBar"', html=False)


    def test_attachment_menu_matches_telegram_builtins_without_wallet(self):
        response = self.client.get(
            reverse("messenger:chat", args=[self.chat.pk])
        )
        self.assertEqual(response.status_code, 200)
        for label in (
            "Фото или видео",
            "Файл",
            "Опрос",
            "Список задач",
            "Статья",
            "Геопозиция",
            "Музыка",
        ):
            self.assertContains(response, label)
        self.assertNotContains(response, "Кошелёк")
        self.assertContains(response, 'id="attachSpecialBackdrop"', html=False)
        self.assertContains(response, "js/attachment-files.js", html=False)
        self.assertContains(response, "js/attachment-special.js", html=False)
        self.assertContains(response, "js/article-editor.js", html=False)
        self.assertContains(response, 'id="attachArticleToolbar"', html=False)
        self.assertContains(response, 'data-article-command="bold"', html=False)
        self.assertContains(response, 'data-article-command="subscript"', html=False)
        self.assertContains(response, 'data-article-command="details"', html=False)
        self.assertContains(response, 'data-article-command="table"', html=False)
        self.assertContains(response, 'data-article-command="location"', html=False)
        self.assertContains(response, 'id="articleViewerBackdrop"', html=False)

    def test_special_poll_can_be_created_and_voted(self):
        create = self.client.post(
            reverse("messenger:send_special_message", args=[self.chat.pk]),
            {
                "special_type": "poll",
                "payload": json.dumps(
                    {
                        "question": "Какой вариант?",
                        "options": ["Первый", "Второй", "Третий"],
                        "anonymous": True,
                        "multiple": False,
                        "quiz": False,
                    },
                    ensure_ascii=False,
                ),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(create.status_code, 200)
        message = Message.objects.get(
            chat=self.chat,
            special_type=Message.SpecialType.POLL,
        )
        self.assertEqual(message.special_data["question"], "Какой вариант?")
        self.assertEqual(len(message.special_data["options"]), 3)

        self.client.force_login(self.bob)
        vote = self.client.post(
            reverse(
                "messenger:special_message_action",
                args=[self.chat.pk, message.pk],
            ),
            {
                "action": "vote",
                "options": json.dumps([1]),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(vote.status_code, 200)
        special = vote.json()["message"]["special"]
        self.assertEqual(special["type"], "poll")
        self.assertEqual(special["selected_indexes"], [1])
        self.assertEqual(special["total_voters"], 1)
        self.assertEqual(special["options"][1]["votes"], 1)
        self.assertTrue(special["options"][1]["selected"])

    def test_quiz_requires_correct_answer_and_reveals_it_after_vote(self):
        create = self.client.post(
            reverse("messenger:send_special_message", args=[self.chat.pk]),
            {
                "special_type": "poll",
                "payload": json.dumps(
                    {
                        "question": "2 + 2?",
                        "options": ["3", "4"],
                        "quiz": True,
                        "correct_option": 1,
                        "explanation": "Два плюс два — четыре.",
                    },
                    ensure_ascii=False,
                ),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(create.status_code, 200)
        message_id = create.json()["message"]["id"]

        self.client.force_login(self.bob)
        vote = self.client.post(
            reverse(
                "messenger:special_message_action",
                args=[self.chat.pk, message_id],
            ),
            {
                "action": "vote",
                "options": json.dumps([0]),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(vote.status_code, 200)
        special = vote.json()["message"]["special"]
        self.assertTrue(special["quiz"])
        self.assertTrue(special["options"][1]["correct"])
        self.assertEqual(special["explanation"], "Два плюс два — четыре.")

    def test_todo_list_allows_collaborative_toggle_and_add(self):
        create = self.client.post(
            reverse("messenger:send_special_message", args=[self.chat.pk]),
            {
                "special_type": "todo",
                "payload": json.dumps(
                    {
                        "title": "Релиз",
                        "tasks": ["Собрать", "Проверить"],
                        "allow_others_add": True,
                        "allow_others_mark": True,
                    },
                    ensure_ascii=False,
                ),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(create.status_code, 200)
        message_id = create.json()["message"]["id"]

        self.client.force_login(self.bob)
        toggled = self.client.post(
            reverse(
                "messenger:special_message_action",
                args=[self.chat.pk, message_id],
            ),
            {"action": "toggle", "index": "0"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(toggled.status_code, 200)
        self.assertTrue(
            toggled.json()["message"]["special"]["tasks"][0]["done"]
        )

        added = self.client.post(
            reverse(
                "messenger:special_message_action",
                args=[self.chat.pk, message_id],
            ),
            {"action": "add", "text": "Опубликовать"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(added.status_code, 200)
        self.assertEqual(
            added.json()["message"]["special"]["tasks"][-1]["text"],
            "Опубликовать",
        )

    def test_article_and_location_special_messages_are_serialized(self):
        article = self.client.post(
            reverse("messenger:send_special_message", args=[self.chat.pk]),
            {
                "special_type": "article",
                "payload": json.dumps(
                    {
                        "title": "Отчёт",
                        "body": "Первая строка\nВторая строка",
                    },
                    ensure_ascii=False,
                ),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(article.status_code, 200)
        self.assertEqual(article.json()["message"]["special"]["type"], "article")
        self.assertEqual(
            article.json()["message"]["special"]["title"],
            "Отчёт",
        )

        location = self.client.post(
            reverse("messenger:send_special_message", args=[self.chat.pk]),
            {
                "special_type": "location",
                "payload": json.dumps(
                    {
                        "label": "Точка",
                        "latitude": 54.687157,
                        "longitude": 25.279652,
                    },
                    ensure_ascii=False,
                ),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(location.status_code, 200)
        special = location.json()["message"]["special"]
        self.assertEqual(special["type"], "location")
        self.assertEqual(special["label"], "Точка")
        self.assertEqual(special["latitude"], 54.687157)
        self.assertEqual(special["longitude"], 25.279652)

    def test_music_attachment_is_sent_as_playable_audio(self):
        audio = SimpleUploadedFile(
            "track.mp3",
            b"ID3" + (b"\0" * 64),
            content_type="audio/mpeg",
        )
        response = self.client.post(
            reverse("messenger:send_message", args=[self.chat.pk]),
            {
                "text": "",
                "attachment_mode": "audio",
                "attachments": audio,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        attachment = MessageAttachment.objects.get(
            message_id=response.json()["message"]["id"]
        )
        self.assertEqual(attachment.kind, MessageAttachment.Kind.AUDIO)
        self.assertEqual(
            response.json()["message"]["attachments"][0]["kind"],
            "audio",
        )


    def test_photo_video_mode_accepts_valid_image_and_serializes_inline_media(self):
        image_buffer = BytesIO()
        Image.new("RGB", (2, 2), "white").save(image_buffer, format="PNG")
        upload = SimpleUploadedFile(
            "photo.png",
            image_buffer.getvalue(),
            content_type="image/png",
        )
        response = self.client.post(
            reverse("messenger:send_message", args=[self.chat.pk]),
            {
                "attachment_mode": "media",
                "attachments": upload,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        attachment = MessageAttachment.objects.get(
            message_id=response.json()["message"]["id"]
        )
        self.assertEqual(attachment.kind, MessageAttachment.Kind.IMAGE)
        serialized = response.json()["message"]["attachments"][0]
        self.assertEqual(serialized["kind"], "image")
        self.assertEqual(
            self.client.get(
                reverse("messenger:view_attachment", args=[attachment.pk])
            ).status_code,
            200,
        )

    def test_document_mode_accepts_arbitrary_file_and_keeps_download_semantics(self):
        upload = SimpleUploadedFile(
            "report.pdf",
            b"%PDF-1.4\nsovietgram-test\n%%EOF",
            content_type="application/pdf",
        )
        response = self.client.post(
            reverse("messenger:send_message", args=[self.chat.pk]),
            {
                "attachment_mode": "file",
                "attachments": upload,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        attachment = MessageAttachment.objects.get(
            message_id=response.json()["message"]["id"]
        )
        self.assertEqual(attachment.kind, MessageAttachment.Kind.FILE)
        serialized = response.json()["message"]["attachments"][0]
        self.assertEqual(serialized["kind"], "file")
        self.assertIn(
            reverse("messenger:download_attachment", args=[attachment.pk]),
            serialized["url"],
        )

    def test_music_mode_uses_inline_audio_endpoint(self):
        upload = SimpleUploadedFile(
            "song.ogg",
            b"OggS" + (b"\0" * 96),
            content_type="audio/ogg",
        )
        response = self.client.post(
            reverse("messenger:send_message", args=[self.chat.pk]),
            {
                "attachment_mode": "audio",
                "attachments": upload,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        attachment = MessageAttachment.objects.get(
            message_id=response.json()["message"]["id"]
        )
        self.assertEqual(attachment.kind, MessageAttachment.Kind.AUDIO)
        serialized = response.json()["message"]["attachments"][0]
        self.assertEqual(serialized["kind"], "audio")
        inline = self.client.get(
            reverse("messenger:view_attachment", args=[attachment.pk])
        )
        self.assertEqual(inline.status_code, 200)
        self.assertTrue(
            inline["Content-Type"].startswith("audio/"),
            inline["Content-Type"],
        )

    def test_article_supports_rich_payload_and_author_editing(self):
        create = self.client.post(
            reverse("messenger:send_special_message", args=[self.chat.pk]),
            {
                "special_type": "article",
                "payload": json.dumps(
                    {
                        "title": "Большая статья",
                        "subtitle": "Подзаголовок",
                        "body": (
                            "# Заголовок\n\n"
                            "**Жирный** и *курсив*.\n\n"
                            "> Цитата\n\n"
                            "- пункт\n"
                            "- [ ] задача\n\n"
                            "| A | B |\n"
                            "| --- | --- |\n"
                            "| 1 | 2 |"
                        ),
                    },
                    ensure_ascii=False,
                ),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(create.status_code, 200)
        special = create.json()["message"]["special"]
        self.assertEqual(special["type"], "article")
        self.assertEqual(special["title"], "Большая статья")
        self.assertEqual(special["subtitle"], "Подзаголовок")
        self.assertTrue(special["can_edit"])
        self.assertEqual(special["format"], "sovietgram-markdown-v1")
        self.assertTrue(special["action_url"])

        message = Message.objects.get(pk=create.json()["message"]["id"])
        edit = self.client.post(
            reverse(
                "messenger:special_message_action",
                args=[self.chat.pk, message.pk],
            ),
            {
                "action": "edit",
                "payload": json.dumps(
                    {
                        "title": "Обновлённая статья",
                        "subtitle": "Новый подзаголовок",
                        "body": "## После редактирования\n\nНовый текст.",
                    },
                    ensure_ascii=False,
                ),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(edit.status_code, 200)
        updated = edit.json()["message"]["special"]
        self.assertEqual(updated["title"], "Обновлённая статья")
        self.assertEqual(updated["subtitle"], "Новый подзаголовок")
        message.refresh_from_db()
        self.assertIsNotNone(message.edited_at)
        self.assertEqual(
            message.special_data["format"],
            "sovietgram-markdown-v1",
        )

    def test_other_private_participant_cannot_edit_article(self):
        create = self.client.post(
            reverse("messenger:send_special_message", args=[self.chat.pk]),
            {
                "special_type": "article",
                "payload": json.dumps(
                    {
                        "title": "Авторская статья",
                        "body": "Текст.",
                    },
                    ensure_ascii=False,
                ),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(create.status_code, 200)
        message_id = create.json()["message"]["id"]

        self.client.force_login(self.bob)
        edit = self.client.post(
            reverse(
                "messenger:special_message_action",
                args=[self.chat.pk, message_id],
            ),
            {
                "action": "edit",
                "payload": json.dumps(
                    {
                        "title": "Чужая правка",
                        "body": "Не должно сохраниться.",
                    },
                    ensure_ascii=False,
                ),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(edit.status_code, 403)
        message = Message.objects.get(pk=message_id)
        self.assertEqual(message.special_data["title"], "Авторская статья")
