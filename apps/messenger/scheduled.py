"""Persistent text-message outbox with a transactionally safe delivery worker."""
import hashlib
import json
import logging
from datetime import timedelta
from uuid import UUID

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_http_methods, require_POST

from . import views
from .models import Chat, ChatParticipant, Message, ScheduledMessage
from .ratelimit import rate_limit
from .quotes import make_quote, resolve_quote
from .services import apply_archive_rules_on_new_message, touch_chat

logger = logging.getLogger(__name__)
MAX_PENDING = 100
ACTIVE = (ScheduledMessage.Status.PENDING, ScheduledMessage.Status.FAILED)


class OutboxError(ValueError):
    def __init__(self, message, status=400, retry_after=0):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def _failure(error):
    return JsonResponse({"ok": False, "error": str(error)}, status=error.status)


def _response(data):
    response = JsonResponse({"ok": True, **data})
    response["Cache-Control"] = "private, no-store"
    return response


def _time(raw):
    try:
        result = parse_datetime(raw)
        if result is None or timezone.is_naive(result):
            raise ValueError
        return result
    except (TypeError, ValueError, OverflowError):
        raise OutboxError("Укажите корректную дату и время с часовым поясом.") from None


def _future(value, now):
    if value <= now:
        raise OutboxError("Время отправки должно быть в будущем.")
    if value > now + timedelta(days=365):
        raise OutboxError("Можно запланировать отправку не более чем на год вперёд.")


def _fields(post, *, include_reply=True):
    text = post.get("text", "")
    if not text.strip() or len(text) > 4096:
        raise OutboxError("Введите сообщение длиной от 1 до 4096 символов.")
    when = _time(post.get("scheduled_for", ""))
    silent = post.get("silent", "") in ("1", "true", "on")
    reply_id = None
    if include_reply and post.get("reply_to"):
        try:
            reply_id = int(post["reply_to"])
            if not 0 < reply_id <= 9223372036854775807:
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            raise OutboxError("Некорректный ответ на сообщение.") from None
    return text, when, silent, reply_id


def _identity(request):
    # A tab from an old account must not schedule or mutate another account.
    if request.POST.get("account_id") != str(request.user.pk):
        raise OutboxError("Аккаунт изменился. Обновите страницу.", 409)


def _digest(chat_id, text, when, silent, reply_id, quote=""):
    payload = [chat_id, text, when.isoformat(), silent, reply_id]
    if quote:
        payload.append(quote)
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def _lock_sender_chat(sender_id, chat_id):
    # Same sender -> chat lock ordering as keyed normal sends.
    sender = get_user_model().objects.select_for_update().filter(pk=sender_id).first()
    if sender is None:
        return None, None
    chat = Chat.objects.select_for_update().filter(pk=chat_id).first()
    return sender, chat


def _member(chat, sender):
    if sender is None or not sender.is_active or chat is None:
        raise OutboxError("Аккаунт или чат недоступен.", 403)
    membership = ChatParticipant.objects.filter(chat=chat, user=sender, is_hidden=False).first()
    if membership is None:
        raise OutboxError("Вы больше не состоите в чате.", 403)
    return membership


def _validate(chat, sender, text, reply_id, *, check_slow_mode):
    membership = _member(chat, sender)
    capabilities = views._posting_capabilities(chat, membership, sender)
    if not capabilities["text"]:
        raise OutboxError(capabilities["reason"] or "Отправка текста запрещена.", 403)
    restriction = views._posting_restriction(
        chat, membership, text=text, check_slow_mode=check_slow_mode,
    )
    if restriction:
        reason, retry_after = restriction
        raise OutboxError(reason, 403, retry_after)
    reply = None
    if reply_id is not None:
        reply = views._visible_message_queryset(chat, sender).filter(pk=reply_id, is_deleted=False).first()
        if reply is None:
            raise OutboxError("Сообщение для ответа больше недоступно.", 409)
    return reply


