import apps.messenger.models
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("messenger", "0040_media_spoilers")]
    operations = [
        migrations.CreateModel(
            name="ScheduledAttachment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("file", models.FileField(upload_to=apps.messenger.models.scheduled_attachment_path)),
                ("kind", models.CharField(choices=[("image", "Изображение"), ("video", "Видео"),
                    ("video_note", "Видеокружок"), ("audio", "Аудио"), ("voice", "Голосовое сообщение"),
                    ("sticker", "Стикер"), ("file", "Файл")], default="file", max_length=16)),
                ("original_name", models.CharField(max_length=255)),
                ("mime_type", models.CharField(blank=True, max_length=127)),
                ("size", models.PositiveBigIntegerField(default=0)),
                ("duration_ms", models.PositiveIntegerField(default=0)),
                ("waveform", models.JSONField(blank=True, default=list)),
                ("is_spoiler", models.BooleanField(default=False)),
                ("scheduled", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name="attachments", to="messenger.scheduledmessage")),
            ],
            options={"ordering": ("pk",)},
        ),
    ]
