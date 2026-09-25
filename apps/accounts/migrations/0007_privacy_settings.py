from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0006_user_archive_preferences"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="privacy_settings",
            field=models.JSONField(blank=True, default=dict, verbose_name="настройки конфиденциальности"),
        ),
        migrations.AddField(
            model_name="user",
            name="default_auto_delete_seconds",
            field=models.PositiveIntegerField(default=0, verbose_name="автоудаление сообщений по умолчанию"),
        ),
        migrations.AddField(
            model_name="user",
            name="delete_after_inactive_days",
            field=models.PositiveSmallIntegerField(default=365, verbose_name="удаление аккаунта после неактивности"),
        ),
        migrations.CreateModel(
            name="UserBlock",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "blocked",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="blocked_by_links",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "blocker",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="blocked_user_links",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ("-created_at", "-id")},
        ),
        migrations.AddConstraint(
            model_name="userblock",
            constraint=models.UniqueConstraint(
                fields=("blocker", "blocked"),
                name="unique_user_block",
            ),
        ),
    ]
