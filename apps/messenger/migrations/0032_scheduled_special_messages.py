from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("messenger", "0031_multiple_message_reactions")]
    operations = [
        migrations.AddField(
            model_name="scheduledmessage", name="special_type",
            field=models.CharField(max_length=16, blank=True, default="", choices=[
                ("", "Обычное сообщение"), ("poll", "Опрос"), ("todo", "Список задач"),
                ("article", "Статья"), ("location", "Геопозиция"),
            ]),
        ),
        migrations.AddField(
            model_name="scheduledmessage", name="special_data",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
