from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0014_security_events")]
    operations = [
        migrations.AddField(
            model_name="user", name="notification_preferences",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
