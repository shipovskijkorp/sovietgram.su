from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("messenger", "0022_community_moderation")]
    operations = [
        migrations.AddField(
            model_name="chat",
            name="allowed_reactions",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
    ]
