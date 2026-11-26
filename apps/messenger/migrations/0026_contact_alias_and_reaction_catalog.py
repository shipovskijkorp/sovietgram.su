from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("messenger", "0025_platform_public_restriction")]
    operations = [
        migrations.AddField(model_name="contact", name="alias",
                            field=models.CharField(blank=True, default="", max_length=100)),
        migrations.AlterField(model_name="messagereaction", name="emoji",
                              field=models.CharField(max_length=8, choices=[("👍", "Нравится"), ("❤️", "Любовь"), ("🔥", "Огонь"), ("😂", "Смешно"), ("😮", "Удивление"), ("👎", "Не нравится"), ("🎉", "Праздник"), ("👏", "Аплодисменты"), ("🤔", "Задумался"), ("😢", "Грустно"), ("😡", "Злость"), ("😍", "Восхищение"), ("😉", "Подмигивание"), ("😎", "Круто"), ("🫡", "Салют"), ("👌", "Отлично"), ("💯", "Сто процентов"), ("🙏", "Спасибо"), ("💀", "Череп"), ("🤡", "Клоун"), ("🤦", "Фейспалм"), ("🍿", "Попкорн"), ("🚀", "Ракета"), ("✅", "Согласен")])),
    ]
