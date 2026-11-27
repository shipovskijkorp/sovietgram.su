from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("messenger", "0037_video_notes")]
    operations = [
        migrations.AddField(
            model_name="stickerpack", name="catalog_published_at",
            field=models.DateTimeField(null=True, blank=True, db_index=True, editable=False),
        ),
        migrations.AlterField(
            model_name="stickerpack", name="source_pack_id",
            field=models.PositiveBigIntegerField(null=True, blank=True, editable=False, db_index=True),
        ),
    ]
