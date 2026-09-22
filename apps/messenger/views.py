from datetime import timedelta
from pathlib import Path

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import connection, transaction
from django.db.models import (
    BigIntegerField,
    BooleanField,
    Count,
    F,
    OuterRef,
    Q,
    Subquery,
    TextField,
    Value,
)
from django.db.models.functions import Coalesce
from django.http import FileResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from .forms import CommunityForm, EditMessageForm, MessageForm
from .models import Chat, ChatParticipant, Contact, Message, MessageAttachment, PinnedMessage
from .ratelimit import rate_limit
from .services import (
    attachment_kind,
    attachment_url,
    clone_attachments,
    delete_message_content,
    get_or_create_direct_chat,
    mark_chat_read,
    other_user_for_chat,
    serialize_message,
    serialize_pins,
    touch_chat,
)

User = get_user_model()


def _safe_next(request, fallback):
    candidate = request.POST.get("next", "")
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return fallback


def _wants_json(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _chat_for_user(user, chat_id):
    return get_object_or_404(
        Chat.objects.filter(participants=user)
        .prefetch_related("participants", "memberships__user")
        .distinct(),
        pk=chat_id,
    )


def _membership(chat, user):
    for membership in chat.memberships.all():
        if membership.user_id == user.pk:
            return membership
    return ChatParticipant.objects.get(chat=chat, user=user)


def _other_membership(chat, user):
    for membership in chat.memberships.all():
        if membership.user_id != user.pk:
            return membership
    return None


def _other_last_read_id(chat, user):
    other = _other_membership(chat, user)
    if other is not None:
        return other.last_read_message_id or 0
    return chat.messages.filter(is_deleted=False).order_by("-id").values_list("id", flat=True).first() or 0


def _presence_text(user):
    if user.is_online:
        return "в сети"
    if not user.last_seen_at:
        return "был(а) давно"

    now = timezone.now()
    delta = now - user.last_seen_at
    local_seen = timezone.localtime(user.last_seen_at)
    if delta < timedelta(minutes=15):
        return "был(а) недавно"
    if local_seen.date() == timezone.localdate():
        return f"был(а) сегодня в {local_seen:%H:%M}"
    if local_seen.date() == timezone.localdate() - timedelta(days=1):
        return f"был(а) вчера в {local_seen:%H:%M}"
    return f"был(а) {local_seen:%d.%m.%Y} в {local_seen:%H:%M}"


def _decorate_chat_ui(chat, user):
    chat.is_saved_ui = (
        chat.type == Chat.Type.PRIVATE
        and chat.direct_key == f"self:{user.pk}"
    )
    chat.is_collective_ui = chat.type != Chat.Type.PRIVATE

    if chat.type == Chat.Type.PRIVATE:
        other_user = other_user_for_chat(chat, user)
        chat.other_user = other_user
        chat.display_name_ui = "Избранное" if chat.is_saved_ui else other_user.display_name
        chat.username_ui = "" if chat.is_saved_ui else other_user.username
        chat.avatar_text_ui = "★" if chat.is_saved_ui else other_user.initials
        chat.search_text_ui = f"{chat.display_name_ui} {chat.username_ui}".lower()
        chat.status_ui = "Личное облако" if chat.is_saved_ui else _presence_text(other_user)
    else:
        chat.other_user = None
        chat.display_name_ui = chat.title or (
            "Канал" if chat.type == Chat.Type.CHANNEL else "Группа"
        )
        chat.username_ui = chat.username or ""
        chat.avatar_text_ui = "К" if chat.type == Chat.Type.CHANNEL else "Г"
        chat.search_text_ui = f"{chat.display_name_ui} {chat.username_ui}".lower()
        members_count = chat.memberships.count()
        if chat.type == Chat.Type.CHANNEL:
            chat.status_ui = f"канал · {members_count} подписчик(ов)"
        else:
            chat.status_ui = f"группа · {members_count} участник(ов)"
    return chat


def _base_message_queryset(chat):
    return (
        chat.messages.select_related("sender", "reply_to", "reply_to__sender")
        .prefetch_related("attachments")
    )


def _prepare_sidebar_chats(user, archived=False):
    last_message = Message.objects.filter(chat=OuterRef("pk"), is_deleted=False).order_by("-id")
    membership = ChatParticipant.objects.filter(chat=OuterRef("pk"), user=user)

    chats = list(
        Chat.objects.filter(memberships__user=user, memberships__is_archived=archived)
        .annotate(
            last_message_id_ui=Subquery(last_message.values("id")[:1]),
            last_message_text_ui=Subquery(last_message.values("text")[:1]),
            last_message_sender_id_ui=Subquery(last_message.values("sender_id")[:1]),
            last_message_created_at_ui=Subquery(last_message.values("created_at")[:1]),
            last_read_message_id_ui=Coalesce(
                Subquery(
                    membership.values("last_read_message_id")[:1],
                    output_field=BigIntegerField(),
                ),
                Value(0, output_field=BigIntegerField()),
            ),
            is_pinned_ui=Subquery(
                membership.values("is_pinned")[:1], output_field=BooleanField()
            ),
            is_muted_ui=Subquery(
                membership.values("is_muted")[:1], output_field=BooleanField()
            ),
            draft_text_ui=Subquery(
                membership.values("draft_text")[:1], output_field=TextField()
            ),
        )
        .annotate(
            unread_count_ui=Count(
                "messages",
                filter=(
                    ~Q(messages__sender=user)
                    & Q(messages__is_deleted=False)
                    & Q(messages__id__gt=F("last_read_message_id_ui"))
                ),
            )
        )
        .prefetch_related("participants")
        .order_by(
            F("is_pinned_ui").desc(nulls_last=True),
            F("last_message_created_at_ui").desc(nulls_last=True),
            "-updated_at",
        )
    )

    for chat in chats:
        _decorate_chat_ui(chat, user)
        preview = " ".join((chat.last_message_text_ui or "").split())
        chat.last_message_preview_ui = preview or "Медиа"
    return chats


def _forward_targets(user):
    targets = list(
        Chat.objects.filter(participants=user)
        .prefetch_related("participants")
        .distinct()
        .order_by("-updated_at")[:60]
    )
    for chat in targets:
        _decorate_chat_ui(chat, user)
    return targets


def _messenger_context(user, selected_chat=None, chat_messages=None, archived=False, focus_id=0):
    context = {
        "chats": _prepare_sidebar_chats(user, archived=archived),
        "selected_chat": selected_chat,
        "chat_messages": chat_messages or [],
        "message_form": MessageForm(),
        "show_archived": archived,
        "archived_count": ChatParticipant.objects.filter(user=user, is_archived=True).count(),
        "forward_targets": _forward_targets(user),
        "message_focus_id": focus_id,
        "server_time": timezone.now().isoformat(),
    }
    if selected_chat is None:
        return context

    membership = _membership(selected_chat, user)
    _decorate_chat_ui(selected_chat, user)
    selected_chat.other_status_ui = selected_chat.status_ui
    other_last_read_id = (
        _other_last_read_id(selected_chat, user)
        if selected_chat.type == Chat.Type.PRIVATE
        else 0
    )

    pins = list(
        PinnedMessage.objects.filter(chat=selected_chat, message__is_deleted=False)
        .select_related("message", "message__sender")
        .order_by("-pinned_at", "-id")[:8]
    )
    pinned_ids = {pin.message_id for pin in pins}
    for message in context["chat_messages"]:
        message.is_pinned_ui = message.pk in pinned_ids
        message.is_read_ui = message.sender_id == user.pk and message.pk <= other_last_read_id

    shared_items = []
    attachments = (
        MessageAttachment.objects.filter(message__chat=selected_chat, message__is_deleted=False)
        .select_related("message")
        .order_by("-id")[:36]
    )
    for attachment in attachments:
        attachment.ui_url = attachment_url(attachment)
        shared_items.append(attachment)

    can_post = not (
        selected_chat.type == Chat.Type.CHANNEL
        and membership.role not in {
            ChatParticipant.Role.OWNER,
            ChatParticipant.Role.ADMIN,
        }
    )

    context.update(
        {
            "active_membership": membership,
            "can_post": can_post,
            "other_last_read_id": other_last_read_id,
            "pinned_records": pins,
            "pinned_message_ids": pinned_ids,
            "shared_attachments": shared_items,
            "search_url": reverse("messenger:search_messages", args=[selected_chat.pk]),
            "draft_url": reverse("messenger:save_draft", args=[selected_chat.pk]),
            "typing_url": reverse("messenger:typing", args=[selected_chat.pk]),
        }
    )
    return context


def _serialized_message(message, user, chat):
    pinned_ids = set(
        PinnedMessage.objects.filter(chat=chat, message__is_deleted=False)
        .values_list("message_id", flat=True)
    )
    return serialize_message(
        message,
        user,
        other_last_read_id=(
            _other_last_read_id(chat, user)
            if chat.type == Chat.Type.PRIVATE
            else 0
        ),
        pinned_ids=pinned_ids,
    )


@login_required
def home(request):
    archived = request.GET.get("archived") == "1"
    return render(
        request,
        "messenger/index.html",
        _messenger_context(request.user, archived=archived),
    )


@login_required
def chat_detail(request, chat_id):
    chat = _chat_for_user(request.user, chat_id)
    membership = _membership(chat, request.user)
    latest = chat.messages.filter(is_deleted=False).order_by("-id").first()
    if latest:
        mark_chat_read(chat, request.user, latest)

    try:
        focus_id = max(0, int(request.GET.get("message", "0")))
    except (TypeError, ValueError):
        focus_id = 0

    base = _base_message_queryset(chat).filter(is_deleted=False)
    focus = base.filter(pk=focus_id).first() if focus_id else None
    if focus is not None:
        before = list(base.filter(id__lte=focus.pk).order_by("-id")[:50])
        before.reverse()
        after = list(base.filter(id__gt=focus.pk).order_by("id")[:50])
        chat_messages = before + after
    else:
        chat_messages = list(base.order_by("-id")[:100])
        chat_messages.reverse()
        focus_id = 0

    return render(
        request,
        "messenger/index.html",
        _messenger_context(
            request.user,
            chat,
            chat_messages,
            archived=membership.is_archived,
            focus_id=focus_id,
        ),
    )


@login_required
def saved_messages(request):
    chat = get_or_create_direct_chat(request.user, request.user)
    return redirect("messenger:chat", chat_id=chat.pk)


@login_required
def create_community(request):
    initial_type = request.GET.get("type")
    if initial_type not in {Chat.Type.GROUP, Chat.Type.CHANNEL}:
        initial_type = Chat.Type.GROUP
    form = CommunityForm(
        request.POST or None,
        initial={"type": initial_type},
    )
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            chat = Chat.objects.create(
                type=form.cleaned_data["type"],
                title=form.cleaned_data["title"],
                username=form.cleaned_data["username"] or None,
                description=form.cleaned_data["description"],
            )
            ChatParticipant.objects.create(
                chat=chat,
                user=request.user,
                role=ChatParticipant.Role.OWNER,
            )

            if chat.type == Chat.Type.GROUP:
                requested = form.cleaned_data["members"]
                member_query = Q()
                for username in requested:
                    member_query |= Q(username__iexact=username)
                users = (
                    list(
                        User.objects.filter(member_query, is_active=True)
                        .exclude(pk=request.user.pk)
                    )
                    if requested
                    else []
                )
                ChatParticipant.objects.bulk_create(
                    [
                        ChatParticipant(
                            chat=chat,
                            user=user,
                            role=ChatParticipant.Role.MEMBER,
                        )
                        for user in users
                    ],
                    ignore_conflicts=True,
                )
                found = {user.username.lower() for user in users}
                missing = [name for name in requested if name.lower() not in found]
                if missing:
                    messages.warning(
                        request,
                        "Не нашли: " + ", ".join(f"@{name}" for name in missing[:8]),
                    )

        messages.success(
            request,
            "Канал вышел в эфир." if chat.type == Chat.Type.CHANNEL
            else "Группа собрана. Можно начинать собрание.",
        )
        return redirect("messenger:chat", chat_id=chat.pk)

    return render(
        request,
        "messenger/create_community.html",
        {"form": form},
    )


@login_required
@require_POST
def join_public_chat(request, username):
    chat = get_object_or_404(
        Chat,
        username__iexact=username,
        type__in=(Chat.Type.GROUP, Chat.Type.CHANNEL),
    )
    ChatParticipant.objects.get_or_create(
        chat=chat,
        user=request.user,
        defaults={"role": ChatParticipant.Role.MEMBER},
    )
    return redirect("messenger:chat", chat_id=chat.pk)


@login_required
@require_POST
def start_chat(request, username):
    target = get_object_or_404(User, username__iexact=username, is_active=True)
    chat = get_or_create_direct_chat(request.user, target)
    return redirect("messenger:chat", chat_id=chat.pk)


@login_required
def contacts(request):
    query = request.GET.get("q", "").strip().lstrip("@")[:150]
    contact_links = list(
        Contact.objects.filter(owner=request.user)
        .select_related("user")
        .order_by("user__username")
    )
    contact_ids = {item.user_id for item in contact_links}

    user_results = []
    channel_results = []
    if query:
        user_results = list(
            User.objects.filter(is_active=True, username__icontains=query)
            .exclude(pk=request.user.pk)
            .order_by("username")[:30]
        )
        for user in user_results:
            user.is_contact_ui = user.pk in contact_ids

        channel_results = list(
            Chat.objects.filter(
                type=Chat.Type.CHANNEL,
                username__icontains=query,
            )
            .exclude(username__isnull=True)
            .order_by("username")[:30]
        )
        joined_chat_ids = set(
            ChatParticipant.objects.filter(user=request.user).values_list(
                "chat_id", flat=True
            )
        )
        for channel in channel_results:
            channel.is_joined_ui = channel.pk in joined_chat_ids

    return render(
        request,
        "messenger/contacts.html",
        {
            "contacts": contact_links,
            "query": query,
            "search_results": user_results,
            "channel_results": channel_results,
            "focus_search": request.GET.get("focus") == "search",
        },
    )


@login_required
@require_POST
def add_contact(request, username):
    target = get_object_or_404(User, username__iexact=username, is_active=True)
    if target.pk != request.user.pk:
        Contact.objects.get_or_create(owner=request.user, user=target)
        messages.success(request, f"@{target.username} добавлен в контакты.")
    return redirect(_safe_next(request, reverse("messenger:contacts")))


@login_required
@require_POST
def remove_contact(request, username):
    target = get_object_or_404(User, username__iexact=username, is_active=True)
    Contact.objects.filter(owner=request.user, user=target).delete()
    messages.success(request, f"@{target.username} удалён из контактов.")
    return redirect(_safe_next(request, reverse("messenger:contacts")))


@login_required
@require_POST
@rate_limit("send_message")
def send_message(request, chat_id):
    chat = _chat_for_user(request.user, chat_id)
    membership = _membership(chat, request.user)
    if (
        chat.type == Chat.Type.CHANNEL
        and membership.role not in {ChatParticipant.Role.OWNER, ChatParticipant.Role.ADMIN}
    ):
        return JsonResponse(
            {"ok": False, "error": "Публиковать в канале могут только администраторы."},
            status=403,
        )
    form = MessageForm(request.POST, request.FILES)
    wants_json = _wants_json(request)

    if not form.is_valid():
        if wants_json:
            return JsonResponse({"ok": False, "errors": form.errors.get_json_data()}, status=400)
        for error in form.non_field_errors():
            messages.error(request, error)
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect("messenger:chat", chat_id=chat.pk)

    reply_to = None
    reply_id = form.cleaned_data.get("reply_to")
    if reply_id:
        reply_to = chat.messages.filter(pk=reply_id, is_deleted=False).first()
        if reply_to is None:
            payload = {"ok": False, "errors": {"reply_to": [{"message": "Сообщение для ответа больше недоступно."}]}}
            if wants_json:
                return JsonResponse(payload, status=400)
            messages.error(request, "Сообщение для ответа больше недоступно.")
            return redirect("messenger:chat", chat_id=chat.pk)

    attachment_mode = form.cleaned_data.get("attachment_mode") or MessageForm.MODE_MEDIA
    send_as_file = attachment_mode == MessageForm.MODE_FILE

    with transaction.atomic():
        message = Message.objects.create(
            chat=chat,
            sender=request.user,
            text=form.cleaned_data["text"],
            reply_to=reply_to,
        )
        for uploaded in form.cleaned_data["attachments"]:
            MessageAttachment.objects.create(
                message=message,
                file=uploaded,
                kind=MessageAttachment.Kind.FILE if send_as_file else attachment_kind(uploaded),
                original_name=Path(uploaded.name).name[:255],
                mime_type=(getattr(uploaded, "content_type", "") or "")[:127],
                size=uploaded.size,
            )
        touch_chat(chat)
        ChatParticipant.objects.filter(chat=chat).update(is_archived=False)
        ChatParticipant.objects.filter(chat=chat, user=request.user).update(
            draft_text="",
            draft_updated_at=None,
            last_typing_at=None,
        )
        mark_chat_read(chat, request.user, message)

    message = _base_message_queryset(chat).get(pk=message.pk)
    if wants_json:
        return JsonResponse({"ok": True, "message": _serialized_message(message, request.user, chat)})
    return redirect("messenger:chat", chat_id=chat.pk)


@login_required
@require_POST
def edit_message(request, chat_id, message_id):
    chat = _chat_for_user(request.user, chat_id)
    message = get_object_or_404(
        _base_message_queryset(chat),
        pk=message_id,
        sender=request.user,
        is_deleted=False,
    )
    form = EditMessageForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"ok": False, "errors": form.errors.get_json_data()}, status=400)

    text = form.cleaned_data["text"]
    if not text and not message.attachments.exists():
        return JsonResponse(
            {"ok": False, "errors": {"text": [{"message": "Текстовое сообщение не может быть пустым."}]}},
            status=400,
        )

    message.text = text
    message.edited_at = timezone.now()
    message.save(update_fields=("text", "edited_at", "updated_at"))
    message = _base_message_queryset(chat).get(pk=message.pk)
    return JsonResponse({"ok": True, "message": _serialized_message(message, request.user, chat)})


