from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.db import models
from django.utils import timezone


def message_attachment_path(instance, filename):
    extension = Path(filename).suffix.lower()[:12]
    now = timezone.now()
    return f"messages/{instance.message.chat_id}/{now:%Y/%m}/{uuid4().hex}{extension}"


def chat_avatar_path(instance, filename):
    extension = Path(filename).suffix.lower()[:12]
    return f"chat_avatars/{instance.pk or 'new'}/{uuid4().hex}{extension}"


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
    title = models.CharField(max_length=120, blank=True, default="")
    username = models.CharField(max_length=64, unique=True, null=True, blank=True)
    description = models.TextField(max_length=500, blank=True, default="")
    avatar = models.ImageField(upload_to=chat_avatar_path, blank=True)
    history_visible_to_new_members = models.BooleanField(default=True)
    members_can_send_messages = models.BooleanField(default=True)
    members_can_send_media = models.BooleanField(default=True)
    members_can_send_links = models.BooleanField(default=True)
    members_can_add_members = models.BooleanField(default=False)
    members_can_pin_messages = models.BooleanField(default=False)
    slow_mode_seconds = models.PositiveSmallIntegerField(default=0)
    signatures_enabled = models.BooleanField(default=False)
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
    can_see_pre_join_history = models.BooleanField(default=True)
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
    is_hidden = models.BooleanField(default=False, db_index=True)
    cleared_before_message_id = models.PositiveBigIntegerField(default=0)
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
    class SpecialType(models.TextChoices):
        NONE = "", "Обычное сообщение"
        POLL = "poll", "Опрос"
        TODO = "todo", "Список задач"
        ARTICLE = "article", "Статья"
        LOCATION = "location", "Геопозиция"

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
    signature_name = models.CharField(max_length=300, blank=True, default="")
    special_type = models.CharField(
        max_length=16,
        choices=SpecialType.choices,
        blank=True,
        default=SpecialType.NONE,
        db_index=True,
    )
    special_data = models.JSONField(blank=True, default=dict)
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
        if self.special_type == self.SpecialType.POLL:
            question = " ".join(str(self.special_data.get("question", "")).split())
            return f"Опрос: {question}" if question else "Опрос"
        if self.special_type == self.SpecialType.TODO:
            title = " ".join(str(self.special_data.get("title", "")).split())
            return f"Список задач: {title}" if title else "Список задач"
        if self.special_type == self.SpecialType.ARTICLE:
            title = " ".join(str(self.special_data.get("title", "")).split())
            return title or "Статья"
        if self.special_type == self.SpecialType.LOCATION:
            label = " ".join(str(self.special_data.get("label", "")).split())
            return f"Геопозиция: {label}" if label else "Геопозиция"
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


class MessageHiddenForUser(models.Model):
    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name="hidden_for_users",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="hidden_chat_messages",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("message", "user"),
                name="unique_hidden_message_for_user",
            ),
        ]

    def __str__(self):
        return f"{self.user} hides message {self.message_id}"


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


class ChatInviteLink(models.Model):
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name="invite_links")
    token = models.CharField(max_length=64, unique=True, db_index=True)
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_chat_invite_links",
    )
    name = models.CharField(max_length=64, blank=True, default="")
    expires_at = models.DateTimeField(null=True, blank=True)
    usage_limit = models.PositiveIntegerField(null=True, blank=True)
    usage_count = models.PositiveIntegerField(default=0)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-id")

    @property
    def is_active(self):
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None and self.expires_at <= timezone.now():
            return False
        if self.usage_limit is not None and self.usage_count >= self.usage_limit:
            return False
        return True

    def __str__(self):
        return f"Invite for {self.chat_id}: {self.name or self.token[:8]}"


class ChatAdminLog(models.Model):
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name="admin_log")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="chat_admin_actions",
    )
    action = models.CharField(max_length=64, db_index=True)
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chat_admin_actions_targeting",
    )
    description = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at", "-id")

    def __str__(self):
        return f"{self.chat_id}: {self.description}"
