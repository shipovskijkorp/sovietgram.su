from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("accounts", "0013_user_media_preload")]
    operations = [
        migrations.AddField(
            model_name="user", name="last_login_alert_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.CreateModel(
            name="SecurityEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(max_length=20, choices=[
                    ("login", "Вход в аккаунт"), ("password", "Изменение пароля"),
                    ("password_reset", "Восстановление пароля"), ("email_change", "Изменение почты"),
                    ("factor_enable", "Включение двухфакторной защиты"),
                    ("factor_disable", "Отключение двухфакторной защиты"),
                    ("factor_codes", "Обновление резервных кодов"),
                ])),
                ("device", models.CharField(blank=True, default="", max_length=240)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name="security_events", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-id",), "indexes": [models.Index(fields=["user", "-id"], name="sg_security_user_idx")]},
        ),
    ]
