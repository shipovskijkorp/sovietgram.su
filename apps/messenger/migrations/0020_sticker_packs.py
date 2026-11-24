from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("messenger", "0019_chat_folders"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.AlterField(
            model_name="messageattachment", name="kind",
            field=models.CharField(choices=[("image", "Изображение"), ("video", "Видео"), ("audio", "Аудио"),
                ("voice", "Голосовое сообщение"), ("sticker", "Стикер"), ("file", "Файл")], default="file", max_length=16),
        ),
        migrations.CreateModel(
            name="StickerPack",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=48)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="sticker_packs", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("id",)},
        ),
        migrations.CreateModel(
            name="Sticker",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("emoji", models.CharField(blank=True, default="", max_length=24)),
                ("image", models.BinaryField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("pack", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="stickers", to="messenger.stickerpack")),
            ],
            options={"ordering": ("id",)},
        ),
    ]