@login_required
@require_POST
def delete_message(request, chat_id, message_id):
    chat = _chat_for_user(request.user, chat_id)
    message = get_object_or_404(
        _base_message_queryset(chat),
        pk=message_id,
        sender=request.user,
        is_deleted=False,
    )
    with transaction.atomic():
        delete_message_content(message)
    message = _base_message_queryset(chat).get(pk=message.pk)
    return JsonResponse({"ok": True, "message": _serialized_message(message, request.user, chat)})


@login_required
@require_POST
def forward_message(request, chat_id, message_id):
    source_chat = _chat_for_user(request.user, chat_id)
    source = get_object_or_404(_base_message_queryset(source_chat), pk=message_id, is_deleted=False)
    raw_target = request.POST.get("target_chat_id", "").strip()

    if raw_target == "saved":
        target_chat = get_or_create_direct_chat(request.user, request.user)
    else:
        try:
            target_chat_id = int(raw_target)
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": "Выберите чат для пересылки."}, status=400)
        target_chat = _chat_for_user(request.user, target_chat_id)

    origin = source.forwarded_from or source
    origin_name = source.forwarded_from_name or source.sender.display_name
    origin_username = source.forwarded_from_username or source.sender.username

    with transaction.atomic():
        forwarded = Message.objects.create(
            chat=target_chat,
            sender=request.user,
            text=source.text,
            forwarded_from=origin,
            forwarded_from_name=origin_name,
            forwarded_from_username=origin_username,
        )
        clone_attachments(source, forwarded)
        touch_chat(target_chat)
        ChatParticipant.objects.filter(chat=target_chat).update(is_archived=False)
        mark_chat_read(target_chat, request.user, forwarded)

    forwarded = _base_message_queryset(target_chat).get(pk=forwarded.pk)
    return JsonResponse(
        {
            "ok": True,
            "message": _serialized_message(forwarded, request.user, target_chat),
            "target_chat_id": target_chat.pk,
            "target_url": reverse("messenger:chat", args=[target_chat.pk]),
        }
    )


