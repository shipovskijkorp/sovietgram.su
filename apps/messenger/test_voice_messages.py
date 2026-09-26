import json
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.privacy import set_privacy_rule

from .models import Message, MessageAttachment, VoiceMessagePlayback
from .services import get_or_create_direct_chat


class VoiceMessageTests(TestCase):
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
            username="voice_alice",
            email="voice-alice@example.com",
            password=self.password,
        )
        self.bob = User.objects.create_user(
            username="voice_bob",
            email="voice-bob@example.com",
            password=self.password,
        )
        self.chat = get_or_create_direct_chat(self.alice, self.bob)
        self.client.force_login(self.alice)

    def _voice_upload(self, content=b"recorded-opus-data"):
        return SimpleUploadedFile(
            "voice.webm",
            content,
            content_type="audio/webm;codecs=opus",
        )

    def _send_voice(self, duration=1450, waveform=None):
        if waveform is None:
            waveform = [8, 16, 44, 82, 100, 56, 23]
        return self.client.post(
            reverse("messenger:send_message", args=[self.chat.pk]),
            {
                "attachment_mode": "voice",
                "voice_duration_ms": str(duration),
                "voice_waveform": json.dumps(waveform),
                "attachments": self._voice_upload(),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

    def test_voice_message_saves_recording_metadata(self):
        response = self._send_voice()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

        attachment = MessageAttachment.objects.get()
        self.assertEqual(attachment.kind, MessageAttachment.Kind.VOICE)
        self.assertEqual(attachment.duration_ms, 1450)
        self.assertEqual(attachment.waveform, [8, 16, 44, 82, 100, 56, 23])

        serialized = response.json()["message"]["attachments"][0]
        self.assertEqual(serialized["kind"], "voice")
        self.assertEqual(serialized["duration_ms"], 1450)
        self.assertEqual(serialized["waveform"], [8, 16, 44, 82, 100, 56, 23])
        self.assertTrue(serialized["listened"])
        self.assertTrue(serialized["mark_played_url"])

    def test_voice_message_must_be_at_least_point_two_seconds(self):
        response = self._send_voice(duration=120)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Message.objects.exists())

    def test_voice_privacy_blocks_direct_voice_recordings(self):
        set_privacy_rule(self.bob, "voice_messages", "nobody")
        response = self._send_voice()
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Message.objects.exists())

    def test_voice_playback_is_marked_per_user(self):
        response = self._send_voice()
        attachment = MessageAttachment.objects.get()
        self.client.force_login(self.bob)

        played = self.client.post(
            reverse("messenger:mark_voice_played", args=[attachment.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(played.status_code, 200)
        self.assertTrue(played.json()["listened"])
        self.assertTrue(
            VoiceMessagePlayback.objects.filter(
                attachment=attachment,
                user=self.bob,
            ).exists()
        )

        poll = self.client.get(
            reverse("messenger:poll_messages", args=[self.chat.pk]),
            {"after": 0},
        )
        voice = poll.json()["messages"][0]["attachments"][0]
        self.assertTrue(voice["listened"])

    def test_voice_attachment_supports_byte_ranges_for_seeking(self):
        payload = b"0123456789abcdef"
        self._send_voice(duration=1200, waveform=[20, 50, 80])
        attachment = MessageAttachment.objects.get()
        # Replace the fixture content with a deterministic payload for the range assertion.
        attachment.file.delete(save=False)
        attachment.file.save("voice.webm", SimpleUploadedFile("voice.webm", payload), save=False)
        attachment.size = len(payload)
        attachment.mime_type = "audio/webm"
        attachment.save(update_fields=["file", "size", "mime_type"])

        self.client.force_login(self.bob)
        response = self.client.get(
            reverse("messenger:view_attachment", args=[attachment.pk]),
            HTTP_RANGE="bytes=2-6",
        )
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response["Accept-Ranges"], "bytes")
        self.assertEqual(response["Content-Range"], f"bytes 2-6/{len(payload)}")
        self.assertEqual(response["Content-Length"], "5")
        self.assertEqual(b"".join(response.streaming_content), payload[2:7])

    def test_voice_recorder_and_custom_player_assets_are_in_chat(self):
        response = self.client.get(reverse("messenger:chat", args=[self.chat.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="voiceRecordButton"', html=False)
        self.assertContains(response, 'id="voiceRecordingBar"', html=False)
        self.assertContains(response, "voice-messages.css", html=False)
        self.assertContains(response, "voice-messages.js", html=False)

    def test_forwarding_voice_obeys_recipient_voice_privacy(self):
        sent = self._send_voice()
        message_id = sent.json()["message"]["id"]

        charlie = User.objects.create_user(
            username="voice_charlie",
            email="voice-charlie@example.com",
            password=self.password,
        )
        target = get_or_create_direct_chat(self.alice, charlie)
        set_privacy_rule(charlie, "voice_messages", "nobody")

        response = self.client.post(
            reverse(
                "messenger:forward_message",
                args=[self.chat.pk, message_id],
            ),
            {"target_chat_id": str(target.pk)},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Message.objects.filter(chat=target).count(), 0)
