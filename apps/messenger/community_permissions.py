"""Server-side community permissions shared by all posting and join paths."""
from django.db.models import Q
from django.utils import timezone

from .models import Chat, ChatMemberModeration, ChatParticipant

ADMIN_RIGHTS = {
    "change_info": "Изменение информации и адреса",
    "manage_permissions": "Общие разрешения участников",
    "invite_users": "Приглашения и заявки",
    "moderate_members": "Удаление, блокировка и ограничения участников",
    "delete_messages": "Удаление чужих сообщений",
    "pin_messages": "Закрепление сообщений",
    "post_messages": "Публикация в канале / отправка вне общих ограничений группы",
    "edit_messages": "Редактирование чужих статей и завершение опросов",
}
MEMBER_DENIALS = {
    "send_text": "Отправка текста и структурированных сообщений",
    "send_media": "Отправка медиа, файлов и стикеров",
    "send_links": "Отправка ссылок",
    "add_members": "Добавление участников",
    "pin_messages": "Закрепление сообщений",
}
DURATIONS = {"1h": 3600, "8h": 28800, "1d": 86400, "7d": 604800, "30d": 2592000, "forever": None}


def admin_rights(membership):
    if membership is None or membership.is_hidden:
        return []
    if membership.role == ChatParticipant.Role.OWNER:
        return list(ADMIN_RIGHTS)
    if membership.role != ChatParticipant.Role.ADMIN:
        return []
    configured = membership.admin_permissions
    if configured is None:
        return list(ADMIN_RIGHTS)
    if not isinstance(configured, list):
        return []
    return [right for right in ADMIN_RIGHTS if right in configured]


def has_admin_right(membership, right):
    return right in admin_rights(membership)


def active_sanctions(chat):
    return ChatMemberModeration.objects.filter(chat=chat).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
    )


def is_banned(chat, user_id):
    return active_sanctions(chat).filter(user_id=user_id, banned=True).exists()


def member_denials(chat, membership):
    if chat.type == Chat.Type.PRIVATE or membership.role != ChatParticipant.Role.MEMBER:
        return set()
    row = active_sanctions(chat).filter(user_id=membership.user_id).first()
    if row is None:
        return set()
    if row.banned:
        return set(MEMBER_DENIALS)
    return set(MEMBER_DENIALS).intersection(row.denied_permissions or [])


def can_add_members(chat, membership):
    if membership.role != ChatParticipant.Role.MEMBER:
        return has_admin_right(membership, "invite_users")
    return chat.type == Chat.Type.GROUP and chat.members_can_add_members and "add_members" not in member_denials(chat, membership)


def can_pin_messages(chat, membership):
    if chat.type == Chat.Type.PRIVATE:
        return True
    if membership.role != ChatParticipant.Role.MEMBER:
        return has_admin_right(membership, "pin_messages")
    return chat.type == Chat.Type.GROUP and chat.members_can_pin_messages and "pin_messages" not in member_denials(chat, membership)


def can_moderate(actor, target):
    return (
        target is not None and target.user_id != actor.user_id
        and target.role != ChatParticipant.Role.OWNER
        and has_admin_right(actor, "moderate_members")
        and (actor.role == ChatParticipant.Role.OWNER or target.role == ChatParticipant.Role.MEMBER)
    )
