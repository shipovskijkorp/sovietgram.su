from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.db import models
from django.utils import timezone


def message_attachment_path(instance, filename):
    extension = Path(filename).suffix.lower()[:12]
    now = timezone.now()
    return f"messages/{instance.message.chat_id}/{now:%Y/%m}/{uuid4().hex}{extension}"


class Contact(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="contact_links",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="contact_of",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(fields=("owner", "user"), name="unique_contact"),
        ]

    def __str__(self):
        return f"{self.owner} -> {self.user}"


class Chat(models.Model):
    class Type(models.TextChoices):
        PRIVATE = "private", "Личный чат"
        GROUP = "group", "Группа"
        CHANNEL = "channel", "Канал"

    type = models.CharField(
        max_length=16,
        choices=Type.choices,
        default=Type.PRIVATE,
        db_index=True,
    )
    participants = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="ChatParticipant",
        related_name="messenger_chats",
    )
    direct_key = models.CharField(max_length=64, unique=True, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        ordering = ("-updated_at", "-id")

    def __str__(self):
        return f"Chat {self.pk}"


class ChatParticipant(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Владелец"
        ADMIN = "admin", "Администратор"
        MEMBER = "member", "Участник"

    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_memberships",
    )
    role = models.CharField(
        max_length=16,
        choices=Role.choices,
        default=Role.MEMBER,
        db_index=True,
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    last_read_message = models.ForeignKey(
        "Message",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="read_by_memberships",
    )
    is_pinned = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    is_muted = models.BooleanField(default=False)
    draft_text = models.TextField(blank=True, default="", max_length=4096)
    draft_updated_at = models.DateTimeField(null=True, blank=True)
    last_typing_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("chat", "user"), name="unique_chat_participant"),
        ]

    def __str__(self):
        return f"{self.user} in {self.chat}"


class Message(models.Model):
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sent_messages",
    )
    text = models.TextField(blank=True, max_length=4096)
    reply_to = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="replies",
    )
    forwarded_from = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="forwarded_copies",
    )
    forwarded_from_name = models.CharField(max_length=300, blank=True, default="")
    forwarded_from_username = models.CharField(max_length=150, blank=True, default="")
    is_deleted = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)
    edited_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("id",)

    @property
    def preview(self):
        if self.is_deleted:
            return "Сообщение удалено"
        compact = " ".join(self.text.split())
        if compact:
            return compact
        attachment = self.attachments.first()
        if not attachment:
            return "Сообщение"
        return {
            MessageAttachment.Kind.IMAGE: "Фото",
            MessageAttachment.Kind.VIDEO: "Видео",
            MessageAttachment.Kind.AUDIO: "Аудио",
        }.get(attachment.kind, "Файл")

    def __str__(self):
        return self.preview[:80]


class MessageAttachment(models.Model):
    class Kind(models.TextChoices):
        IMAGE = "image", "Изображение"
        VIDEO = "video", "Видео"
        AUDIO = "audio", "Аудио"
        FILE = "file", "Файл"

    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to=message_attachment_path)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.FILE)
    original_name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=127, blank=True)
    size = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.original_name


class PinnedMessage(models.Model):
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name="pinned_messages")
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="pin_records")
    pinned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="pinned_chat_messages",
    )
    pinned_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-pinned_at", "-id")
        constraints = [
            models.UniqueConstraint(fields=("chat", "message"), name="unique_pinned_message"),
        ]

    def __str__(self):
        return f"Pinned {self.message_id} in {self.chat_id}"
