from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("messenger", "0035_sticker_source_capability")]
    operations = [
        migrations.AddField(model_name="chat", name="members_allowed_media",
                            field=models.JSONField(blank=True, null=True, default=None)),
    ]
