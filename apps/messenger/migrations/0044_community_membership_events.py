import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("messenger", "0043_admin_titles_and_directory")]
    operations = [
        migrations.CreateModel(
            name="CommunityMembershipEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source", models.CharField(max_length=20, choices=[
                    ("created", "Создание сообщества"),
                    ("initial_add", "Добавление при создании"),
                    ("manual_add", "Добавление администратором"),
                    ("public", "Публичный адрес"),
                    ("directory", "Каталог сообществ"),
                    ("invite", "Ссылка-приглашение"),
                    ("approval", "Одобренная заявка"),
                    ("leave", "Самостоятельный выход"),
                    ("removed", "Удаление участника"),
                    ("banned", "Блокировка"),
                    ("account_deleted", "Удаление аккаунта"),
                ])),
                ("invite_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("count", models.PositiveIntegerField(default=1)),
                ("occurred_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("chat", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name="membership_events", to="messenger.chat")),
            ],
            options={
                "indexes": [models.Index(fields=["chat", "occurred_at"], name="sg_member_event_chat_time")],
                "constraints": [models.CheckConstraint(condition=models.Q(count__gt=0), name="sg_member_event_positive")],
            },
        ),
    ]
