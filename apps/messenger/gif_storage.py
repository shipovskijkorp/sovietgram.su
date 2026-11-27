"""Unique immutable GIF paths can be deleted after database commit."""
from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import SavedGif


@receiver(post_delete, sender=SavedGif, dispatch_uid="sovietgram.saved_gif_cleanup")
def cleanup_saved_gif(sender, instance, using, **kwargs):
    if instance.file:
        name, storage = instance.file.name, instance.file.storage
        transaction.on_commit(lambda: storage.delete(name), using=using, robust=True)
