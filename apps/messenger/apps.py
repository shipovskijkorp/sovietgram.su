from django.apps import AppConfig


class MessengerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.messenger"
    verbose_name = "Мессенджер"

    def ready(self):
        from . import scheduled_storage  # noqa: F401
