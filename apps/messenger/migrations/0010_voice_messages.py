from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("messenger", "0009_auto_delete_messages"),
    ]

    operations = [
        migrations.AddField(
            model_name="messageattachment",
            name="duration_ms",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="messageattachment",
            name="waveform",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.CreateModel(
            name="VoiceMessagePlayback",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("played_at", models.DateTimeField(auto_now_add=True)),
                (
                    "attachment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="voice_playbacks",
                        to="messenger.messageattachment",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="voice_message_playbacks",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ("-played_at", "-id")},
        ),
        migrations.AddConstraint(
            model_name="voicemessageplayback",
            constraint=models.UniqueConstraint(
                fields=("attachment", "user"),
                name="unique_voice_playback_per_user",
            ),
        ),
    ]
