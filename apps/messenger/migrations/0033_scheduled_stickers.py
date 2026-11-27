from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("messenger", "0032_scheduled_special_messages")]
    operations = [
        migrations.AddField(
            model_name="scheduledmessage", name="sticker_source_id",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="scheduledmessage", name="sticker_image",
            field=models.BinaryField(blank=True, default=bytes),
        ),
    ]
