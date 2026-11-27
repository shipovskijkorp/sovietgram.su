from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("messenger", "0033_scheduled_stickers")]
    operations = [
        migrations.AddField(model_name="chatparticipant", name="draft_reply_id",
                            field=models.PositiveBigIntegerField(blank=True, null=True)),
        migrations.AddField(model_name="chatparticipant", name="draft_quote",
                            field=models.CharField(blank=True, default="", max_length=88)),
    ]
