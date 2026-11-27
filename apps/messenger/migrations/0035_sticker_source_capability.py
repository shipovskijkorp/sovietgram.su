from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("messenger", "0034_draft_reply_quote")]
    operations = [
        migrations.AddField(model_name="stickerpack", name="source_share_token",
                            field=models.UUIDField(blank=True, editable=False, null=True)),
    ]
