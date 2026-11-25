from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [("accounts", "0012_platform_roles"), ("messenger", "0025_platform_public_restriction")]
    operations = [
        migrations.CreateModel(
            name="PlatformReport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(max_length=12, choices=[("user", "Пользователь"), ("message", "Сообщение"), ("community", "Сообщество")])),
                ("target_id", models.PositiveBigIntegerField()),
                ("target_label", models.CharField(max_length=180)),
                ("reason", models.CharField(max_length=12, choices=[("spam", "Спам / мошенничество"), ("abuse", "Оскорбления / травля"), ("illegal", "Запрещённый контент"), ("other", "Другое")])),
                ("details", models.CharField(blank=True, max_length=1000)),
                ("status", models.CharField(max_length=12, choices=[("open", "На рассмотрении"), ("resolved", "Решена"), ("dismissed", "Отклонена")], default="open", db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("decision", models.CharField(blank=True, max_length=300)),
                ("reporter", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="platform_reports", to=settings.AUTH_USER_MODEL)),
                ("decided_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="platform_report_decisions", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-id",), "constraints": [models.UniqueConstraint(fields=("reporter", "kind", "target_id"), condition=models.Q(status="open"), name="sg_platform_one_open_report")], "indexes": [models.Index(fields=["status", "-id"], name="sg_platform_report_queue")]},
        ),
        migrations.CreateModel(
            name="PlatformAudit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("actor_label", models.CharField(max_length=180)),
                ("action", models.CharField(max_length=40)),
                ("target_kind", models.CharField(max_length=20)),
                ("target_id", models.PositiveBigIntegerField()),
                ("target_label", models.CharField(max_length=180)),
                ("reason", models.CharField(max_length=300)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="platform_audit_actions", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-id",)},
        ),
    ]
