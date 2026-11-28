"""Channel discussions: separate from channel publishing and from group history."""
import hashlib
import json
import logging
from pathlib import Path
from uuid import UUID

from django import forms
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .community_permissions import has_admin_right, is_banned, member_denials, member_reaction_emojis
from .forms import _validate_inline_image
from .models import (Chat, ChatParticipant, ChannelComment, ChannelCommentAttachment,
                     ChannelCommentReaction, Message, MessageHiddenForUser, MessageReaction, community_search_key)
from .ratelimit import rate_limit

PAGE = 40
MAX_ID = 9223372036854775807
MAX_FILES = 4
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 24 * 1024 * 1024
MEDIA_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif", ".mp4": "video/mp4", ".webm": "video/webm",
}
logger = logging.getLogger(__name__)


def reaction_groups(comment_ids, user_id):
    grouped = {}
    for item in ChannelCommentReaction.objects.filter(comment_id__in=comment_ids).order_by().values(
            "comment_id", "emoji").annotate(count=Count("pk"), mine=Count("pk", filter=Q(user_id=user_id))):
        grouped.setdefault(item["comment_id"], []).append(
            {"emoji": item["emoji"], "count": item["count"], "mine": bool(item["mine"])})
    for items in grouped.values():
        items.sort(key=lambda item: (-item["count"], item["emoji"]))
    return grouped


def media_payload(comment, member):
    return [{"id": a.pk, "kind": a.kind, "name": a.original_name, "size": a.size,
             "url": reverse("messenger:comment_media", args=[comment.post.chat_id, comment.post_id, a.pk])
                    + "?account_id=" + str(member.user_id)} for a in comment.attachments.all()]


def prepare_uploads(request, text, reply_id):
    uploads = request.FILES.getlist("attachments")
    if set(request.FILES) - {"attachments"} or len(uploads) > MAX_FILES:
        raise ValueError("Можно отправить не более 4 медиафайлов.")
    if sum(upload.size for upload in uploads) > MAX_TOTAL_BYTES:
        raise ValueError("Общий размер медиа не более 24 МиБ.")
    prepared, signatures = [], []
    for upload in uploads:
        if not 0 < upload.size <= MAX_FILE_BYTES:
            raise ValueError("Один файл должен занимать от 1 байта до 16 МиБ.")
        extension = Path(upload.name).suffix.lower()
        mime = MEDIA_TYPES.get(extension)
        if not mime:
            raise ValueError("Поддерживаются PNG, JPEG, WebP, GIF, MP4 и WebM.")
        kind = "image" if mime.startswith("image/") else "video"
        if kind == "image":
            _validate_inline_image(upload, extension)
        else:
            header = upload.read(16)
            upload.seek(0)
            valid = (header.startswith(bytes.fromhex("1a45dfa3")) if extension == ".webm"
                     else len(header) >= 12 and header[4:8] == b"ftyp")
            if not valid:
                raise ValueError("Некорректный видеофайл.")
        digest = hashlib.sha256()
        for chunk in upload.chunks():
            digest.update(chunk)
        upload.seek(0)
        name = Path(upload.name).name[:255]
        signatures.append([name, upload.size, digest.hexdigest()])
        prepared.append((upload, kind, mime, name))
    digest = hashlib.sha256(json.dumps([text, reply_id, signatures], ensure_ascii=False,
                                        separators=(",", ":")).encode()).hexdigest()
    return prepared, digest


def create_comment(post, user, client_id, text, reply, digest, prepared):
    saved = []
    success = False
    try:
        with transaction.atomic():
            comment = ChannelComment.objects.create(post=post, author=user, client_id=client_id,
                                                   text=text, reply_to=reply, request_digest=digest)
            for upload, kind, mime, name in prepared:
                attachment = ChannelCommentAttachment(comment=comment, kind=kind, mime_type=mime,
                                                      original_name=name, size=upload.size)
                attachment.file.save(name, upload, save=False)
                saved.append((attachment.file.storage, attachment.file.name))
                attachment.save()
        success = True
        return comment
    finally:
        if not success:
            for storage, name in saved:
                try:
                    storage.delete(name)
                except OSError:
                    logger.exception("Could not clean failed comment upload")



def error(text, status=400):
    result = JsonResponse({"ok": False, "error": text}, status=status)
    result["Cache-Control"] = "private, no-store"
    return result


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


