from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("messenger", "0018_archive_pin_order_and_voice_kind"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="ChatFolder",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=32)),
                ("position", models.PositiveIntegerField(default=0)),
                ("revision", models.PositiveBigIntegerField(default=1)),
                ("categories", models.JSONField(blank=True, default=list)),
                ("included_chat_ids", models.JSONField(blank=True, default=list)),
                ("excluded_chat_ids", models.JSONField(blank=True, default=list)),
                ("pinned_chat_ids", models.JSONField(blank=True, default=list)),
                ("exclude_muted", models.BooleanField(default=False)),
                ("exclude_read", models.BooleanField(default=False)),
                ("exclude_archived", models.BooleanField(default=False)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="chat_folders", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ("position", "pk"),
                "indexes": [models.Index(fields=["owner", "position"], name="sg_folder_owner_pos")],
            },
        ),
    ]