@login_required
@require_POST
def pin_message(request, chat_id, message_id):
    chat = _chat_for_user(request.user, chat_id)
    membership = _membership(chat, request.user)
    if (
        chat.type != Chat.Type.PRIVATE
        and membership.role not in {
            ChatParticipant.Role.OWNER,
            ChatParticipant.Role.ADMIN,
        }
    ):
        return JsonResponse(
            {"ok": False, "error": "Закреплять сообщения здесь могут только администраторы."},
            status=403,
        )
    message = get_object_or_404(chat.messages, pk=message_id, is_deleted=False)
    pin = PinnedMessage.objects.filter(chat=chat, message=message).first()
    if pin is None:
        PinnedMessage.objects.create(chat=chat, message=message, pinned_by=request.user)
        pinned = True
    else:
        pin.delete()
        pinned = False
    return JsonResponse({"ok": True, "pinned": pinned, "pins": serialize_pins(chat)})


@login_required
@require_GET
@rate_limit("search_messages")
def search_messages(request, chat_id):
    chat = _chat_for_user(request.user, chat_id)
    query = request.GET.get("q", "").strip()[:120]
    if not query:
        return JsonResponse({"ok": True, "results": []})

    base = _base_message_queryset(chat).filter(is_deleted=False)
    if connection.vendor == "postgresql":
        from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector

        search_query = SearchQuery(query, config="simple", search_type="websearch")
        search_vector = SearchVector("text", config="simple")
        results = list(
            base.annotate(
                search_document=search_vector,
                search_rank=SearchRank(search_vector, search_query),
            )
            .filter(
                Q(search_document=search_query)
                | Q(attachments__original_name__icontains=query)
            )
            .distinct()
            .order_by("-search_rank", "-id")[:50]
        )
    else:
        results = list(
            base.filter(
                Q(text__icontains=query)
                | Q(attachments__original_name__icontains=query)
            )
            .distinct()
            .order_by("-id")[:50]
        )
    return JsonResponse(
        {
            "ok": True,
            "results": [
                {
                    "id": message.pk,
                    "sender_name": message.sender.display_name,
                    "preview": message.preview[:220],
                    "time": timezone.localtime(message.created_at).strftime("%d.%m.%Y %H:%M"),
                    "url": f"{reverse('messenger:chat', args=[chat.pk])}?message={message.pk}#message-{message.pk}",
                }
                for message in results
            ],
        }
    )


