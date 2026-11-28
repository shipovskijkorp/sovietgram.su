"""Remove unique comment media files only after successful database deletion."""
from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import ChannelCommentAttachment


@receiver(post_delete, sender=ChannelCommentAttachment, dispatch_uid="sovietgram.comment_file_cleanup")
def cleanup_comment_file(sender, instance, using, **kwargs):
    if instance.file:
        name, storage = instance.file.name, instance.file.storage
        transaction.on_commit(lambda: storage.delete(name), using=using, robust=True)
