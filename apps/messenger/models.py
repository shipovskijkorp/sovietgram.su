from datetime import timedelta
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
    alias = models.CharField(max_length=100, blank=True, default="")
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
    protect_content = models.BooleanField(default=False)
    members_can_send_messages = models.BooleanField(default=True)
    members_can_send_media = models.BooleanField(default=True)
    members_can_send_links = models.BooleanField(default=True)
    members_can_add_members = models.BooleanField(default=False)
    members_can_pin_messages = models.BooleanField(default=False)
    slow_mode_seconds = models.PositiveSmallIntegerField(default=0)
    # NULL allows the full current reaction catalog; [] disables new reactions.
    allowed_reactions = models.JSONField(default=None, null=True, blank=True)
    signatures_enabled = models.BooleanField(default=False)
    comments_enabled = models.BooleanField(default=False)
    platform_public_restricted = models.BooleanField(default=False, editable=False)
    auto_delete_seconds = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        ordering = ("-updated_at", "-id")
        constraints = [
            models.CheckConstraint(condition=models.Q(platform_public_restricted=False) | models.Q(username__isnull=True), name="sg_chat_public_restriction"),
        ]

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
    # None preserves full privileges for existing administrators; [] is explicitly no privileges.
    admin_permissions = models.JSONField(default=None, null=True, blank=True)
    can_see_pre_join_history = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)
    last_read_message = models.ForeignKey(
        "Message",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="read_by_memberships",
    )
    # A durable read cursor survives deletion/expiry of the referenced message.
    read_through_id = models.PositiveBigIntegerField(default=0)
    # A personal reminder, independent of the real read receipt cursor.
    marked_unread_at = models.DateTimeField(null=True, blank=True)
    is_pinned = models.BooleanField(default=False)
    # Personal order within the current folder, independent of message activity.
    pin_order = models.PositiveBigIntegerField(default=0)
    is_archived = models.BooleanField(default=False)
    is_muted = models.BooleanField(default=False)
    muted_until = models.DateTimeField(null=True, blank=True)
    is_hidden = models.BooleanField(default=False, db_index=True)
    cleared_before_message_id = models.PositiveBigIntegerField(default=0)
    draft_text = models.TextField(blank=True, default="", max_length=4096)
    draft_updated_at = models.DateTimeField(null=True, blank=True)
    last_typing_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("chat", "user"), name="unique_chat_participant"),
        ]

    @property
    def notifications_muted(self):
        return bool(
            self.is_muted
            and (self.muted_until is None or self.muted_until > timezone.now())
        )

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
    silent = models.BooleanField(default=False)
    comments_closed = models.BooleanField(default=False)
    reaction_version = models.PositiveBigIntegerField(default=0)
    reaction_changed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)

    def save(self, *args, **kwargs):
        if self._state.adding and self.expires_at is None and self.chat_id:
            seconds = int(getattr(self.chat, "auto_delete_seconds", 0) or 0)
            if seconds > 0:
                self.expires_at = timezone.now() + timedelta(seconds=seconds)
        super().save(*args, **kwargs)

    class Meta:
        ordering = ("id",)

    @property
    def sync_revision(self):
        # Integer microseconds, safely representable by JS Number for the
        # lifetime of this application. Avoid lossy millisecond Date parsing.
        return int(self.updated_at.timestamp()) * 1_000_000 + self.updated_at.microsecond

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
            MessageAttachment.Kind.VOICE: "Голосовое сообщение",
            MessageAttachment.Kind.STICKER: "Стикер",
        }.get(attachment.kind, "Файл")

    def __str__(self):
        return self.preview[:80]


class ChannelPostView(models.Model):
    """A unique authenticated account viewing a channel publication."""

    post = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="channel_views")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="channel_post_views",
    )
    # NULL only for legacy views that were recorded before timestamps existed.
    viewed_at = models.DateTimeField(default=timezone.now, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("post", "user"), name="sg_channel_post_view_once"),
        ]
        indexes = [models.Index(fields=("post", "viewed_at"), name="sg_post_view_date_idx")]


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
        VOICE = "voice", "Голосовое сообщение"
        STICKER = "sticker", "Стикер"
        FILE = "file", "Файл"

    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to=message_attachment_path)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.FILE)
    original_name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=127, blank=True)
    size = models.PositiveBigIntegerField(default=0)
    duration_ms = models.PositiveIntegerField(default=0)
    waveform = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.original_name


class VoiceMessagePlayback(models.Model):
    attachment = models.ForeignKey(
        MessageAttachment,
        on_delete=models.CASCADE,
        related_name="voice_playbacks",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="voice_message_playbacks",
    )
    played_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("attachment", "user"),
                name="unique_voice_playback_per_user",
            ),
        ]
        ordering = ("-played_at", "-id")

    def __str__(self):
        return f"{self.user} played voice attachment {self.attachment_id}"


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
    requires_approval = models.BooleanField(default=False)
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


class MessageSendReceipt(models.Model):
    """Idempotency receipt; survives deletion of the original message."""

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="message_send_receipts",
    )
    client_id = models.UUIDField()
    request_digest = models.CharField(max_length=64)
    message = models.ForeignKey(
        Message, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="send_receipts",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("sender", "client_id"), name="unique_message_send_receipt"),
        ]


