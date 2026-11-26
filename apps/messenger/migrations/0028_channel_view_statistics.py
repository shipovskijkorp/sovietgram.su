from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [("messenger", "0027_channel_post_views")]
    operations = [
        # Keep the true timestamp unknown for pre-existing view records.
        migrations.AddField(model_name="channelpostview", name="viewed_at",
                            field=models.DateTimeField(null=True, blank=True)),
        migrations.AlterField(model_name="channelpostview", name="viewed_at",
                              field=models.DateTimeField(default=django.utils.timezone.now, null=True, blank=True)),
        migrations.AddIndex(model_name="channelpostview",
                            index=models.Index(fields=["post", "viewed_at"], name="sg_post_view_date_idx")),
    ]
