from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("messenger", "0002_chat_features"),
    ]

    operations = [
        migrations.AddField(
            model_name="chat",
            name="type",
            field=models.CharField(
                choices=[
                    ("private", "Личный чат"),
                    ("group", "Группа"),
                    ("channel", "Канал"),
                ],
                db_index=True,
                default="private",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="chatparticipant",
            name="role",
            field=models.CharField(
                choices=[
                    ("owner", "Владелец"),
                    ("admin", "Администратор"),
                    ("member", "Участник"),
                ],
                db_index=True,
                default="member",
                max_length=16,
            ),
        ),
    ]
