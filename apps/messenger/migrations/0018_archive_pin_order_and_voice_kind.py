from django.db import migrations, models


def initialize_pin_order(apps, schema_editor):
    Membership = apps.get_model("messenger", "ChatParticipant")
    db = schema_editor.connection.alias
    rows = Membership.objects.using(db).filter(is_pinned=True).order_by(
        "user_id", "is_archived", "chat__updated_at", "pk",
    ).values_list("pk", "user_id", "is_archived")
    previous = None
    position = 0
    for pk, user_id, archived in rows.iterator():
        key = (user_id, archived)
        if key != previous:
            previous, position = key, 0
        position += 1
        Membership.objects.using(db).filter(pk=pk).update(pin_order=position)


class Migration(migrations.Migration):
    dependencies = [("messenger", "0017_scheduled_messages")]

    operations = [
        migrations.AddField(
            model_name="chatparticipant",
            name="pin_order",
            field=models.PositiveBigIntegerField(default=0),
        ),
        migrations.RunPython(initialize_pin_order, migrations.RunPython.noop),
        # This choice was added with voice messages but its migration was missing.
        migrations.AlterField(
            model_name="messageattachment",
            name="kind",
            field=models.CharField(
                choices=[("image", "Изображение"), ("video", "Видео"), ("audio", "Аудио"),
                         ("voice", "Голосовое сообщение"), ("file", "Файл")],
                default="file", max_length=16,
            ),
        ),
    ]
