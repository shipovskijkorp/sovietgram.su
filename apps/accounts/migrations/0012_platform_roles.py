from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0011_two_factor")]
    operations = [
        migrations.AddField(model_name="user", name="platform_role", field=models.CharField(max_length=12, choices=[("", "Пользователь"), ("moderator", "Модератор"), ("admin", "Администратор"), ("owner", "Владелец платформы")], blank=True, default="", editable=False, db_index=True)),
        migrations.AddField(model_name="user", name="platform_suspended_at", field=models.DateTimeField(null=True, blank=True, editable=False, db_index=True)),
        migrations.AddField(model_name="user", name="platform_suspension_reason", field=models.CharField(max_length=300, blank=True, default="", editable=False)),
    ]
