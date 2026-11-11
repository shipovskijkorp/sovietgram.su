from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("messenger", "0012_remove_chatparticipant_wallpaper"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatparticipant",
            name="muted_until",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