def serialize(comment, member, writable, reactions):
    own = comment.author_id == member.user_id
    reply = comment.reply_to
    return {
        "id": comment.pk, "text": comment.text,
        "author": comment.author.display_name, "username": comment.author.username,
        "own": own, "can_edit": own and writable,
        "can_delete": own or has_admin_right(member, "delete_messages"),
        "time": timezone.localtime(comment.created_at).strftime("%d.%m %H:%M"),
        "edited": bool(comment.edited_at), "revision": comment.updated_at.isoformat(),
        "reactions": reactions.get(comment.pk, []),
        "attachments": media_payload(comment, member),
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
    q = request.GET.get("q", "").strip()
    if len(q) > 120 or len(q.split()) > 10:
        return error("Поиск: до 120 символов и 10 слов.")
    for term in community_search_key(q).split():
        query = query.filter(search_key__contains=term)
    matched = query.count() if q else total
    if before:
        query = query.filter(pk__lt=before)
    rows = list(query.select_related("author", "reply_to__author", "post").prefetch_related("attachments").order_by("-pk")[:PAGE + 1])
    more = len(rows) > PAGE
    rows = rows[:PAGE]
    writable = can_write(chat, member, post)
    reactions = reaction_groups([row.pk for row in rows], member.user_id)
    return response({
        "ok": True, "account_id": request.user.pk, "total": total, "matched": matched, "query": q,
        "allowed_reactions": [] if post.comments_closed else member_reaction_emojis(chat, member),
        "closed": post.comments_closed, "can_write": writable,
        "can_moderate": has_admin_right(member, "delete_messages"),
        "protected": chat.protect_content,
        "comments": [serialize(row, member, writable, reactions) for row in reversed(rows)],
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
    if request.FILES and action != "create":
        return error("Вложения доступны только при создании комментария.")
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
        if len(text) > 4096 or (not text and not request.FILES):
            return error("Введите комментарий до 4096 символов или прикрепите медиа.")
        try:
            client_id = UUID(request.POST.get("client_id", ""))
            reply_id = integer(request.POST.get("reply_to", "0"), zero=True)
        except (ValueError, TypeError, AttributeError):
            return error("Некорректные данные отправки.")
        prior = ChannelComment.objects.filter(post=post, author=request.user, client_id=client_id).first()
        if not prior and not writable:
            return error("Комментарии закрыты или ограничены для вас.", 403)
        try:
            prepared, digest = prepare_uploads(request, text, reply_id)
        except forms.ValidationError as exc:
            return error(exc.messages[0])
        except (ValueError, OSError) as exc:
            return error(str(exc) if isinstance(exc, ValueError) else "Не удалось прочитать файл.")
        if prior:
            if prior.is_deleted:
                return error("Этот комментарий уже был удалён.", 409)
            if ((prior.request_digest and prior.request_digest != digest) or
                (not prior.request_digest and (prepared or prior.text != text or (prior.reply_to_id or 0) != reply_id))):
                return error("Идентификатор уже использован.", 409)
            return response({"ok": True, "id": prior.pk, "replayed": True})
        if not writable:
            return error("Комментарии закрыты или ограничены для вас.", 403)
        reply = None
        if reply_id:
            reply = ChannelComment.objects.filter(pk=reply_id, post=post, is_deleted=False).first()
            if reply is None:
                return error("Комментарий для ответа недоступен.", 404)
        try:
            comment = create_comment(post, request.user, client_id, text, reply, digest, prepared)
        except OSError:
            logger.exception("Could not store comment media")
            return error("Не удалось сохранить медиа.", 503)
        return response({"ok": True, "id": comment.pk, "replayed": False})

    if action not in {"edit", "delete", "react"}:
        return error("Неизвестное действие.")
    try:
        comment_id = integer(request.POST.get("comment_id"))
    except ValueError as exc:
        return error(str(exc))
    comment = get_object_or_404(ChannelComment, pk=comment_id, post=post)
    own = comment.author_id == request.user.pk
    if action == "react":
        emoji = request.POST.get("emoji", "")
        enabled = request.POST.get("enabled")
        if emoji not in MessageReaction.Emoji.values or enabled not in {"0", "1"}:
            return error("Некорректная реакция.")
        if comment.is_deleted:
            raise Http404
        if post.comments_closed or emoji not in member_reaction_emojis(chat, member):
            return error("Реакция недоступна.", 403)
        own_reactions = ChannelCommentReaction.objects.filter(comment=comment, user=request.user)
        if enabled == "1":
            if not own_reactions.filter(emoji=emoji).exists():
                if own_reactions.count() >= MessageReaction.MAX_PER_USER:
                    return error("Не более трёх реакций на комментарий.", 409)
                own_reactions.create(emoji=emoji)
        else:
            own_reactions.filter(emoji=emoji).delete()
        return response({"ok": True, "id": comment.pk,
                         "reactions": reaction_groups([comment.pk], request.user.pk).get(comment.pk, [])})
    if action == "delete":
        if not (own or moderate):
            return error("Недостаточно прав.", 403)
        if not comment.is_deleted:
            comment.text = ""
            comment.reply_to = None
            comment.is_deleted = True
            comment.save(update_fields=["text", "reply_to", "is_deleted", "updated_at"])
            comment.attachments.all().delete()
            comment.reactions.all().delete()
        return response({"ok": True})
    if not own or not writable or comment.is_deleted:
        return error("Редактирование недоступно.", 403)
    text = request.POST.get("text", "").strip()
    if len(text) > 4096 or (not text and not comment.attachments.exists()):
        return error("Введите комментарий до 4096 символов или сохраните медиа.")
    if comment.text == text:
        return response({"ok": True})
    if request.POST.get("revision") != comment.updated_at.isoformat():
        return error("Комментарий уже изменился. Обновите обсуждение.", 409)
    comment.text = text
    comment.edited_at = timezone.now()
    comment.save(update_fields=["text", "edited_at", "updated_at"])
    return response({"ok": True})


@login_required
@require_GET
def comment_media(request, chat_id, message_id, attachment_id):
    if request.GET.get("account_id") != str(request.user.pk):
        raise Http404
    chat, member, post = thread(request, chat_id, message_id)
    attachment = get_object_or_404(ChannelCommentAttachment, pk=attachment_id, comment__post=post,
                                   comment__is_deleted=False)
    mime = MEDIA_TYPES.get(Path(attachment.original_name).suffix.lower())
    if not mime or mime != attachment.mime_type or not attachment.file or not attachment.file.storage.exists(attachment.file.name):
        raise Http404
    from .views import _inline_file_response
    try:
        result = _inline_file_response(request, attachment, mime)
    except (OSError, ValueError):
        raise Http404 from None
    result["Cache-Control"] = "private, no-store"
    result["X-Content-Type-Options"] = "nosniff"
    result["Referrer-Policy"] = "no-referrer"
    return result
