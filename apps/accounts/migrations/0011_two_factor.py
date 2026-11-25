from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0010_keep_folder_chats_archived")]
    operations = [
        migrations.AddField(model_name="user", name="security_version", field=models.PositiveBigIntegerField(default=0, editable=False)),
        migrations.AddField(model_name="user", name="two_factor_secret", field=models.TextField(blank=True, default="", editable=False)),
        migrations.AddField(model_name="user", name="two_factor_recovery_hashes", field=models.JSONField(blank=True, default=list, editable=False)),
        migrations.AddField(model_name="user", name="two_factor_last_step", field=models.BigIntegerField(default=-1, editable=False)),
        migrations.AddField(model_name="user", name="two_factor_failures", field=models.PositiveSmallIntegerField(default=0, editable=False)),
        migrations.AddField(model_name="user", name="two_factor_failure_window", field=models.DateTimeField(blank=True, null=True, editable=False)),
    ]
