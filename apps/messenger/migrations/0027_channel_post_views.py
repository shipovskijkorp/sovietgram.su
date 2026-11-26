from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("messenger", "0026_contact_alias_and_reaction_catalog"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="ChannelPostView",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("post", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="channel_views", to="messenger.message")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="channel_post_views", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "constraints": [models.UniqueConstraint(fields=("post", "user"), name="sg_channel_post_view_once")],
            },
        ),
    ]