def _serialize(item):
    return {
        "id": item.pk,
        "text": item.text,
        "silent": item.silent,
        "reply_to": item.reply_message_id,
        "has_quote": bool(item.reply_quote),
        "scheduled_for": item.scheduled_for.isoformat(),
        "next_attempt_at": item.next_attempt_at.isoformat(),
        "status": item.status,
        "error": item.error,
        "revision": item.revision,
        "delivered_message_id": item.delivered_message_id,
        "action_url": reverse("messenger:scheduled_action", args=[item.chat_id, item.pk]),
    }


def _deliver(item, sender, chat):
    """Caller holds the sender, chat and outbox row locks, in that order."""
    if item.status not in ACTIVE:
        return item
    try:
        reply = _validate(
            chat, sender, item.text, item.reply_message_id, check_slow_mode=True,
        )
        if item.reply_quote and (chat.protect_content or not resolve_quote(reply, item.reply_quote)):
            raise OutboxError("Цитата больше недоступна. Уберите ответ и повторите отправку.", 409)
    except OutboxError as error:
        item.error = str(error)[:300]
        item.revision += 1
        if error.retry_after:
            item.status = ScheduledMessage.Status.PENDING
            item.next_attempt_at = timezone.now() + timedelta(seconds=error.retry_after + 1)
        else:
            item.status = ScheduledMessage.Status.FAILED
        item.save(update_fields=["error", "status", "next_attempt_at", "revision", "updated_at"])
        return item

    message = Message.objects.create(
        chat=chat, sender=sender, text=item.text, reply_to=reply,
        reply_quote=item.reply_quote, silent=item.silent,
        signature_name=sender.display_name if chat.type == Chat.Type.CHANNEL and chat.signatures_enabled else "",
    )
    touch_chat(chat)
    apply_archive_rules_on_new_message(chat, message)
    # Do not erase a new draft or typing state when the worker delivers.
    item.delivered_message = message
    item.status = ScheduledMessage.Status.SENT
    item.text = ""
    item.reply_message_id = None
    item.reply_quote = ""
    item.error = ""
    item.revision += 1
    item.save(update_fields=[
        "delivered_message", "status", "text", "reply_message_id", "reply_quote", "error", "revision", "updated_at",
    ])
    return item


@login_required
@require_http_methods(["GET", "POST"])
@rate_limit("scheduled_messages")
def scheduled_messages(request, chat_id):
    chat = views._chat_for_user(request.user, chat_id)
    if request.method == "GET":
        account = request.GET.get("account_id")
        if account is not None and account != str(request.user.pk):
            return _failure(OutboxError("Аккаунт изменился. Обновите страницу.", 409))
        rows = ScheduledMessage.objects.filter(chat=chat, sender=request.user, status__in=ACTIVE)
        return _response({"items": [_serialize(item) for item in rows.order_by("scheduled_for", "id")[:MAX_PENDING]]})

    try:
        _identity(request)
        if request.FILES:
            raise OutboxError("Пока можно планировать только текстовые сообщения.")
        text, when, silent, reply_id = _fields(request.POST)
        try:
            client_id = UUID(request.POST.get("client_message_id", ""))
        except (TypeError, ValueError, AttributeError):
            raise OutboxError("Некорректный идентификатор отправки.") from None
        raw_quote = request.POST.get("reply_quote", "")
        if len(raw_quote) > 1024:
            raise OutboxError("Выберите фрагмент текста до 1024 символов.")
        digest = _digest(chat.pk, text, when, silent, reply_id, raw_quote)
        with transaction.atomic():
            sender, fresh_chat = _lock_sender_chat(request.user.pk, chat.pk)
            _member(fresh_chat, sender)
            previous = ScheduledMessage.objects.filter(sender=sender, client_id=client_id).first()
            if previous:
                if previous.request_digest != digest:
                    raise OutboxError("Идентификатор уже использован для другой отправки.", 409)
                return _response({"item": _serialize(previous), "replayed": True})
            _future(when, timezone.now())
            reply = _validate(fresh_chat, sender, text, reply_id, check_slow_mode=False)
            try:
                if raw_quote and fresh_chat.protect_content:
                    raise ValueError("Цитирование отключено в защищённом чате.")
                quote_ref = make_quote(reply, raw_quote)
            except ValueError as error:
                raise OutboxError(str(error)) from error
            if ScheduledMessage.objects.filter(sender=sender, status__in=ACTIVE).count() >= MAX_PENDING:
                raise OutboxError("Достигнут предел в 100 запланированных сообщений.", 409)
            item = ScheduledMessage.objects.create(
                chat=fresh_chat, sender=sender, client_id=client_id, request_digest=digest,
                text=text, reply_message_id=reply_id, reply_quote=quote_ref, silent=silent,
                scheduled_for=when, next_attempt_at=when,
            )
        return _response({"item": _serialize(item)})
    except OutboxError as error:
        return _failure(error)


