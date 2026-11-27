from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("messenger", "0036_group_media_kinds")]
    operations = [
        migrations.AlterField(
            model_name="messageattachment", name="kind",
            field=models.CharField(max_length=16, default="file", choices=[
                ("image", "Изображение"), ("video", "Видео"), ("video_note", "Видеокружок"),
                ("audio", "Аудио"), ("voice", "Голосовое сообщение"),
                ("sticker", "Стикер"), ("file", "Файл"),
            ]),
        ),
    ]
