from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_user_profile_details"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="keep_archived_chats",
            field=models.BooleanField(
                default=False,
                verbose_name="всегда оставлять чаты в архиве",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="archive_unknown_chats",
            field=models.BooleanField(
                default=False,
                verbose_name="архивировать и отключать уведомления у новых чатов не из контактов",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="archive_in_main_menu",
            field=models.BooleanField(
                default=True,
                verbose_name="показывать архив в главном меню",
            ),
        ),
    ]
