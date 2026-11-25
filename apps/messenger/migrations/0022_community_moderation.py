from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("messenger", "0021_sticker_collections_join_requests"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.AddField(model_name="chatparticipant", name="admin_permissions",
                            field=models.JSONField(blank=True, default=None, null=True)),
        migrations.CreateModel(
            name="ChatMemberModeration",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("banned", models.BooleanField(default=False)),
                ("denied_permissions", models.JSONField(blank=True, default=list)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("reason", models.CharField(blank=True, default="", max_length=200)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="community_moderation_actions", to=settings.AUTH_USER_MODEL)),
                ("chat", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="member_moderation", to="messenger.chat")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="community_moderation", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ("-updated_at", "-pk"),
                "constraints": [models.UniqueConstraint(fields=("chat", "user"), name="unique_chat_member_moderation")],
                "indexes": [models.Index(fields=["chat", "banned", "expires_at"], name="sg_chat_moderation_idx")],
            },
        ),
    ]
