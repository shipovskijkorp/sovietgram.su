from django.db import transaction
from django.db.models import Case, IntegerField, Value, When

from apps.messenger.models import (
    Chat,
    ChatAdminLog,
    ChatParticipant,
    MessageAttachment,
)


def _delete_stored_file(field):
    if not field:
        return
    name = getattr(field, "name", "") or ""
    storage = getattr(field, "storage", None)
    if name and storage:
        storage.delete(name)


def _delete_chat_with_files(chat):
    attachments = list(
        MessageAttachment.objects.filter(message__chat=chat).only("id", "file")
    )
    for attachment in attachments:
        _delete_stored_file(attachment.file)
    _delete_stored_file(chat.avatar)
    chat.delete()


@transaction.atomic
def delete_user_account(user):
    """
    Delete an account without leaving structurally broken messenger state.

    Private chats cannot exist with a missing peer, so they are removed as a
    whole. Collective chats keep existing members: ownership is transferred to
    an administrator first, then to the oldest remaining member. Empty
    collectives are deleted. Files that Django's cascades do not remove from
    storage are deleted explicitly.
    """
    if not getattr(user, "pk", None):
        return

    # Lock the account row when it still exists. A concurrent cleanup then
    # cannot race ownership transfer and cascade deletion.
    UserModel = type(user)
    locked_user = UserModel.objects.select_for_update().filter(pk=user.pk).first()
    if locked_user is None:
        return
    user = locked_user

    owned = list(
        ChatParticipant.objects.select_for_update()
        .filter(
            user=user,
            role=ChatParticipant.Role.OWNER,
            chat__type__in=(Chat.Type.GROUP, Chat.Type.CHANNEL),
        )
        .select_related("chat")
        .order_by("chat_id")
    )

    for owner_membership in owned:
        chat = owner_membership.chat
        successor = (
            ChatParticipant.objects.select_for_update()
            .filter(chat=chat)
            .exclude(user=user)
            .annotate(
                _owner_rank=Case(
                    When(role=ChatParticipant.Role.ADMIN, then=Value(0)),
                    default=Value(1),
                    output_field=IntegerField(),
                )
            )
            .order_by("_owner_rank", "joined_at", "id")
            .first()
        )
        if successor is None:
            _delete_chat_with_files(chat)
            continue

        successor.role = ChatParticipant.Role.OWNER
        successor.save(update_fields=("role",))
        owner_membership.role = ChatParticipant.Role.MEMBER
        owner_membership.save(update_fields=("role",))
        ChatAdminLog.objects.create(
            chat=chat,
            actor=None,
            target_user=successor.user,
            action="owner_transfer",
            description=(
                f"Права владельца автоматически переданы "
                f"{successor.user.display_name} после удаления прежнего владельца."
            )[:255],
        )

    # A private chat is defined by two concrete accounts (or one account for
    # Saved Messages). Keeping it after one peer is deleted corrupts the
    # direct-chat invariant, so remove the whole chat and its stored media.
    private_chats = list(
        Chat.objects.select_for_update()
        .filter(type=Chat.Type.PRIVATE, memberships__user=user)
        .distinct()
        .order_by("id")
    )
    for chat in private_chats:
        _delete_chat_with_files(chat)

    # Messages in surviving groups/channels are removed by the FK cascade.
    # Delete their files first because FileField storage is not cascade-aware.
    remaining_attachments = list(
        MessageAttachment.objects.filter(message__sender=user).only("id", "file")
    )
    for attachment in remaining_attachments:
        _delete_stored_file(attachment.file)

    _delete_stored_file(user.avatar)
    user.delete()
