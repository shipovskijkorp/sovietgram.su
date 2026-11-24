from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0009_account_security_request")]
    operations = [
        migrations.AddField(
            model_name="user",
            name="keep_folder_chats_archived",
            field=models.BooleanField(default=False, verbose_name="оставлять чаты из пользовательских папок в архиве"),
        ),
    ]
