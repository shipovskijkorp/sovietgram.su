"""Shared folder matching semantics for sidebar, search and archive delivery."""
from django.http import Http404

from .models import Chat, ChatFolder, Contact

CATEGORIES = ("contacts", "noncontacts", "groups", "channels", "saved")
MAX_FOLDERS = 20
MAX_CHATS = 200


def requested_folder(user, raw):
    if raw in (None, ""):
        return None
    try:
        pk = int(raw)
        if not 0 < pk <= 9223372036854775807:
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        raise Http404 from None
    folder = ChatFolder.objects.filter(owner=user, pk=pk).first()
    if folder is None:
        raise Http404
    return folder


def category_for_chat(chat, user_id, contact_ids):
    if chat.type == Chat.Type.GROUP:
        return "groups"
    if chat.type == Chat.Type.CHANNEL:
        return "channels"
    if chat.direct_key == f"self:{user_id}":
        return "saved"
    # Use the existing prefetch cache for decorated sidebar chats.
    peer = next((item for item in chat.participants.all() if item.pk != user_id), None)
    return "contacts" if peer and peer.pk in contact_ids else "noncontacts"


def matches_folder(folder, chat_id, category, archived, muted, unread):
    # Explicit exclusions win; explicit inclusions override automatic filters.
    if chat_id in folder.excluded_chat_ids:
        return False
    if chat_id in folder.included_chat_ids:
        return True
    return (
        category in folder.categories
        and not (folder.exclude_archived and archived)
        and not (folder.exclude_muted and muted)
        and not (folder.exclude_read and not unread)
    )


def decorate_folder_categories(chats, user):
    contact_ids = set(Contact.objects.filter(owner=user).values_list("user_id", flat=True))
    for chat in chats:
        chat.folder_category_ui = category_for_chat(chat, user.pk, contact_ids)


def matching_chats(folder, chats):
    return [
        chat for chat in chats if matches_folder(
            folder, chat.pk, chat.folder_category_ui, chat.is_archived_ui,
            chat.is_muted_ui, chat.has_unread_ui,
        )
    ]


def keep_in_archive_for_folder(membership):
    user = membership.user
    if not user.keep_folder_chats_archived:
        return False
    folders = list(ChatFolder.objects.filter(owner=user))
    if not folders:
        return False
    contact_ids = set(Contact.objects.filter(owner=user).values_list("user_id", flat=True))
    category = category_for_chat(membership.chat, user.pk, contact_ids)
    # Called for newly delivered incoming messages. The chat is unread now.
    return any(matches_folder(
        folder, membership.chat_id, category, True, membership.notifications_muted, True,
    ) for folder in folders)
