from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("messenger", "0020_sticker_packs"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.AddField(model_name="sticker", name="is_favorite", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="sticker", name="last_used_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="chatinvitelink", name="requires_approval", field=models.BooleanField(default=False)),
        migrations.CreateModel(
            name="ChatJoinRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(max_length=16, choices=[("pending", "На рассмотрении"), ("approved", "Одобрена"), ("rejected", "Отклонена"), ("canceled", "Отменена")], default="pending")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("chat", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="join_requests", to="messenger.chat")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="chat_join_requests", to=settings.AUTH_USER_MODEL)),
                ("invite", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="join_requests", to="messenger.chatinvitelink")),
                ("decided_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="decided_join_requests", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ("created_at", "pk"),
                "constraints": [models.UniqueConstraint(fields=("chat", "user"), name="unique_chat_join_request")],
                "indexes": [models.Index(fields=["chat", "status", "created_at"], name="sg_join_chat_status_idx")],
            },
        ),
    ]
