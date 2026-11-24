from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("messenger", "0014_read_cursor_send_receipt"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatparticipant",
            name="marked_unread_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
