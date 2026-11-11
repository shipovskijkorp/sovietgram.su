from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0007_privacy_settings"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="email_verified_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="подтверждение электронной почты",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="email_verification_sent_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="дата отправки подтверждения",
            ),
        ),
    ]
