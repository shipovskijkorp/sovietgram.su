from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("messenger", "0003_chat_types_and_roles"),
    ]

    operations = [
        migrations.AddField(
            model_name="chat",
            name="title",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="chat",
            name="username",
            field=models.CharField(blank=True, max_length=64, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="chat",
            name="description",
            field=models.TextField(blank=True, default="", max_length=500),
        ),
    ]
