from django.conf import settings
from django.db import migrations, models
from django.db.models import F
import django.db.models.deletion


def seed_read_cursor(apps, schema_editor):
    Membership = apps.get_model("messenger", "ChatParticipant")
    Membership.objects.using(schema_editor.connection.alias).filter(
        last_read_message__isnull=False,
    ).update(read_through_id=F("last_read_message_id"))


class Migration(migrations.Migration):
    dependencies = [
        ("messenger", "0013_chatparticipant_muted_until"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="chatparticipant",
            name="read_through_id",
            field=models.PositiveBigIntegerField(default=0),
        ),
        migrations.RunPython(seed_read_cursor, migrations.RunPython.noop),
        migrations.CreateModel(
            name="MessageSendReceipt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("client_id", models.UUIDField()),
                ("request_digest", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("sender", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="message_send_receipts", to=settings.AUTH_USER_MODEL)),
                ("message", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="send_receipts", to="messenger.message")),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("sender", "client_id"), name="unique_message_send_receipt"),
                ],
            },
        ),
    ]
