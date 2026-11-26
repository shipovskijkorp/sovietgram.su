from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("messenger", "0028_channel_view_statistics")]
    operations = [
        migrations.AddField(model_name="message", name="reply_quote",
                            field=models.CharField(blank=True, default="", max_length=88)),
        migrations.AddField(model_name="scheduledmessage", name="reply_quote",
                            field=models.CharField(blank=True, default="", max_length=88)),
    ]
