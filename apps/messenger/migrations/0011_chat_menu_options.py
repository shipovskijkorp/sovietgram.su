from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("messenger", "0010_voice_messages"),
    ]

    operations = [
        migrations.AddField(
            model_name="chat",
            name="protect_content",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="chatparticipant",
            name="wallpaper",
            field=models.CharField(blank=True, default="", max_length=16),
        ),
    ]
