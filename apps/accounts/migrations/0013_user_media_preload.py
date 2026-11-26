from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0012_platform_roles")]
    operations = [
        migrations.AddField(
            model_name="user", name="media_preload",
            field=models.BooleanField(default=True, verbose_name="предзагрузка аудио и видео"),
        ),
    ]
