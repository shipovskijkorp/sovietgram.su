from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("messenger", "0008_special_message_attachments"),
    ]

    operations = [
        migrations.AddField(
            model_name="chat",
            name="auto_delete_seconds",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="message",
            name="expires_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
