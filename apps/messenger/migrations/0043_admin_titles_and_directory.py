import unicodedata

from django.db import migrations, models


def populate_search_keys(apps, schema_editor):
    Chat = apps.get_model("messenger", "Chat")
    alias = schema_editor.connection.alias
    pending = []
    for chat in Chat.objects.using(alias).all().iterator(chunk_size=200):
        value = " ".join(str(part or "") for part in (chat.title, chat.username, chat.description))
        chat.directory_search_key = unicodedata.normalize("NFKC", value).casefold()
        pending.append(chat)
        if len(pending) >= 200:
            Chat.objects.using(alias).bulk_update(pending, ["directory_search_key"], batch_size=200)
            pending.clear()
    if pending:
        Chat.objects.using(alias).bulk_update(pending, ["directory_search_key"], batch_size=200)


class Migration(migrations.Migration):
    dependencies = [("messenger", "0042_saved_gifs")]
    operations = [
        migrations.AddField(model_name="chat", name="directory_search_key", field=models.TextField(blank=True, default="", editable=False)),
        migrations.AddField(model_name="chatparticipant", name="admin_title", field=models.CharField(max_length=32, blank=True, default="")),
        migrations.AddField(model_name="message", name="sender_title", field=models.CharField(max_length=32, blank=True, default="", editable=False)),
        migrations.AddConstraint(model_name="chatparticipant", constraint=models.CheckConstraint(
            condition=models.Q(role__in=("owner", "admin")) | models.Q(admin_title=""), name="sg_admin_title_role")),
        migrations.RunPython(populate_search_keys, migrations.RunPython.noop),
    ]
