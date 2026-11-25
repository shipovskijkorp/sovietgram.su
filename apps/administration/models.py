from django.conf import settings
from django.db import models


class PlatformReport(models.Model):
    class Kind(models.TextChoices):
        USER = "user", "Пользователь"
        MESSAGE = "message", "Сообщение"
        COMMUNITY = "community", "Сообщество"

    class Reason(models.TextChoices):
        SPAM = "spam", "Спам / мошенничество"
        ABUSE = "abuse", "Оскорбления / травля"
        ILLEGAL = "illegal", "Запрещённый контент"
        OTHER = "other", "Другое"

    class Status(models.TextChoices):
        OPEN = "open", "На рассмотрении"
        RESOLVED = "resolved", "Решена"
        DISMISSED = "dismissed", "Отклонена"

    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="platform_reports")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    target_id = models.PositiveBigIntegerField()
    target_label = models.CharField(max_length=180)
    reason = models.CharField(max_length=12, choices=Reason.choices)
    details = models.CharField(max_length=1000, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="platform_report_decisions")
    decision = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ("-id",)
        constraints = [
            models.UniqueConstraint(fields=("reporter", "kind", "target_id"), condition=models.Q(status="open"), name="sg_platform_one_open_report"),
        ]
        indexes = [models.Index(fields=("status", "-id"), name="sg_platform_report_queue")]


class PlatformAudit(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="platform_audit_actions")
    actor_label = models.CharField(max_length=180)
    action = models.CharField(max_length=40)
    target_kind = models.CharField(max_length=20)
    target_id = models.PositiveBigIntegerField()
    target_label = models.CharField(max_length=180)
    reason = models.CharField(max_length=300)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-id",)
