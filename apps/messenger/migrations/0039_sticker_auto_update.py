from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("messenger", "0038_sticker_catalog")]
    operations = [
        migrations.AddField(
            model_name="stickerpack", name="auto_update_at",
            field=models.DateTimeField(null=True, blank=True, editable=False, db_index=True),
        ),
        migrations.AddField(
            model_name="stickerpack", name="auto_update_error",
            field=models.CharField(max_length=180, blank=True, default="", editable=False),
        ),
    ]