@login_required
@require_POST
def chat_action(request, chat_id):
    chat = _chat_for_user(request.user, chat_id)
    membership = _membership(chat, request.user)
    action = request.POST.get("action", "")

    if action == "pin":
        membership.is_pinned = not membership.is_pinned
        membership.save(update_fields=("is_pinned",))
        messages.success(request, "Чат закреплён." if membership.is_pinned else "Чат откреплён.")
    elif action == "mute":
        membership.is_muted = not membership.is_muted
        membership.save(update_fields=("is_muted",))
        messages.success(request, "Уведомления выключены." if membership.is_muted else "Уведомления включены.")
    elif action == "archive":
        membership.is_archived = not membership.is_archived
        membership.save(update_fields=("is_archived",))
        messages.success(request, "Чат перенесён в архив." if membership.is_archived else "Чат возвращён из архива.")
        if membership.is_archived:
            return redirect(f"{reverse('messenger:home')}?archived=1")
        return redirect("messenger:home")
    elif action == "clear":
        if (
            chat.type != Chat.Type.PRIVATE
            and membership.role not in {
                ChatParticipant.Role.OWNER,
                ChatParticipant.Role.ADMIN,
            }
        ):
            messages.error(request, "Очищать историю здесь могут только администраторы.")
            return redirect("messenger:chat", chat_id=chat.pk)
        with transaction.atomic():
            for message in _base_message_queryset(chat).filter(is_deleted=False):
                delete_message_content(message)
            PinnedMessage.objects.filter(chat=chat).delete()
            ChatParticipant.objects.filter(chat=chat).update(
                last_read_message=None,
                draft_text="",
                draft_updated_at=None,
                last_typing_at=None,
            )
        messages.success(
            request,
            "История чата очищена для всех."
            if chat.type != Chat.Type.PRIVATE
            else "История переписки очищена.",
        )
    else:
        messages.error(request, "Неизвестное действие с чатом.")

    return redirect("messenger:chat", chat_id=chat.pk)


