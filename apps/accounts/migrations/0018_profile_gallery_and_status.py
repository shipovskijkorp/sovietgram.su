from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0017_security_session_events")]
    operations = [
        migrations.AddField(model_name="avatarhistory", name="is_shared", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="user", name="emoji_status", field=models.CharField(blank=True, default="", max_length=16)),
        migrations.AddField(model_name="user", name="emoji_status_until", field=models.DateTimeField(blank=True, null=True)),
    ]
