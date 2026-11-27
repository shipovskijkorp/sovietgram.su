from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("messenger", "0039_sticker_auto_update")]
    operations = [
        migrations.AddField(model_name="messageattachment", name="is_spoiler",
                            field=models.BooleanField(default=False)),
    ]
