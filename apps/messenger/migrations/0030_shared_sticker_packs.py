from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("messenger", "0029_reply_quotes")]
    operations = [
        migrations.AddField(model_name="stickerpack", name="share_token",
                            field=models.UUIDField(blank=True, editable=False, null=True, unique=True)),
        migrations.AddField(model_name="stickerpack", name="source_pack_id",
                            field=models.PositiveBigIntegerField(blank=True, editable=False, null=True)),
        migrations.AddConstraint(model_name="stickerpack",
                                 constraint=models.UniqueConstraint(fields=("owner", "source_pack_id"),
                                                                    name="sg_one_imported_sticker_pack")),
    ]