@login_required
@require_POST
@rate_limit("scheduled_action")
def scheduled_action(request, chat_id, scheduled_id):
    views._chat_for_user(request.user, chat_id)
    try:
        _identity(request)
        action = request.POST.get("action", "")
        if action not in {"edit", "cancel", "send_now"}:
            raise OutboxError("Неизвестное действие.")
        with transaction.atomic():
            sender, chat = _lock_sender_chat(request.user.pk, chat_id)
            _member(chat, sender)
            item = ScheduledMessage.objects.select_for_update().filter(
                pk=scheduled_id, chat=chat, sender=sender,
            ).first()
            if item is None:
                raise Http404
            # A repeated delivery/cancellation cannot create another message.
            if (action == "send_now" and item.status == ScheduledMessage.Status.SENT
                    or action == "cancel" and item.status == ScheduledMessage.Status.CANCELED):
                return _response({"item": _serialize(item), "replayed": True})
            if str(item.revision) != request.POST.get("revision") or item.status not in ACTIVE:
                raise OutboxError("Сообщение уже изменилось. Обновите список.", 409)
            if action == "cancel":
                item.status = ScheduledMessage.Status.CANCELED
                item.text = ""
                item.reply_message_id = None
                item.reply_quote = ""
                item.error = ""
                item.revision += 1
                item.save(update_fields=["status", "text", "reply_message_id", "reply_quote", "error", "revision", "updated_at"])
            elif action == "edit":
                text, when, silent, _ = _fields(request.POST, include_reply=False)
                _future(when, timezone.now())
                reply_id = None if request.POST.get("remove_reply") == "1" else item.reply_message_id
                reply = _validate(chat, sender, text, reply_id, check_slow_mode=False)
                if reply_id is None:
                    item.reply_quote = ""
                elif item.reply_quote and (chat.protect_content or not resolve_quote(reply, item.reply_quote)):
                    raise OutboxError("Цитата больше недоступна. Уберите ответ.", 409)
                item.text, item.silent, item.reply_message_id = text, silent, reply_id
                item.scheduled_for = item.next_attempt_at = when
                item.status = ScheduledMessage.Status.PENDING
                item.error = ""
                item.revision += 1
                item.save(update_fields=[
                    "text", "silent", "reply_message_id", "reply_quote", "scheduled_for", "next_attempt_at",
                    "status", "error", "revision", "updated_at",
                ])
            else:
                _deliver(item, sender, chat)
        return _response({"item": _serialize(item)})
    except OutboxError as error:
        return _failure(error)


def deliver_due_messages(limit=100):
    """Multiple workers can race safely; a crash rolls back both send and receipt."""
    due = list(ScheduledMessage.objects.filter(
        status=ScheduledMessage.Status.PENDING, next_attempt_at__lte=timezone.now(),
    ).order_by("next_attempt_at", "pk").values_list("pk", "sender_id", "chat_id")[:limit])
    sent = 0
    for pk, sender_id, chat_id in due:
        try:
            with transaction.atomic():
                sender, chat = _lock_sender_chat(sender_id, chat_id)
                if sender is None or chat is None:
                    continue  # Cascading deletion removes the outbox row.
                item = ScheduledMessage.objects.select_for_update().filter(
                    pk=pk, sender=sender, chat=chat,
                    status=ScheduledMessage.Status.PENDING, next_attempt_at__lte=timezone.now(),
                ).first()
                if item is None:
                    continue
                _deliver(item, sender, chat)
                sent += int(item.status == ScheduledMessage.Status.SENT)
        except Exception:
            # Retry transient database/storage failures at the next tick.
            # Do not log user message contents.
            logger.exception("Scheduled delivery failed (outbox id=%s)", pk)
    return sent
