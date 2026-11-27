from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("accounts", "0015_notification_preferences")]
    operations = [
        migrations.CreateModel(
            name="AvatarHistory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("image", models.ImageField(upload_to="avatars/%Y/%m/")),
                ("archived_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name="avatar_history", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-id",), "constraints": [
                models.UniqueConstraint(fields=["user", "image"], name="sg_unique_avatar_history"),
            ]},
        ),
    ]
