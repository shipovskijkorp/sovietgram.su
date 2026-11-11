from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("messenger", "0011_chat_menu_options"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="chatparticipant",
            name="wallpaper",
        ),
    ]