@login_required
@require_POST
def save_draft(request, chat_id):
    chat = _chat_for_user(request.user, chat_id)
    text = request.POST.get("text", "")
    if len(text) > 4096:
        return JsonResponse({"ok": False, "error": "Черновик слишком длинный."}, status=400)
    ChatParticipant.objects.filter(chat=chat, user=request.user).update(
        draft_text=text,
        draft_updated_at=timezone.now() if text else None,
    )
    return JsonResponse({"ok": True})


@login_required
@require_POST
@rate_limit("typing")
def typing(request, chat_id):
    chat = _chat_for_user(request.user, chat_id)
    ChatParticipant.objects.filter(chat=chat, user=request.user).update(last_typing_at=timezone.now())
    return JsonResponse({"ok": True})


def _attachment_for_user(user, attachment_id):
    return get_object_or_404(
        MessageAttachment.objects.select_related("message", "message__chat"),
        pk=attachment_id,
        message__chat__participants=user,
        message__is_deleted=False,
    )


INLINE_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".m4v": "video/x-m4v",
}


@login_required
@require_GET
def view_attachment(request, attachment_id):
    attachment = _attachment_for_user(request.user, attachment_id)
    if attachment.kind not in {
        MessageAttachment.Kind.IMAGE,
        MessageAttachment.Kind.VIDEO,
    }:
        return JsonResponse({"ok": False, "error": "Вложение нельзя открыть inline."}, status=404)

    extension = Path(attachment.original_name).suffix.lower()
    content_type = INLINE_MEDIA_TYPES.get(extension)
    if content_type is None:
        return JsonResponse({"ok": False, "error": "Неподдерживаемый тип медиа."}, status=404)

    attachment.file.open("rb")
    return FileResponse(
        attachment.file,
        as_attachment=False,
        filename=Path(attachment.original_name).name or "media",
        content_type=content_type,
    )


