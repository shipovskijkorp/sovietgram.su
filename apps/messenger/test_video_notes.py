from tempfile import TemporaryDirectory
from uuid import uuid4

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.privacy import set_privacy_rule
from .models import Chat, ChatParticipant, Message, MessageAttachment, VoiceMessagePlayback
from .services import get_or_create_direct_chat


# Minimal container-signature fixtures exercise the upload contract, not codecs.
WEBM = bytes.fromhex("1a45dfa3") + b"test video payload"
MP4 = bytes.fromhex("00000018") + b"ftypisom" + b"test video payload"


class VideoNoteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("notealice", "notealice@example.net", "Password-1945!")
        cls.bob = User.objects.create_user("notebob", "notebob@example.net", "Password-1945!")
        cls.other = User.objects.create_user("noteother", "noteother@example.net", "Password-1945!")
        cls.chat = get_or_create_direct_chat(cls.alice, cls.bob)

    def setUp(self):
        cache.clear()
        work = TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.enterContext(override_settings(MEDIA_ROOT=work.name))
        self.client.force_login(self.alice)

    def send(self, chat=None, *, content=WEBM, name="note.webm", mime="video/webm", **extra):
        data = {"account_id":self.alice.pk, "attachment_mode":"video_note",
                "video_note_duration_ms":"1500", "client_message_id":str(uuid4()), **extra}
        data["attachments"] = SimpleUploadedFile(name, content, content_type=mime)
        return self.client.post(reverse("messenger:send_message", args=[(chat or self.chat).pk]),
                                data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_send_reply_retry_stream_and_playback(self):
        reply = Message.objects.create(chat=self.chat, sender=self.bob, text="Reply target")
        key = str(uuid4())
        for _ in range(2):
            response = self.send(client_message_id=key, reply_to=reply.pk)
            self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["replayed"])
        item = response.json()["message"]["attachments"][0]
        attachment = MessageAttachment.objects.get(pk=item["id"])
        self.assertEqual(attachment.kind, "video_note")
        self.assertEqual(attachment.duration_ms, 1500)
        self.assertEqual(attachment.message.reply_to_id, reply.pk)
        self.assertEqual(attachment.message.preview, "Видеокружок")
        self.assertEqual(item["kind"], "video_note")
        self.assertTrue(item["mark_played_url"])
        self.assertEqual(MessageAttachment.objects.count(), 1)
        self.client.force_login(self.bob)
        page = self.client.get(reverse("messenger:chat", args=[self.chat.pk]))
        self.assertContains(page, 'data-video-note-player')
        self.assertContains(page, 'data-note-id="%d"' % attachment.pk)
        self.assertContains(page, 'data-listened="false"')
        response = self.client.get(item["url"], HTTP_RANGE="bytes=0-3")
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response["Content-Type"], "video/webm")
        self.assertEqual(b"".join(response.streaming_content), WEBM[:4])
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(self.client.post(item["mark_played_url"], {"account_id":self.bob.pk}).status_code, 200)
        self.assertTrue(VoiceMessagePlayback.objects.filter(user=self.bob, attachment=attachment).exists())
        self.assertContains(self.client.get(reverse("messenger:chat", args=[self.chat.pk])), 'data-listened="true"')
        outsider = Client()
        outsider.force_login(self.other)
        self.assertEqual(outsider.get(item["url"]).status_code, 404)
        self.assertEqual(outsider.post(item["mark_played_url"]).status_code, 404)

    def test_mp4_and_validation(self):
        self.assertEqual(self.send(content=MP4, name="note.mp4", mime="video/mp4").status_code, 200)
        for kwargs in ({"video_note_duration_ms":"60001"},{"video_note_duration_ms":"0"},
                       {"video_note_duration_ms":""},{"text":"caption"},
                       {"content":b"not video"},{"mime":"image/png"},
                       {"name":"note.html","mime":"text/html"}):
            self.assertEqual(self.send(**kwargs).status_code, 400, kwargs)
        self.assertEqual(MessageAttachment.objects.count(), 1)

    def test_private_and_group_permissions(self):
        set_privacy_rule(self.bob, "voice_messages", "nobody")
        self.assertEqual(self.send().status_code, 403)
        self.assertNotContains(self.client.get(reverse("messenger:chat", args=[self.chat.pk])),
                               'class="composer-tool-button video-note-composer-button"')
        group = Chat.objects.create(type=Chat.Type.GROUP, title="Video only", members_allowed_media=["video"])
        ChatParticipant.objects.create(chat=group, user=self.alice)
        ChatParticipant.objects.create(chat=group, user=self.bob, role="owner")
        result = self.send(group)
        self.assertEqual(result.status_code, 200, result.content)
        note = result.json()["message"]["id"]
        # Video permission is independent of permission to send audio recordings.
        Chat.objects.filter(pk=group.pk).update(members_allowed_media=["voice"])
        self.assertEqual(self.send(group).status_code, 403)
        response = self.client.post(reverse("messenger:forward_message", args=[group.pk,note]),
            {"target_chat_id":self.chat.pk}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Message.objects.filter(chat=self.chat).exists())

    def test_video_note_in_gallery_search_and_protected_chat(self):
        response = self.send()
        self.assertEqual(response.status_code, 200, response.content)
        attachment = response.json()["message"]["attachments"][0]
        gallery = self.client.get(reverse("messenger:chat_gallery", args=[self.chat.pk]), {"kind":"media"}).json()
        self.assertEqual(gallery["counts"]["media"], 1)
        self.assertEqual(gallery["items"][0]["kind"], "video_note")
        search = self.client.get(reverse("messenger:search_messages", args=[self.chat.pk]), {"kind":"video_note"})
        self.assertEqual(search.status_code, 200)
        self.assertEqual(len(search.json()["results"]), 1)
        Chat.objects.filter(pk=self.chat.pk).update(protect_content=True)
        self.assertEqual(self.client.get(reverse("messenger:download_attachment", args=[attachment["id"]])).status_code, 403)
