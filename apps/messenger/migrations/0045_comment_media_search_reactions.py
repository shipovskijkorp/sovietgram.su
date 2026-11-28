import unicodedata

import apps.messenger.models
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def populate_search_keys(apps, schema_editor):
    Comment = apps.get_model("messenger", "ChannelComment")
    alias = schema_editor.connection.alias
    batch = []
    for comment in Comment.objects.using(alias).filter(is_deleted=False).iterator(chunk_size=200):
        comment.search_key = unicodedata.normalize("NFKC", comment.text).casefold()
        batch.append(comment)
        if len(batch) == 200:
            Comment.objects.using(alias).bulk_update(batch, ["search_key"], batch_size=200)
            batch.clear()
    if batch:
        Comment.objects.using(alias).bulk_update(batch, ["search_key"], batch_size=200)


class Migration(migrations.Migration):
    dependencies = [
        ("messenger", "0044_community_membership_events"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.AlterField(model_name="channelcomment", name="text", field=models.TextField(blank=True, max_length=4096)),
        migrations.AddField(model_name="channelcomment", name="request_digest", field=models.CharField(blank=True, default="", editable=False, max_length=64)),
        migrations.AddField(model_name="channelcomment", name="search_key", field=models.TextField(blank=True, default="", editable=False)),
        migrations.CreateModel(
            name="ChannelCommentReaction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("emoji", models.CharField(max_length=8, choices=[
                    ("👍", "Нравится"),
                    ("❤️", "Любовь"),
                    ("🔥", "Огонь"),
                    ("😂", "Смешно"),
                    ("😮", "Удивление"),
                    ("👎", "Не нравится"),
                    ("🎉", "Праздник"),
                    ("👏", "Аплодисменты"),
                    ("🤔", "Задумался"),
                    ("😢", "Грустно"),
                    ("😡", "Злость"),
                    ("😍", "Восхищение"),
                    ("😉", "Подмигивание"),
                    ("😎", "Круто"),
                    ("🫡", "Салют"),
                    ("👌", "Отлично"),
                    ("💯", "Сто процентов"),
                    ("🙏", "Спасибо"),
                    ("💀", "Череп"),
                    ("🤡", "Клоун"),
                    ("🤦", "Фейспалм"),
                    ("🍿", "Попкорн"),
                    ("🚀", "Ракета"),
                    ("✅", "Согласен"),
                ])),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("comment", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="reactions", to="messenger.channelcomment")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="comment_reactions", to=settings.AUTH_USER_MODEL)),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("comment", "user", "emoji"), name="sg_comment_user_emoji")]},
        ),
        migrations.CreateModel(
            name="ChannelCommentAttachment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("file", models.FileField(upload_to=apps.messenger.models.comment_attachment_path)),
                ("kind", models.CharField(max_length=16, choices=[("image", "Изображение"), ("video", "Видео")])),
                ("original_name", models.CharField(max_length=255)),
                ("mime_type", models.CharField(max_length=127)),
                ("size", models.PositiveBigIntegerField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("comment", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="attachments", to="messenger.channelcomment")),
            ],
            options={"ordering": ("pk",)},
        ),
        migrations.RunPython(populate_search_keys, migrations.RunPython.noop),
    ]