class MessageReaction(models.Model):
    """One emoji reaction per user and message."""

    class Emoji(models.TextChoices):
        THUMBS_UP = "👍", "Нравится"
        HEART = "❤️", "Любовь"
        FIRE = "🔥", "Огонь"
        LAUGH = "😂", "Смешно"
        SURPRISE = "😮", "Удивление"
        THUMBS_DOWN = "👎", "Не нравится"
        PARTY = "🎉", "Праздник"
        CLAP = "👏", "Аплодисменты"
        THINKING = "🤔", "Задумался"
        CRY = "😢", "Грустно"
        ANGRY = "😡", "Злость"
        HEART_EYES = "😍", "Восхищение"
        WINK = "😉", "Подмигивание"
        COOL = "😎", "Круто"
        SALUTE = "🫡", "Салют"
        OK = "👌", "Отлично"
        HUNDRED = "💯", "Сто процентов"
        PRAY = "🙏", "Спасибо"
        SKULL = "💀", "Череп"
        CLOWN = "🤡", "Клоун"
        FACEPALM = "🤦", "Фейспалм"
        POPCORN = "🍿", "Попкорн"
        ROCKET = "🚀", "Ракета"
        CHECK = "✅", "Согласен"

    message = models.ForeignKey(
        Message, on_delete=models.CASCADE, related_name="reactions",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="message_reactions",
    )
    emoji = models.CharField(max_length=8, choices=Emoji.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("message", "user"), name="unique_message_reaction_user"),
        ]


class ScheduledMessage(models.Model):
    """Private outbox. A Message ID is allocated only at actual delivery."""

    class Status(models.TextChoices):
        PENDING = "pending", "Запланировано"
        FAILED = "failed", "Не отправлено"
        SENT = "sent", "Отправлено"
        CANCELED = "canceled", "Отменено"

    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name="scheduled_messages")
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="scheduled_messages",
    )
    client_id = models.UUIDField()
    request_digest = models.CharField(max_length=64)
    text = models.TextField(blank=True, max_length=4096)
    # Keep the original ID even if the referenced message is removed.
    reply_message_id = models.PositiveBigIntegerField(null=True, blank=True)
    silent = models.BooleanField(default=False)
    scheduled_for = models.DateTimeField()
    next_attempt_at = models.DateTimeField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    error = models.CharField(max_length=300, blank=True, default="")
    revision = models.PositiveBigIntegerField(default=1)
    delivered_message = models.ForeignKey(
        Message, on_delete=models.SET_NULL, null=True, blank=True, related_name="scheduled_sources",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("sender", "client_id"), name="unique_scheduled_send_key"),
        ]
        indexes = [
            models.Index(fields=("status", "next_attempt_at", "id"), name="sg_sched_due_idx"),
            models.Index(fields=("sender", "chat", "status"), name="sg_sched_owner_idx"),
        ]


class ChatFolder(models.Model):
    """A personal saved chat filter; never changes chat membership or history."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_folders")
    name = models.CharField(max_length=32)
    position = models.PositiveIntegerField(default=0)
    revision = models.PositiveBigIntegerField(default=1)
    categories = models.JSONField(default=list, blank=True)
    included_chat_ids = models.JSONField(default=list, blank=True)
    excluded_chat_ids = models.JSONField(default=list, blank=True)
    pinned_chat_ids = models.JSONField(default=list, blank=True)
    exclude_muted = models.BooleanField(default=False)
    exclude_read = models.BooleanField(default=False)
    exclude_archived = models.BooleanField(default=False)

    class Meta:
        ordering = ("position", "pk")
        indexes = [models.Index(fields=("owner", "position"), name="sg_folder_owner_pos")]


class StickerPack(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sticker_packs")
    name = models.CharField(max_length=48)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("id",)


class Sticker(models.Model):
    pack = models.ForeignKey(StickerPack, on_delete=models.CASCADE, related_name="stickers")
    emoji = models.CharField(max_length=24, blank=True, default="")
    # Bounded, normalized small WebP assets. Cascading deletes need no file cleanup.
    image = models.BinaryField()
    is_favorite = models.BooleanField(default=False)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("id",)


class ChatJoinRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "На рассмотрении"
        APPROVED = "approved", "Одобрена"
        REJECTED = "rejected", "Отклонена"
        CANCELED = "canceled", "Отменена"

    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name="join_requests")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_join_requests")
    invite = models.ForeignKey(ChatInviteLink, on_delete=models.CASCADE, related_name="join_requests")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(default=timezone.now)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="decided_join_requests")

    class Meta:
        ordering = ("created_at", "pk")
        constraints = [models.UniqueConstraint(fields=("chat", "user"), name="unique_chat_join_request")]
        indexes = [models.Index(fields=("chat", "status", "created_at"), name="sg_join_chat_status_idx")]


class ChatMemberModeration(models.Model):
    """Community-local sanctions survive membership removal and rejoining."""
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name="member_moderation")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="community_moderation")
    banned = models.BooleanField(default=False)
    denied_permissions = models.JSONField(default=list, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(max_length=200, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                              related_name="community_moderation_actions")

    class Meta:
        ordering = ("-updated_at", "-pk")
        constraints = [models.UniqueConstraint(fields=("chat", "user"), name="unique_chat_member_moderation")]
        indexes = [models.Index(fields=("chat", "banned", "expires_at"), name="sg_chat_moderation_idx")]


class ChannelComment(models.Model):
    """A text discussion belonging to exactly one channel publication."""
    post = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="channel_comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="channel_comments")
    client_id = models.UUIDField()
    text = models.TextField(max_length=4096)
    reply_to = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="replies")
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    edited_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("id",)
        constraints = [
            models.UniqueConstraint(fields=("post", "author", "client_id"), name="sg_comment_send_once"),
        ]
        indexes = [models.Index(fields=("post", "is_deleted", "id"), name="sg_comment_post_visible_idx")]
