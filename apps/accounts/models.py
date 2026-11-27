from datetime import timedelta
from urllib.parse import quote

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import salted_hmac


class User(AbstractUser):
    class Theme(models.TextChoices):
        LIGHT = "light", "Светлая"
        DARK = "dark", "Тёмная"

    email = models.EmailField("электронная почта", unique=True)
    email_verified_at = models.DateTimeField(
        "подтверждение электронной почты", null=True, blank=True,
    )
    email_verification_sent_at = models.DateTimeField(
        "дата отправки подтверждения", null=True, blank=True,
    )
    bio = models.CharField("о себе", max_length=160, blank=True, default="")
    avatar = models.ImageField(
        "фотография профиля",
        upload_to="avatars/%Y/%m/",
        blank=True,
        default="",
    )
    theme = models.CharField(
        "тема оформления",
        max_length=10,
        choices=Theme.choices,
        default=Theme.LIGHT,
    )
    enter_to_send = models.BooleanField("отправка по Enter", default=True)
    media_preload = models.BooleanField("предзагрузка аудио и видео", default=True)
    keep_archived_chats = models.BooleanField(
        "всегда оставлять чаты в архиве",
        default=False,
    )
    keep_folder_chats_archived = models.BooleanField(
        "оставлять чаты из пользовательских папок в архиве",
        default=False,
    )
    archive_unknown_chats = models.BooleanField(
        "архивировать и отключать уведомления у новых чатов не из контактов",
        default=False,
    )
    archive_in_main_menu = models.BooleanField(
        "показывать архив в главном меню",
        default=True,
    )
    last_seen_at = models.DateTimeField("последняя активность", null=True, blank=True)
    birthday = models.DateField("день рождения", null=True, blank=True)
    personal_channel = models.ForeignKey(
        "messenger.Chat",
        verbose_name="личный канал",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="profile_owners",
    )
    privacy_settings = models.JSONField(
        "настройки конфиденциальности",
        default=dict,
        blank=True,
    )
    default_auto_delete_seconds = models.PositiveIntegerField(
        "автоудаление сообщений по умолчанию",
        default=0,
    )
    delete_after_inactive_days = models.PositiveSmallIntegerField(
        "удаление аккаунта после неактивности",
        default=365,
    )

    class PlatformRole(models.TextChoices):
        MEMBER = "", "Пользователь"
        MODERATOR = "moderator", "Модератор"
        ADMIN = "admin", "Администратор"
        OWNER = "owner", "Владелец платформы"

    platform_role = models.CharField(max_length=12, choices=PlatformRole.choices, blank=True, default="", editable=False, db_index=True)
    platform_suspended_at = models.DateTimeField(null=True, blank=True, editable=False, db_index=True)
    platform_suspension_reason = models.CharField(max_length=300, blank=True, default="", editable=False)
    security_version = models.PositiveBigIntegerField(default=0, editable=False)
    last_login_alert_at = models.DateTimeField(null=True, blank=True, editable=False)
    two_factor_secret = models.TextField(blank=True, default="", editable=False)
    two_factor_recovery_hashes = models.JSONField(default=list, blank=True, editable=False)
    two_factor_last_step = models.BigIntegerField(default=-1, editable=False)
    two_factor_failures = models.PositiveSmallIntegerField(default=0, editable=False)
    two_factor_failure_window = models.DateTimeField(null=True, blank=True, editable=False)

    @property
    def two_factor_enabled(self):
        return bool(self.two_factor_secret)

    def _get_session_auth_hash(self, secret=None):
        # Preserve existing sessions until the account changes its 2FA settings.
        if not self.security_version:
            return super()._get_session_auth_hash(secret=secret)
        return salted_hmac(
            "sovietgram.session-auth.security-version.v1",
            f"{self.password}|{self.security_version}",
            secret=secret, algorithm="sha256",
        ).hexdigest()

    @property
    def display_name(self):
        return self.get_full_name().strip() or self.username

    @property
    def avatar_url(self):
        if not self.avatar:
            return ""
        # The protected avatar route is intentionally stable by username.
        # Add the stored filename as a version so a newly uploaded picture
        # cannot be reused from an older in-memory/browser image cache.
        version = quote(self.avatar.name, safe="")
        return f"{reverse('accounts:profile_avatar', args=[self.username])}?v={version}"

    @property
    def initials(self):
        parts = self.get_full_name().split()
        if parts:
            return "".join(part[0] for part in parts[:2]).upper()
        return self.username[:2].upper() or "?"

    @property
    def is_online(self):
        return bool(
            self.last_seen_at
            and self.last_seen_at >= timezone.now() - timedelta(minutes=2)
        )

    def __str__(self):
        return self.username


class UserBlock(models.Model):
    blocker = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="blocked_user_links",
    )
    blocked = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="blocked_by_links",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("blocker", "blocked"),
                name="unique_user_block",
            ),
        ]

    def __str__(self):
        return f"{self.blocker} blocks {self.blocked}"


class AccountSecurityRequest(models.Model):
    """One outstanding credential operation per account and purpose."""

    class Purpose(models.TextChoices):
        PASSWORD_RESET = "password_reset", "Восстановление пароля"
        EMAIL_CHANGE = "email_change", "Изменение почты"

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="security_requests",
    )
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    token_digest = models.CharField(max_length=64, null=True, blank=True, unique=True)
    email = models.EmailField()
    account_state = models.CharField(max_length=64)
    issued_at = models.DateTimeField()
    expires_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "purpose"), name="unique_account_security_purpose",
            ),
        ]


class SecurityEvent(models.Model):
    class Kind(models.TextChoices):
        LOGIN = "login", "Вход в аккаунт"
        PASSWORD = "password", "Изменение пароля"
        RESET = "password_reset", "Восстановление пароля"
        EMAIL = "email_change", "Изменение почты"
        FACTOR_ENABLE = "factor_enable", "Включение двухфакторной защиты"
        FACTOR_DISABLE = "factor_disable", "Отключение двухфакторной защиты"
        FACTOR_CODES = "factor_codes", "Обновление резервных кодов"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="security_events")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    device = models.CharField(max_length=240, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-id",)
        indexes = [models.Index(fields=["user", "-id"], name="sg_security_user_idx")]
