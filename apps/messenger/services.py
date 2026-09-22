from pathlib import Path

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models import Chat, ChatParticipant, MessageAttachment, PinnedMessage


@transaction.atomic
def get_or_create_direct_chat(first_user, second_user):
    if first_user.pk == second_user.pk:
        direct_key = f"self:{first_user.pk}"
        chat, created = Chat.objects.get_or_create(direct_key=direct_key)
        if created:
            ChatParticipant.objects.create(chat=chat, user=first_user)
        return chat

    low_id, high_id = sorted((first_user.pk, second_user.pk))
    direct_key = f"{low_id}:{high_id}"
    chat, created = Chat.objects.get_or_create(direct_key=direct_key)
    if created:
        ChatParticipant.objects.bulk_create(
            [
                ChatParticipant(chat=chat, user=first_user),
                ChatParticipant(chat=chat, user=second_user),
            ]
        )
    return chat


def other_user_for_chat(chat, current_user):
    return next(
        (participant for participant in chat.participants.all() if participant.pk != current_user.pk),
        current_user,
    )


def mark_chat_read(chat, user, message=None):
    if message is None:
        message = chat.messages.filter(is_deleted=False).order_by("-id").first()
    if message is None:
        return
    ChatParticipant.objects.filter(chat=chat, user=user).update(last_read_message=message)


def touch_chat(chat):
    Chat.objects.filter(pk=chat.pk).update(updated_at=timezone.now())


def attachment_kind(uploaded):
    content_type = (getattr(uploaded, "content_type", "") or "").lower()
    if content_type.startswith("image/"):
        return MessageAttachment.Kind.IMAGE
    if content_type.startswith("video/"):
        return MessageAttachment.Kind.VIDEO
    if content_type.startswith("audio/"):
        return MessageAttachment.Kind.AUDIO
    return MessageAttachment.Kind.FILE


def clone_attachments(source_message, target_message):
    for attachment in source_message.attachments.all():
        attachment.file.open("rb")
        try:
            clone = MessageAttachment(
                message=target_message,
                kind=attachment.kind,
                original_name=attachment.original_name,
                mime_type=attachment.mime_type,
                size=attachment.size,
            )
            clone.file.save(
                Path(attachment.original_name).name or "file",
                attachment.file,
                save=False,
            )
            clone.save()
        finally:
            attachment.file.close()


def delete_message_content(message):
    PinnedMessage.objects.filter(message=message).delete()
    for attachment in list(message.attachments.all()):
        if attachment.file:
            attachment.file.delete(save=False)
        attachment.delete()
    message.text = ""
    message.is_deleted = True
    message.edited_at = None
    message.save(update_fields=("text", "is_deleted", "edited_at", "updated_at"))


def attachment_url(attachment):
    if attachment.kind == MessageAttachment.Kind.FILE:
        return reverse("messenger:download_attachment", args=[attachment.pk])
    return reverse("messenger:view_attachment", args=[attachment.pk])


def serialize_message(message, current_user, other_last_read_id=0, pinned_ids=None):
    pinned_ids = pinned_ids or set()
    reply = message.reply_to
    reply_data = None
    if reply is not None:
        reply_data = {
            "id": reply.pk,
            "sender_name": reply.sender.display_name,
            "preview": reply.preview[:180],
            "is_deleted": reply.is_deleted,
        }

    attachments = []
    if not message.is_deleted:
        attachments = [
            {
                "id": attachment.pk,
                "kind": attachment.kind,
                "name": attachment.original_name,
                "url": attachment_url(attachment),
                "size": attachment.size,
            }
            for attachment in message.attachments.all()
        ]

    is_own = message.sender_id == current_user.pk
    return {
        "id": message.pk,
        "text": "" if message.is_deleted else message.text,
        "sender_id": message.sender_id,
        "sender_name": message.sender.display_name,
        "sender_username": message.sender.username,
        "is_own": is_own,
        "is_deleted": message.is_deleted,
        "is_edited": bool(message.edited_at) and not message.is_deleted,
        "is_read": bool(is_own and message.pk <= other_last_read_id),
        "is_pinned": message.pk in pinned_ids,
        "created_at": message.created_at.isoformat(),
        "updated_at": message.updated_at.isoformat(),
        "time": timezone.localtime(message.created_at).strftime("%H:%M"),
        "reply": reply_data,
        "forwarded": {
            "name": message.forwarded_from_name,
            "username": message.forwarded_from_username,
        } if message.forwarded_from_name else None,
        "attachments": attachments,
        "urls": {
            "edit": reverse("messenger:edit_message", args=[message.chat_id, message.pk]),
            "delete": reverse("messenger:delete_message", args=[message.chat_id, message.pk]),
            "forward": reverse("messenger:forward_message", args=[message.chat_id, message.pk]),
            "pin": reverse("messenger:pin_message", args=[message.chat_id, message.pk]),
        },
    }


def serialize_pins(chat):
    pins = (
        PinnedMessage.objects.filter(chat=chat, message__is_deleted=False)
        .select_related("message", "message__sender")
        .order_by("-pinned_at", "-id")[:8]
    )
    return [
        {
            "id": pin.pk,
            "message_id": pin.message_id,
            "sender_name": pin.message.sender.display_name,
            "preview": pin.message.preview[:180],
        }
        for pin in pins
    ]
