from datetime import timedelta

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    class Theme(models.TextChoices):
        LIGHT = "light", "Светлая"
        DARK = "dark", "Тёмная"

    email = models.EmailField("электронная почта", unique=True)
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

    @property
    def display_name(self):
        return self.get_full_name().strip() or self.username

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
