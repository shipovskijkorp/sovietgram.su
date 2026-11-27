from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("messenger", "0030_shared_sticker_packs")]

    operations = [
        migrations.RemoveConstraint(
            model_name="messagereaction", name="unique_message_reaction_user",
        ),
        migrations.AddConstraint(
            model_name="messagereaction",
            constraint=models.UniqueConstraint(
                fields=("message", "user", "emoji"), name="sg_unique_message_user_emoji",
            ),
        ),
    ]
