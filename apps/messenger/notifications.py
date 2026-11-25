"""Content-free, paginated notification polling and unread counts."""
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import BigIntegerField, F, Q, Value
from django.db.models.functions import Coalesce, Greatest
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET

from .markdown import mentioned_usernames
from .models import Chat, Message

PAGE_SIZE = 100


def unread_messages(user, now, *, audible=False):
    mute = (Q(chat__memberships__is_muted=False) | Q(chat__memberships__muted_until__lte=now)) if audible else Q()
    return Message.objects.filter(
        mute,
        Q(expires_at__isnull=True) | Q(expires_at__gt=now),
        Q(chat__type=Chat.Type.PRIVATE)
        | Q(chat__history_visible_to_new_members=True)
        | Q(chat__memberships__can_see_pre_join_history=True)
        | Q(created_at__gte=F("chat__memberships__joined_at")),
        chat__memberships__user=user,
        chat__memberships__is_hidden=False,
        is_deleted=False,
        id__gt=Greatest(
            F("chat__memberships__read_through_id"),
            F("chat__memberships__cleared_before_message_id"),
            Coalesce(F("chat__memberships__last_read_message_id"), Value(0, output_field=BigIntegerField())),
            output_field=BigIntegerField(),
        ),
    ).exclude(sender=user).exclude(hidden_for_users__user=user)


@login_required
@require_GET
def poll_sound_notifications(request):
    account_id = request.GET.get("account_id")
    if account_id is not None and account_id != str(request.user.pk):
        return JsonResponse({"ok": False, "error": "Аккаунт изменился."}, status=409)
    now = timezone.now()
    try:
        since = parse_datetime(request.GET.get("since", ""))
        if since is not None and timezone.is_naive(since):
            since = None
        after_id = int(request.GET.get("after_id", "0"))
        if not 0 <= after_id <= 9223372036854775807:
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        since, after_id = None, 0

    base = unread_messages(request.user, now)
    items = []
    has_more = False
    next_since, next_after_id = now, 0
    if since is not None and since <= now:
        # No backlog alert older than 30 seconds. Within that window, page
        # oldest first so a large burst never silently discards older alerts.
        lower_bound = now - timedelta(seconds=30)
        if since < lower_bound:
            since, after_id = lower_bound, 0
        rows = list(
            unread_messages(request.user, now, audible=True).filter(
                Q(created_at__gt=since) | Q(created_at=since, pk__gt=after_id),
                silent=False, created_at__lte=now,
            ).order_by("created_at", "pk")
            .values_list("pk", "chat_id", "created_at", "text", "reply_to__sender_id")[:PAGE_SIZE + 1]
        )
        has_more = len(rows) > PAGE_SIZE
        rows = rows[:PAGE_SIZE]
        username = request.user.username.casefold()
        for pk, chat_id, created_at, text, reply_sender_id in rows:
            kind = "reply" if reply_sender_id == request.user.pk else (
                "mention" if "@" in text and username in text.casefold()
                and username in mentioned_usernames(text) else "message"
            )
            items.append({"id": pk, "chat_id": chat_id, "kind": kind})
        if has_more:
            next_since, next_after_id = rows[-1][2], rows[-1][0]
        else:
            next_since = max(since, now - timedelta(seconds=5))
            next_after_id = after_id if next_since == since else 0

    payload = {
        "ok": True, "ids": [item["id"] for item in items], "items": items,
        "server_time": now.isoformat(), "account_id": request.user.pk,
        "next_since": next_since.isoformat(), "next_after_id": next_after_id, "has_more": has_more,
    }
    if request.GET.get("include_unread") == "1":
        payload["unread_count"] = base.count()
    response = JsonResponse(payload)
    response["Cache-Control"] = "private, no-store"
    return response
