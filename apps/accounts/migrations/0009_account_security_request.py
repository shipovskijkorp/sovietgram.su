from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0008_email_verification"),
    ]

    operations = [
        migrations.CreateModel(
            name="AccountSecurityRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("purpose", models.CharField(choices=[("password_reset", "Восстановление пароля"), ("email_change", "Изменение почты")], max_length=20)),
                ("token_digest", models.CharField(blank=True, max_length=64, null=True, unique=True)),
                ("email", models.EmailField(max_length=254)),
                ("account_state", models.CharField(max_length=64)),
                ("issued_at", models.DateTimeField()),
                ("expires_at", models.DateTimeField()),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="security_requests", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("user", "purpose"), name="unique_account_security_purpose"),
                ],
            },
        ),
    ]
