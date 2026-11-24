from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("messenger", "0015_chatparticipant_marked_unread_at"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="message",
            name="reaction_version",
            field=models.PositiveBigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="message",
            name="reaction_changed_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.CreateModel(
            name="MessageReaction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("emoji", models.CharField(choices=[("👍", "Нравится"), ("❤️", "Любовь"), ("🔥", "Огонь"), ("😂", "Смешно"), ("😮", "Удивление"), ("👎", "Не нравится")], max_length=8)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("message", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="reactions", to="messenger.message")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="message_reactions", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("message", "user"), name="unique_message_reaction_user"),
                ],
            },
        ),
    ]
