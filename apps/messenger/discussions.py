"""Channel discussions: separate from channel publishing and from group history."""
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .community_permissions import has_admin_right, is_banned, member_denials
from .models import Chat, ChatParticipant, ChannelComment, Message, MessageHiddenForUser
from .ratelimit import rate_limit

PAGE = 40
MAX_ID = 9223372036854775807


def error(text, status=400):
    return JsonResponse({"ok": False, "error": text}, status=status)


def integer(value, *, zero=False):
    try:
        result = int(value)
        if not (0 if zero else 1) <= result <= MAX_ID:
            raise ValueError
        return result
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Некорректный идентификатор.") from None


def thread(request, chat_id, message_id, *, lock=False):
    # All writes lock the channel, then the membership, then the publication.
    chats = Chat.objects.select_for_update() if lock else Chat.objects.all()
    chat = get_object_or_404(chats, pk=chat_id, type=Chat.Type.CHANNEL)
    memberships = ChatParticipant.objects.select_for_update() if lock else ChatParticipant.objects.all()
    member = get_object_or_404(memberships, chat=chat, user=request.user, is_hidden=False)
    if not chat.comments_enabled or is_banned(chat, request.user.pk):
        raise Http404
    query = Message.objects.select_for_update() if lock else Message.objects.all()
    query = query.filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()),
        chat=chat, is_deleted=False, pk__gt=member.cleared_before_message_id,
    ).exclude(hidden_for_users__user=request.user)
    if not chat.history_visible_to_new_members and not member.can_see_pre_join_history:
        query = query.filter(created_at__gte=member.joined_at)
    post = get_object_or_404(query, pk=message_id)
    return chat, member, post


def can_write(chat, member, post):
    return not post.comments_closed and "comment" not in member_denials(chat, member)


def serialize(comment, member, writable):
    own = comment.author_id == member.user_id
    reply = comment.reply_to
    return {
        "id": comment.pk, "text": comment.text,
        "author": comment.author.display_name, "username": comment.author.username,
        "own": own, "can_edit": own and writable,
        "can_delete": own or has_admin_right(member, "delete_messages"),
        "time": timezone.localtime(comment.created_at).strftime("%d.%m %H:%M"),
        "edited": bool(comment.edited_at), "revision": comment.updated_at.isoformat(),
        "reply": (
            {"id": reply.pk, "author": reply.author.display_name, "text": reply.text[:180]}
            if reply and not reply.is_deleted and reply.post_id == comment.post_id else None
        ),
    }


def response(data):
    result = JsonResponse(data)
    result["Cache-Control"] = "private, no-store"
    return result


@login_required
@require_GET
@rate_limit("channel_discussion_read")
def channel_discussion(request, chat_id, message_id):
    if request.GET.get("account_id") != str(request.user.pk):
        return error("Аккаунт изменился. Обновите страницу.", 409)
    chat, member, post = thread(request, chat_id, message_id)
    try:
        before = integer(request.GET.get("before", "0"), zero=True)
    except ValueError as exc:
        return error(str(exc))
    query = ChannelComment.objects.filter(post=post, is_deleted=False)
    total = query.count()
    if before:
        query = query.filter(pk__lt=before)
    rows = list(query.select_related("author", "reply_to__author").order_by("-pk")[:PAGE + 1])
    more = len(rows) > PAGE
    rows = rows[:PAGE]
    writable = can_write(chat, member, post)
    return response({
        "ok": True, "account_id": request.user.pk, "total": total,
        "closed": post.comments_closed, "can_write": writable,
        "can_moderate": has_admin_right(member, "delete_messages"),
        "protected": chat.protect_content,
        "comments": [serialize(row, member, writable) for row in reversed(rows)],
        "next_before": rows[-1].pk if more else None,
    })


@login_required
@require_POST
@rate_limit("channel_discussion_write")
@transaction.atomic
def discussion_action(request, chat_id, message_id):
    if request.POST.get("account_id") != str(request.user.pk):
        return error("Аккаунт изменился. Обновите страницу.", 409)
    chat, member, post = thread(request, chat_id, message_id, lock=True)
    action = request.POST.get("action")
    writable = can_write(chat, member, post)
    moderate = has_admin_right(member, "delete_messages")

    if action in {"close", "open"}:
        if not moderate:
            return error("Недостаточно прав.", 403)
        closed = action == "close"
        if post.comments_closed != closed:
            post.comments_closed = closed
            post.save(update_fields=["comments_closed", "updated_at"])
            from .models import ChatAdminLog
            ChatAdminLog.objects.create(
                chat=chat, actor=request.user, action="discussion_" + action,
                description=("Закрыто" if closed else "Открыто") + f" обсуждение публикации #{post.pk}.",
            )
        return response({"ok": True, "closed": closed})

    if action == "create":
        text = request.POST.get("text", "").strip()
        if not text or len(text) > 4096:
            return error("Комментарий должен содержать от 1 до 4096 символов.")
        try:
            client_id = UUID(request.POST.get("client_id", ""))
            reply_id = integer(request.POST.get("reply_to", "0"), zero=True)
        except (ValueError, TypeError, AttributeError):
            return error("Некорректные данные отправки.")
        prior = ChannelComment.objects.filter(post=post, author=request.user, client_id=client_id).first()
        if prior:
            if prior.is_deleted:
                return error("Этот комментарий уже был удалён.", 409)
            if prior.text != text or (prior.reply_to_id or 0) != reply_id:
                return error("Идентификатор уже использован.", 409)
            return response({"ok": True, "id": prior.pk, "replayed": True})
        if not writable:
            return error("Комментарии закрыты или ограничены для вас.", 403)
        reply = None
        if reply_id:
            reply = ChannelComment.objects.filter(pk=reply_id, post=post, is_deleted=False).first()
            if reply is None:
                return error("Комментарий для ответа недоступен.", 404)
        comment = ChannelComment.objects.create(
            post=post, author=request.user, client_id=client_id, text=text, reply_to=reply,
        )
        return response({"ok": True, "id": comment.pk, "replayed": False})

    if action not in {"edit", "delete"}:
        return error("Неизвестное действие.")
    try:
        comment_id = integer(request.POST.get("comment_id"))
    except ValueError as exc:
        return error(str(exc))
    comment = get_object_or_404(ChannelComment, pk=comment_id, post=post)
    own = comment.author_id == request.user.pk
    if action == "delete":
        if not (own or moderate):
            return error("Недостаточно прав.", 403)
        if not comment.is_deleted:
            comment.text = ""
            comment.reply_to = None
            comment.is_deleted = True
            comment.save(update_fields=["text", "reply_to", "is_deleted", "updated_at"])
        return response({"ok": True})
    if not own or not writable or comment.is_deleted:
        return error("Редактирование недоступно.", 403)
    text = request.POST.get("text", "").strip()
    if not text or len(text) > 4096:
        return error("Комментарий должен содержать от 1 до 4096 символов.")
    if comment.text == text:
        return response({"ok": True})
    if request.POST.get("revision") != comment.updated_at.isoformat():
        return error("Комментарий уже изменился. Обновите обсуждение.", 409)
    comment.text = text
    comment.edited_at = timezone.now()
    comment.save(update_fields=["text", "edited_at", "updated_at"])
    return response({"ok": True})
