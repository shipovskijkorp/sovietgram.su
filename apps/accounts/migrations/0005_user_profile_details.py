from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_user_last_seen_at"),
        ("messenger", "0005_chat_avatar"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="birthday",
            field=models.DateField(blank=True, null=True, verbose_name="день рождения"),
        ),
        migrations.AddField(
            model_name="user",
            name="personal_channel",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="profile_owners",
                to="messenger.chat",
                verbose_name="личный канал",
            ),
        ),
    ]
