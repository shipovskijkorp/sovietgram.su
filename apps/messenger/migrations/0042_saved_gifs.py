import apps.messenger.models
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("messenger", "0041_scheduled_attachments"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="SavedGif",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("file", models.FileField(upload_to=apps.messenger.models.saved_gif_path)),
                ("digest", models.CharField(editable=False, max_length=64)),
                ("size", models.PositiveBigIntegerField(default=0, editable=False)),
                ("name", models.CharField(max_length=80)),
                ("tags", models.CharField(blank=True, default="", max_length=160)),
                ("search_key", models.CharField(default="", editable=False, max_length=512)),
                ("favorite", models.BooleanField(default=False)),
                ("can_publish", models.BooleanField(default=False, editable=False)),
                ("published_at", models.DateTimeField(blank=True, db_index=True, editable=False, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name="saved_gifs", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-created_at", "-pk")},
        ),
        migrations.AddConstraint(
            model_name="savedgif",
            constraint=models.UniqueConstraint(fields=("owner", "digest"), name="sg_gif_owner_digest"),
        ),
    ]
