import json
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from .models import Message
from .services import get_or_create_direct_chat


class TodoDeadlineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("todoalice", "todoalice@example.net", "Password-1945!")
        cls.bob = User.objects.create_user("todobob", "todobob@example.net", "Password-1945!")
        cls.chat = get_or_create_direct_chat(cls.alice, cls.bob)

    def setUp(self):
        self.client.force_login(self.alice)
        self.url = reverse("messenger:send_special_message", args=[self.chat.pk])

    def create(self, tasks):
        return self.client.post(self.url, {"special_type":"todo", "payload":json.dumps({
            "title":"Tasks", "tasks":tasks, "allow_others_add":True, "allow_others_mark":True,
        })}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_deadlines_progress_and_idempotent_mark(self):
        past = (timezone.localdate()-timedelta(days=2)).isoformat()
        result = self.create([{"text":"First", "due_date":past}, "Legacy"])
        self.assertEqual(result.status_code, 200, result.content)
        message = result.json()["message"]
        special = message["special"]
        self.assertTrue(special["tasks"][0]["overdue"])
        self.assertEqual(special["tasks"][0]["due_date"], past)
        self.assertEqual(special["tasks"][1]["due_date"], "")
        self.assertEqual(special["total"], 2)
        url = reverse("messenger:special_message_action", args=[self.chat.pk,message["id"]])
        self.client.force_login(self.bob)
        for _ in range(2):
            marked = self.client.post(url, {"action":"set_done","index":"0","done":"1"})
            self.assertEqual(marked.status_code, 200, marked.content)
            updated = marked.json()["message"]["special"]
            self.assertEqual(updated["completed"], 1)
            self.assertFalse(updated["tasks"][0]["overdue"])
        self.assertEqual(self.client.post(url, {"action":"set_due","index":"0","due_date":""}).status_code, 403)
        added = self.client.post(url, {"action":"add","text":"New","due_date":past})
        self.assertEqual(added.json()["message"]["special"]["tasks"][-1]["due_date"], past)
        self.client.force_login(self.alice)
        cleared = self.client.post(url, {"action":"set_due","index":"0","due_date":""})
        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(cleared.json()["message"]["special"]["tasks"][0]["due_date"], "")
        self.assertEqual(Message.objects.get(pk=message["id"]).special_data["tasks"][0]["done_by"], self.bob.pk)
        page = self.client.get(reverse("messenger:chat", args=[self.chat.pk]))
        self.assertContains(page, "1/3")
        self.assertContains(page, "Просрочено")

    def test_invalid_calendar_dates_rejected(self):
        for date in ("2027-02-29", "next Tuesday", "2026-1-2"):
            result = self.create([{"text":"Bad", "due_date":date}])
            self.assertEqual(result.status_code, 400)
        self.assertFalse(Message.objects.filter(chat=self.chat).exists())
