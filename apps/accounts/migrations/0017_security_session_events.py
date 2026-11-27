from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0016_avatar_history")]
    operations = [
        migrations.AlterField(
            model_name="securityevent", name="kind",
            field=models.CharField(max_length=20, choices=[
                ("login", "Вход в аккаунт"), ("password", "Изменение пароля"),
                ("password_reset", "Восстановление пароля"), ("email_change", "Изменение почты"),
                ("factor_enable", "Включение двухфакторной защиты"),
                ("factor_disable", "Отключение двухфакторной защиты"),
                ("factor_codes", "Обновление резервных кодов"),
                ("session_revoke", "Завершение другого сеанса"),
                ("sessions_revoke", "Завершение остальных сеансов"),
            ]),
        ),
    ]
