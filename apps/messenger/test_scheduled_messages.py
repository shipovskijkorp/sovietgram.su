from datetime import timedelta
from tempfile import TemporaryDirectory
from uuid import uuid4

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User, UserBlock
from .models import Chat, ChatParticipant, Message, MessageAttachment, MessageHiddenForUser, ScheduledMessage, Sticker, StickerPack
from .scheduled import deliver_due_messages
from .services import get_or_create_direct_chat


class ScheduledMessageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.net", "Password-1945!")
        cls.bob = User.objects.create_user("bob", "bob@example.net", "Password-1945!")
        cls.outsider = User.objects.create_user("outsider", "other@example.net", "Password-1945!")
        cls.chat = get_or_create_direct_chat(cls.alice, cls.bob)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.alice)
        self.peer = Client()
        self.peer.force_login(self.bob)

    def url(self, chat=None):
        return reverse("messenger:scheduled_messages", args=[(chat or self.chat).pk])

    def data(self, **overrides):
        return {
            "account_id": str(self.alice.pk), "client_message_id": str(uuid4()),
            "text": "**Scheduled**", "scheduled_for": (timezone.now()+timedelta(minutes=5)).isoformat(),
            "silent": "1", **overrides,
        }

    def schedule(self, chat=None, **overrides):
        response = self.client.post(self.url(chat), self.data(**overrides))
        self.assertEqual(response.status_code, 200, response.content)
        return ScheduledMessage.objects.get(pk=response.json()["item"]["id"])

    def make_due(self, item):
        ScheduledMessage.objects.filter(pk=item.pk).update(next_attempt_at=timezone.now()-timedelta(seconds=1))

    def action(self, item, action, **overrides):
        return self.client.post(reverse("messenger:scheduled_action", args=[item.chat_id,item.pk]), {
            "account_id": str(self.alice.pk), "revision": item.revision, "action": action, **overrides,
        })

    def test_private_queue_invisible_until_delivery_and_idempotent_worker(self):
        before = self.chat.updated_at
        item = self.schedule()
        self.assertEqual(self.peer.get(self.url()).json()["items"], [])
        self.assertEqual(self.client.get(self.url()).json()["items"][0]["text"], "**Scheduled**")
        self.assertFalse(Message.objects.exists())
        self.assertEqual(deliver_due_messages(), 0)
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.updated_at, before)
        self.assertEqual(self.peer.get(reverse("messenger:message_history", args=[self.chat.pk])).json()["messages"], [])
        self.make_due(item)
        self.assertEqual(deliver_due_messages(), 1)
        self.assertEqual(deliver_due_messages(), 0)
        item.refresh_from_db()
        self.assertEqual(item.status, ScheduledMessage.Status.SENT)
        self.assertEqual(item.text, "")
        message = item.delivered_message
        self.assertTrue(message.silent)
        self.assertEqual(message.text, "**Scheduled**")
        history = self.peer.get(reverse("messenger:message_history", args=[self.chat.pk])).json()["messages"]
        self.assertEqual(len(history), 1)
        self.assertIn("<strong>Scheduled</strong>", history[0]["markdown_html"])
        self.assertTrue(history[0]["silent"])
        self.assertEqual(self.client.get(self.url()).json()["items"], [])

    def test_scheduled_poll_remains_private_and_delivers_as_poll(self):
        import json
        payload = {"question": "Pick one", "options": ["A", "B"], "quiz": True,
                   "correct_option": 1, "explanation": "private explanation"}
        data = self.data(text="", special_type="poll", payload=json.dumps(payload))
        result = self.client.post(self.url(), data)
        self.assertEqual(result.status_code, 200, result.content)
        item = ScheduledMessage.objects.get(pk=result.json()["item"]["id"])
        self.assertEqual(item.special_type, "poll")
        self.assertEqual(item.special_data["correct_option"], 1)
        self.assertTrue(self.client.post(self.url(), data).json()["replayed"])
        self.assertEqual(self.peer.get(self.url()).json()["items"], [])
        self.assertFalse(Message.objects.exists())
        self.make_due(item)
        self.assertEqual(deliver_due_messages(), 1)
        self.assertEqual(deliver_due_messages(), 0)
        item.refresh_from_db()
        self.assertEqual(item.special_data, {})
        self.assertEqual(item.special_type, "")
        message = item.delivered_message
        self.assertEqual(message.special_type, "poll")
        self.assertEqual(message.special_data["correct_option"], 1)
        self.assertEqual(message.special_data["options"][0]["voters"], [])
        self.assertTrue(message.silent)
        response = self.peer.get(reverse("messenger:message_history", args=[self.chat.pk]))
        self.assertNotContains(response, "private explanation")
        self.assertNotContains(response, '"correct_option":')

    def test_scheduled_special_reschedule_cancel_and_link_policy(self):
        import json
        group = Chat.objects.create(type=Chat.Type.GROUP, title="Group")
        ChatParticipant.objects.create(chat=group, user=self.alice)
        ChatParticipant.objects.create(chat=group, user=self.bob, role="owner")
        item = self.schedule(group, text="", special_type="todo",
            payload=json.dumps({"title":"Tasks","tasks":["Read https://example.org"]}))
        updated = self.action(item, "edit", text="ignored", silent="0",
            scheduled_for=(timezone.now()+timedelta(hours=1)).isoformat())
        self.assertEqual(updated.status_code, 200, updated.content)
        item.refresh_from_db()
        self.assertEqual(item.text, "Tasks")
        self.assertEqual(item.special_data["tasks"][0]["text"], "Read https://example.org")
        Chat.objects.filter(pk=group.pk).update(members_can_send_links=False)
        self.make_due(item)
        self.assertEqual(deliver_due_messages(), 0)
        item.refresh_from_db()
        self.assertEqual(item.status, ScheduledMessage.Status.FAILED)
        self.assertEqual(self.action(item, "cancel").status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.special_data, {})
        self.assertFalse(Message.objects.filter(chat=group).exists())
        self.assertEqual(self.client.post(self.url(group), self.data(
            text="", special_type="todo", payload=json.dumps({"title":"Tasks","tasks":["https://example.org"]})
        )).status_code, 403)

    def test_invalid_scheduled_special_is_rejected(self):
        import json
        for kind, payload in (("poll", {"question":"Q","options":["A"]}),
                              ("location", {"latitude":100,"longitude":0}),
                              ("article", {"title":"T","body":""})):
            response = self.client.post(self.url(), self.data(text="", special_type=kind, payload=json.dumps(payload)))
            self.assertEqual(response.status_code, 400)
        self.assertFalse(ScheduledMessage.objects.exists())

    def test_scheduled_article_preserves_full_markdown_and_checks_late_links(self):
        import json
        group = Chat.objects.create(type=Chat.Type.GROUP, title="Group")
        ChatParticipant.objects.create(chat=group, user=self.alice)
        ChatParticipant.objects.create(chat=group, user=self.bob, role="owner")
        body = "**Long article**\n" + "x" * 20000 + "\nhttps://example.org"
        payload = {"title":"Article","subtitle":"Subtitle","body":body}
        item = self.schedule(group, text="", special_type="article", payload=json.dumps(payload))
        self.assertEqual(item.special_data["body"], body)
        self.assertLess(len(item.text), len(body))
        self.assertEqual(self.client.get(self.url(group)).json()["items"][0]["display_text"], "Article")
        self.assertEqual(self.peer.get(self.url(group)).json()["items"], [])
        Chat.objects.filter(pk=group.pk).update(members_can_send_links=False)
        self.make_due(item)
        self.assertEqual(deliver_due_messages(), 0)
        item.refresh_from_db()
        self.assertEqual(item.status, ScheduledMessage.Status.FAILED)
        Chat.objects.filter(pk=group.pk).update(members_can_send_links=True)
        response = self.action(item, "send_now")
        self.assertEqual(response.status_code, 200, response.content)
        item.refresh_from_db()
        self.assertEqual(item.status, ScheduledMessage.Status.SENT)
        self.assertEqual(item.special_data, {})
        message = item.delivered_message
        self.assertEqual(message.special_type, "article")
        self.assertEqual(message.special_data["body"], body)
        self.assertEqual(message.special_data["subtitle"], "Subtitle")

    def test_scheduled_sticker_snapshot_survives_pack_deletion(self):
        from io import BytesIO
        from PIL import Image
        buffer = BytesIO()
        Image.new("RGBA", (8, 8), "red").save(buffer, format="WEBP")
        image = buffer.getvalue()
        pack = StickerPack.objects.create(owner=self.alice, name="Test")
        sticker = Sticker.objects.create(pack=pack, image=image)
        data = self.data(text="", sticker_id=sticker.pk)
        result = self.client.post(self.url(), data)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(result.json()["item"]["attachment_type"], "sticker")
        item = ScheduledMessage.objects.get(pk=result.json()["item"]["id"])
        self.assertEqual(bytes(item.sticker_image), image)
        self.assertEqual(self.peer.get(self.url()).json()["items"], [])
        pack.delete()
        self.assertTrue(self.client.post(self.url(), data).json()["replayed"])
        updated = self.action(item, "edit", text="ignored",
            scheduled_for=(timezone.now()+timedelta(minutes=20)).isoformat())
        self.assertEqual(updated.status_code, 200, updated.content)
        item.refresh_from_db()
        self.assertEqual(item.text, "")
        self.make_due(item)
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            self.assertEqual(deliver_due_messages(), 1)
            self.assertEqual(deliver_due_messages(), 0)
            item.refresh_from_db()
            self.assertFalse(item.sticker_image)
            self.assertIsNone(item.sticker_source_id)
            message = item.delivered_message
            self.assertEqual(message.text, "")
            self.assertEqual(message.special_type, "")
            attachment = message.attachments.get()
            self.assertEqual(attachment.kind, MessageAttachment.Kind.STICKER)
            with attachment.file.open("rb") as stored:
                self.assertEqual(stored.read(), image)

    def test_scheduled_sticker_ownership_media_permission_and_cancel(self):
        own_pack = StickerPack.objects.create(owner=self.alice, name="Own")
        own = Sticker.objects.create(pack=own_pack, image=b"sticker")
        peer_pack = StickerPack.objects.create(owner=self.bob, name="Peer")
        peer_sticker = Sticker.objects.create(pack=peer_pack, image=b"peer")
        self.assertEqual(self.client.post(self.url(), self.data(text="", sticker_id=peer_sticker.pk)).status_code, 404)
        self.assertEqual(self.client.post(self.url(), self.data(text="mixed", sticker_id=own.pk)).status_code, 400)
        group = Chat.objects.create(type=Chat.Type.GROUP, title="Media only", members_can_send_messages=False)
        ChatParticipant.objects.create(chat=group, user=self.alice)
        ChatParticipant.objects.create(chat=group, user=self.bob, role="owner")
        item = self.schedule(group, text="", sticker_id=own.pk)
        Chat.objects.filter(pk=group.pk).update(members_can_send_media=False)
        self.make_due(item)
        self.assertEqual(deliver_due_messages(), 0)
        item.refresh_from_db()
        self.assertEqual(item.status, ScheduledMessage.Status.FAILED)
        self.assertEqual(self.action(item, "cancel").status_code, 200)
        item.refresh_from_db()
        self.assertFalse(item.sticker_image)
        self.assertIsNone(item.sticker_source_id)
        self.assertFalse(Message.objects.filter(chat=group).exists())

    def test_create_retry_does_not_duplicate_or_recreate_cancelled_item(self):
        data = self.data()
        first = self.client.post(self.url(), data).json()
        second = self.client.post(self.url(), data).json()
        self.assertTrue(second["replayed"])
        self.assertEqual(first["item"]["id"], second["item"]["id"])
        changed = self.client.post(self.url(), {**data,"silent":"0"})
        self.assertEqual(changed.status_code, 409)
        item = ScheduledMessage.objects.get(pk=first["item"]["id"])
        self.assertEqual(self.action(item,"cancel").status_code,200)
        third = self.client.post(self.url(), data).json()
        self.assertEqual(third["item"]["status"], "canceled")
        self.assertEqual(ScheduledMessage.objects.count(), 1)
        self.make_due(item)
        self.assertEqual(deliver_due_messages(), 0)

    def test_edit_revision_and_send_now_keep_new_draft(self):
        item = self.schedule()
        update = self.action(item, "edit", text="Changed", silent="0",
                             scheduled_for=(timezone.now()+timedelta(hours=1)).isoformat())
        self.assertEqual(update.status_code, 200, update.content)
        self.assertEqual(self.action(item, "cancel").status_code, 409)
        item.refresh_from_db()
        ChatParticipant.objects.filter(chat=self.chat,user=self.alice).update(draft_text="New draft")
        response = self.action(item, "send_now")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["item"]["status"], "sent")
        self.assertTrue(self.action(item,"send_now").json()["replayed"])
        self.assertEqual(Message.objects.count(),1)
        self.assertEqual(Message.objects.get().text,"Changed")
        self.assertFalse(Message.objects.get().silent)
        self.assertEqual(ChatParticipant.objects.get(chat=self.chat,user=self.alice).draft_text,"New draft")

    def test_worker_checks_block_and_allows_recovery(self):
        item=self.schedule()
        block=UserBlock.objects.create(blocker=self.bob,blocked=self.alice)
        self.make_due(item)
        self.assertEqual(deliver_due_messages(),0)
        item.refresh_from_db()
        self.assertEqual(item.status,ScheduledMessage.Status.FAILED)
        self.assertTrue(item.error)
        self.assertFalse(Message.objects.exists())
        self.assertEqual(self.client.get(self.url()).json()["items"][0]["status"],"failed")
        block.delete()
        self.assertEqual(self.action(item,"send_now").json()["item"]["status"],"sent")
        self.assertEqual(Message.objects.count(),1)

    def test_deleted_reply_fails_instead_of_sending_unrelated_text(self):
        reply=Message.objects.create(chat=self.chat,sender=self.bob,text="Reply target")
        item=self.schedule(reply_to=str(reply.pk))
        reply.delete()
        self.make_due(item)
        self.assertEqual(deliver_due_messages(),0)
        item.refresh_from_db()
        self.assertEqual(item.status,ScheduledMessage.Status.FAILED)
        changed=self.action(item,"edit",text=item.text,silent="1",remove_reply="1",
                            scheduled_for=(timezone.now()+timedelta(minutes=5)).isoformat())
        self.assertEqual(changed.status_code,200,changed.content)
        item.refresh_from_db()
        self.assertIsNone(item.reply_message_id)
        self.assertEqual(self.action(item,"send_now").json()["item"]["status"],"sent")

    def test_slow_mode_defers_until_next_allowed_attempt(self):
        group=Chat.objects.create(type=Chat.Type.GROUP,title="Slow",slow_mode_seconds=60)
        ChatParticipant.objects.create(chat=group,user=self.bob,role=ChatParticipant.Role.OWNER)
        ChatParticipant.objects.create(chat=group,user=self.alice)
        Message.objects.create(chat=group,sender=self.alice,text="Recent")
        item=self.schedule(group)
        self.make_due(item)
        self.assertEqual(deliver_due_messages(),0)
        item.refresh_from_db()
        self.assertEqual(item.status,ScheduledMessage.Status.PENDING)
        self.assertGreater(item.next_attempt_at,timezone.now())
        self.assertIn("Медленный режим",item.error)
        Message.objects.filter(chat=group).update(created_at=timezone.now()-timedelta(minutes=2))
        self.make_due(item)
        self.assertEqual(deliver_due_messages(),1)

    def test_worker_starts_auto_delete_clock_only_at_delivery(self):
        Chat.objects.filter(pk=self.chat.pk).update(auto_delete_seconds=60)
        item=self.schedule()
        self.assertFalse(Message.objects.exists())
        self.make_due(item)
        now=timezone.now()
        call_command("deliver_scheduled_messages")
        item.refresh_from_db()
        self.assertGreaterEqual(item.delivered_message.expires_at,now+timedelta(seconds=60))
        self.assertLess(item.delivered_message.expires_at,now+timedelta(seconds=65))

    def test_permissions_stale_account_invalid_time_and_csrf(self):
        item=self.schedule()
        self.assertEqual(self.peer.post(reverse("messenger:scheduled_action",args=[self.chat.pk,item.pk]),{
            "account_id":str(self.bob.pk),"revision":item.revision,"action":"cancel",
        }).status_code,404)
        self.assertEqual(self.client.get(self.url(),{"account_id":self.bob.pk}).status_code,409)
        self.assertEqual(self.client.post(self.url(),self.data(account_id=self.bob.pk)).status_code,409)
        for when in ("invalid","2026-01-01T10:00",(timezone.now()-timedelta(seconds=2)).isoformat(),
                     (timezone.now()+timedelta(days=366)).isoformat()):
            self.assertEqual(self.client.post(self.url(),self.data(scheduled_for=when)).status_code,400)
        csrf=Client(enforce_csrf_checks=True)
        csrf.force_login(self.alice)
        self.assertEqual(csrf.post(self.url(),self.data()).status_code,403)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.url()).status_code,404)
        self.assertTrue(ScheduledMessage.objects.filter(pk=item.pk,status="pending").exists())

    def test_schedule_respects_current_posting_permissions(self):
        group=Chat.objects.create(type=Chat.Type.CHANNEL,title="Read-only channel")
        ChatParticipant.objects.create(chat=group,user=self.bob,role=ChatParticipant.Role.OWNER)
        ChatParticipant.objects.create(chat=group,user=self.alice)
        self.assertEqual(self.client.post(self.url(group),self.data()).status_code,403)


class SoundNotificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice=User.objects.create_user("alice","alice@example.net","Password-1945!")
        cls.bob=User.objects.create_user("bob","bob@example.net","Password-1945!")
        cls.chat=get_or_create_direct_chat(cls.alice,cls.bob)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.bob)
        self.url=reverse("messenger:poll_sound_notifications")
        self.since=(timezone.now()-timedelta(seconds=10)).isoformat()

    def ids(self):
        response=self.client.get(self.url,{"since":self.since})
        self.assertEqual(response.status_code,200,response.content)
        self.assertIn("no-store",response["Cache-Control"])
        return response.json()["ids"]

    def test_quiet_messages_stay_unread_but_do_not_trigger_sound(self):
        sender=Client()
        sender.force_login(self.alice)
        send=reverse("messenger:send_message",args=[self.chat.pk])
        key=str(uuid4())
        first=sender.post(send,{"text":"Silent","silent":"1","client_message_id":key},HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(first.status_code,200,first.content)
        self.assertTrue(first.json()["message"]["silent"])
        self.assertTrue(sender.post(send,{"text":"Silent","silent":"1","client_message_id":key},
                                   HTTP_X_REQUESTED_WITH="XMLHttpRequest").json()["replayed"])
        loud=Message.objects.create(chat=self.chat,sender=self.alice,text="Normal")
        self.assertEqual(self.ids(),[loud.pk])
        self.assertEqual(self.client.get(self.url).json()["ids"],[])
        page=self.client.get(reverse("messenger:home"))
        self.assertContains(page,'<span class="chat-row__unread">2</span>',html=True)
        self.assertEqual(Message.objects.filter(chat=self.chat).count(),2)

    def test_muted_hidden_read_and_own_messages_are_not_audible(self):
        first=Message.objects.create(chat=self.chat,sender=self.alice,text="Incoming")
        membership=ChatParticipant.objects.get(chat=self.chat,user=self.bob)
        self.assertEqual(self.ids(),[first.pk])
        membership.is_muted=True
        membership.save(update_fields=["is_muted"])
        self.assertEqual(self.ids(),[])
        membership.muted_until=timezone.now()-timedelta(seconds=1)
        membership.save(update_fields=["muted_until"])
        self.assertEqual(self.ids(),[first.pk])
        membership.read_through_id=first.pk
        membership.save(update_fields=["read_through_id"])
        hidden=Message.objects.create(chat=self.chat,sender=self.alice,text="Hidden")
        MessageHiddenForUser.objects.create(message=hidden,user=self.bob)
        Message.objects.create(chat=self.chat,sender=self.bob,text="Own")
        self.assertEqual(self.ids(),[])

    def test_silent_file_upload(self):
        self.client.force_login(self.alice)
        with TemporaryDirectory() as folder, override_settings(MEDIA_ROOT=folder):
            response=self.client.post(reverse("messenger:send_message",args=[self.chat.pk]),{
                "attachment_mode":"file","attachments":SimpleUploadedFile("file.txt",b"abc",content_type="text/plain"),
                "silent":"1",
            },HTTP_X_REQUESTED_WITH="XMLHttpRequest")
            self.assertEqual(response.status_code,200,response.content)
            self.assertTrue(response.json()["message"]["silent"])
            self.client.force_login(self.bob)
            self.assertEqual(self.ids(),[])