@login_required
@require_GET
def download_attachment(request, attachment_id):
    attachment = _attachment_for_user(request.user, attachment_id)
    attachment.file.open("rb")
    return FileResponse(
        attachment.file,
        as_attachment=True,
        filename=Path(attachment.original_name).name or "file",
        content_type="application/octet-stream",
    )


@login_required
@require_GET
def poll_messages(request, chat_id):
    chat = _chat_for_user(request.user, chat_id)
    try:
        after_id = max(0, int(request.GET.get("after", "0")))
    except (TypeError, ValueError):
        after_id = 0

    now = timezone.now()
    since = parse_datetime(request.GET.get("since", ""))
    if since is None:
        since = now
    elif timezone.is_naive(since):
        since = timezone.make_aware(since, timezone.get_current_timezone())

    base = _base_message_queryset(chat)
    new_messages = list(
        base.filter(id__gt=after_id, is_deleted=False).order_by("id")[:100]
    )
    if new_messages:
        mark_chat_read(chat, request.user, new_messages[-1])

    updated_messages = list(
        base.filter(id__lte=after_id, updated_at__gt=since)
        .order_by("updated_at", "id")[:100]
    )
    high_watermark = chat.messages.order_by("-id").values_list("id", flat=True).first() or after_id
    other_last_read_id = (
        _other_last_read_id(chat, request.user)
        if chat.type == Chat.Type.PRIVATE
        else 0
    )
    pinned_ids = set(
        PinnedMessage.objects.filter(chat=chat, message__is_deleted=False)
        .values_list("message_id", flat=True)
    )

    if chat.type == Chat.Type.PRIVATE:
        other_membership = _other_membership(chat, request.user)
        other_typing = bool(
            other_membership
            and other_membership.last_typing_at
            and other_membership.last_typing_at >= now - timedelta(seconds=5)
        )
        other_user = other_user_for_chat(chat, request.user)
        other_status = (
            "Личное облако"
            if chat.direct_key == f"self:{request.user.pk}"
            else _presence_text(other_user)
        )
    else:
        other_typing = False
        _decorate_chat_ui(chat, request.user)
        other_status = chat.status_ui

    return JsonResponse(
        {
            "ok": True,
            "messages": [
                serialize_message(
                    message,
                    request.user,
                    other_last_read_id=other_last_read_id,
                    pinned_ids=pinned_ids,
                )
                for message in new_messages
            ],
            "updates": [
                serialize_message(
                    message,
                    request.user,
                    other_last_read_id=other_last_read_id,
                    pinned_ids=pinned_ids,
                )
                for message in updated_messages
            ],
            "high_watermark": high_watermark,
            "other_last_read_id": other_last_read_id,
            "other_typing": other_typing,
            "other_status": other_status,
            "pins": serialize_pins(chat),
            "server_time": now.isoformat(),
        }
    )
