"""Remove private queued files only after the database commits their deletion."""
from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import MessageAttachment, ScheduledAttachment


@receiver(post_delete, sender=ScheduledAttachment, dispatch_uid="sovietgram.scheduled_file_cleanup")
def cleanup_scheduled_file(sender, instance, using, **kwargs):
    name = instance.file.name
    if not name:
        return
    storage = instance.file.storage

    def cleanup():
        # Delivery atomically transfers the same immutable path to a message.
        if (not MessageAttachment.objects.using(using).filter(file=name).exists()
                and not ScheduledAttachment.objects.using(using).filter(file=name).exists()):
            storage.delete(name)

    transaction.on_commit(cleanup, using=using, robust=True)
