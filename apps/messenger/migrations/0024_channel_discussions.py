from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("messenger", "0023_chat_allowed_reactions"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.AddField(model_name="chat", name="comments_enabled", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="message", name="comments_closed", field=models.BooleanField(default=False)),
        migrations.CreateModel(
            name="ChannelComment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("client_id", models.UUIDField()),
                ("text", models.TextField(max_length=4096)),
                ("is_deleted", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("edited_at", models.DateTimeField(blank=True, null=True)),
                ("author", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="channel_comments", to=settings.AUTH_USER_MODEL)),
                ("post", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="channel_comments", to="messenger.message")),
                ("reply_to", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="replies", to="messenger.channelcomment")),
            ],
            options={
                "ordering": ("id",),
                "constraints": [models.UniqueConstraint(fields=("post", "author", "client_id"), name="sg_comment_send_once")],
                "indexes": [models.Index(fields=["post", "is_deleted", "id"], name="sg_comment_post_visible_idx")],
            },
        ),
    ]
