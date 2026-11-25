from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("messenger", "0024_channel_discussions")]
    operations = [
        migrations.AddField(model_name="chat", name="platform_public_restricted", field=models.BooleanField(default=False, editable=False)),
        migrations.AddConstraint(model_name="chat", constraint=models.CheckConstraint(condition=models.Q(platform_public_restricted=False) | models.Q(username__isnull=True), name="sg_chat_public_restriction")),
    ]
