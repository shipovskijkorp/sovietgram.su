from pathlib import Path

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models import Chat, ChatParticipant, Contact, Message, MessageAttachment, PinnedMessage


@transaction.atomic
def get_or_create_direct_chat(first_user, second_user):
    if first_user.pk == second_user.pk:
        direct_key = f"self:{first_user.pk}"
        chat, created = Chat.objects.get_or_create(
            direct_key=direct_key,
            defaults={"type": Chat.Type.PRIVATE},
        )
        if created:
            ChatParticipant.objects.create(
                chat=chat,
                user=first_user,
                role=ChatParticipant.Role.MEMBER,
            )
        return chat

    low_id, high_id = sorted((first_user.pk, second_user.pk))
    direct_key = f"{low_id}:{high_id}"
    chat, created = Chat.objects.get_or_create(
        direct_key=direct_key,
        defaults={"type": Chat.Type.PRIVATE},
    )
    if created:
        ChatParticipant.objects.bulk_create(
            [
                ChatParticipant(
                    chat=chat,
                    user=first_user,
                    role=ChatParticipant.Role.MEMBER,
                ),
                ChatParticipant(
                    chat=chat,
                    user=second_user,
                    role=ChatParticipant.Role.MEMBER,
                ),
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


def apply_archive_rules_on_new_message(chat, message):
    """Mirror Telegram archive behavior for a newly delivered message."""
    sender = message.sender
    had_previous_messages = chat.messages.filter(
        is_deleted=False,
    ).exclude(pk=message.pk).exists()

    memberships = list(
        ChatParticipant.objects.filter(chat=chat)
        .select_related("user")
    )
    for membership in memberships:
        if membership.user_id == sender.pk:
            # Reopening or sending into a locally deleted chat makes it visible
            # again, but still does not pull the sender's own archived chat out.
            if membership.is_hidden:
                ChatParticipant.objects.filter(pk=membership.pk).update(
                    is_hidden=False,
                )
            continue

        if membership.is_hidden:
            ChatParticipant.objects.filter(pk=membership.pk).update(
                is_hidden=False,
            )
            membership.is_hidden = False

        user = membership.user

        # Telegram's "Archive and Mute New Chats from Unknown Users".
        if (
            chat.type == Chat.Type.PRIVATE
            and user.archive_unknown_chats
            and not had_previous_messages
            and not Contact.objects.filter(owner=user, user=sender).exists()
        ):
            ChatParticipant.objects.filter(pk=membership.pk).update(
                is_archived=True,
                is_muted=True,
            )
            continue

        # Muted chats stay archived. Unmuted chats return to the main list on
        # incoming messages unless "Always Keep Archived" is enabled.
        if (
            membership.is_archived
            and not membership.is_muted
            and not user.keep_archived_chats
        ):
            ChatParticipant.objects.filter(pk=membership.pk).update(
                is_archived=False,
            )


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
    message.hidden_for_users.all().delete()
    for attachment in list(message.attachments.all()):
        if attachment.file:
            attachment.file.delete(save=False)
        attachment.delete()
    message.text = ""
    message.special_type = Message.SpecialType.NONE
    message.special_data = {}
    message.is_deleted = True
    message.edited_at = None
    message.save(
        update_fields=(
            "text",
            "special_type",
            "special_data",
            "is_deleted",
            "edited_at",
            "updated_at",
        )
    )


def attachment_url(attachment):
    if attachment.kind == MessageAttachment.Kind.FILE:
        return reverse("messenger:download_attachment", args=[attachment.pk])
    return reverse("messenger:view_attachment", args=[attachment.pk])


def serialize_special_content(message, current_user):
    data = message.special_data or {}
    special_type = message.special_type or ""
    if not special_type:
        return None

    if special_type == Message.SpecialType.POLL:
        options = data.get("options") or []
        selected_indexes = []
        voter_ids = set()
        for index, option in enumerate(options):
            voters = set()
            for value in option.get("voters") or []:
                try:
                    voters.add(int(value))
                except (TypeError, ValueError):
                    continue
            voter_ids.update(voters)
            if current_user.pk in voters:
                selected_indexes.append(index)

        total_voters = max(1, len(voter_ids))
        anonymous = bool(data.get("anonymous", True))
        voter_names = {}
        if not anonymous and voter_ids:
            voter_names = {
                user.pk: user.display_name
                for user in message.chat.participants.filter(pk__in=voter_ids)
            }
        quiz = bool(data.get("quiz"))
        reveal_quiz = bool(selected_indexes) or message.sender_id == current_user.pk
        correct_index = data.get("correct_option")
        serialized_options = []
        for index, option in enumerate(options):
            voters = option.get("voters") or []
            votes = len(voters)
            serialized_options.append(
                {
                    "index": index,
                    "text": str(option.get("text", ""))[:100],
                    "votes": votes,
                    "percent": round((votes / total_voters) * 100) if votes else 0,
                    "selected": index in selected_indexes,
                    "correct": bool(
                        quiz
                        and reveal_quiz
                        and isinstance(correct_index, int)
                        and index == correct_index
                    ),
                    "voter_names": (
                        [
                            voter_names.get(int(user_id), "Пользователь")
                            for user_id in voters
                            if str(user_id).isdigit()
                        ]
                        if not anonymous
                        else []
                    ),
                }
            )
        return {
            "type": "poll",
            "question": str(data.get("question", ""))[:255],
            "anonymous": anonymous,
            "multiple": bool(data.get("multiple", False)) and not quiz,
            "quiz": quiz,
            "closed": bool(data.get("closed", False)),
            "can_close": (
                message.sender_id == current_user.pk
                and not bool(data.get("closed", False))
            ),
            "total_voters": len(voter_ids),
            "selected_indexes": selected_indexes,
            "options": serialized_options,
            "explanation": (
                str(data.get("explanation", ""))[:500]
                if quiz and reveal_quiz
                else ""
            ),
            "action_url": reverse(
                "messenger:special_message_action",
                args=[message.chat_id, message.pk],
            ),
        }

    if special_type == Message.SpecialType.TODO:
        is_author = message.sender_id == current_user.pk
        tasks = []
        for index, task in enumerate(data.get("tasks") or []):
            tasks.append(
                {
                    "index": index,
                    "text": str(task.get("text", ""))[:160],
                    "done": bool(task.get("done", False)),
                }
            )
        return {
            "type": "todo",
            "title": str(data.get("title", ""))[:255],
            "tasks": tasks,
            "allow_others_add": bool(data.get("allow_others_add", False)),
            "allow_others_mark": bool(data.get("allow_others_mark", True)),
            "can_add": is_author or bool(data.get("allow_others_add", False)),
            "can_toggle": is_author or bool(data.get("allow_others_mark", True)),
            "action_url": reverse(
                "messenger:special_message_action",
                args=[message.chat_id, message.pk],
            ),
        }

    if special_type == Message.SpecialType.ARTICLE:
        return {
            "type": "article",
            "title": str(data.get("title", ""))[:200],
            "body": str(data.get("body", ""))[:12000],
        }

    if special_type == Message.SpecialType.LOCATION:
        return {
            "type": "location",
            "label": str(data.get("label", ""))[:120],
            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),
        }

    return None


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
        "signature_name": message.signature_name,
        "special": (
            None
            if message.is_deleted
            else serialize_special_content(message, current_user)
        ),
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
