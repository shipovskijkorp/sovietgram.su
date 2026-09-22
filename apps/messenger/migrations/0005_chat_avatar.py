from django.db import migrations, models
import apps.messenger.models


class Migration(migrations.Migration):
    dependencies = [
        ("messenger", "0004_chat_metadata"),
    ]

    operations = [
        migrations.AddField(
            model_name="chat",
            name="avatar",
            field=models.ImageField(
                blank=True,
                upload_to=apps.messenger.models.chat_avatar_path,
            ),
        ),
    ]
