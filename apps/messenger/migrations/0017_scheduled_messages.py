from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("messenger", "0016_message_reactions"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="message",
            name="silent",
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name="ScheduledMessage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("client_id", models.UUIDField()),
                ("request_digest", models.CharField(max_length=64)),
                ("text", models.TextField(blank=True, max_length=4096)),
                ("reply_message_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("silent", models.BooleanField(default=False)),
                ("scheduled_for", models.DateTimeField()),
                ("next_attempt_at", models.DateTimeField()),
                ("status", models.CharField(choices=[("pending", "Запланировано"), ("failed", "Не отправлено"), ("sent", "Отправлено"), ("canceled", "Отменено")], default="pending", max_length=12)),
                ("error", models.CharField(blank=True, default="", max_length=300)),
                ("revision", models.PositiveBigIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("chat", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="scheduled_messages", to="messenger.chat")),
                ("sender", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="scheduled_messages", to=settings.AUTH_USER_MODEL)),
                ("delivered_message", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="scheduled_sources", to="messenger.message")),
            ],
            options={
                "constraints": [models.UniqueConstraint(fields=("sender", "client_id"), name="unique_scheduled_send_key")],
                "indexes": [
                    models.Index(fields=["status", "next_attempt_at", "id"], name="sg_sched_due_idx"),
                    models.Index(fields=["sender", "chat", "status"], name="sg_sched_owner_idx"),
                ],
            },
        ),
    ]
