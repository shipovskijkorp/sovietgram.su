"""Lightweight, content-free in-app sound notification polling."""
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import BigIntegerField, F, Q, Value
from django.db.models.functions import Coalesce, Greatest
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET

from .models import Chat, Message


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
    except (ValueError, TypeError, OverflowError):
        since = None
    items = []
    if since is not None and since <= now:
        # No backlog alert on open/reconnect. Overlap is deduplicated in
        # the browser; routing metadata contains no private message text.
        since = max(since, now - timedelta(seconds=30))
        rows = list(
            Message.objects.filter(
                Q(expires_at__isnull=True) | Q(expires_at__gt=now),
                Q(chat__memberships__is_muted=False)
                | Q(chat__memberships__muted_until__lte=now),
                Q(chat__type=Chat.Type.PRIVATE)
                | Q(chat__history_visible_to_new_members=True)
                | Q(chat__memberships__can_see_pre_join_history=True)
                | Q(created_at__gte=F("chat__memberships__joined_at")),
                chat__memberships__user=request.user,
                chat__memberships__is_hidden=False,
                is_deleted=False, silent=False,
                created_at__gt=since, created_at__lte=now,
                id__gt=Greatest(
                    F("chat__memberships__read_through_id"),
                    F("chat__memberships__cleared_before_message_id"),
                    Coalesce(F("chat__memberships__last_read_message_id"), Value(0, output_field=BigIntegerField())),
                    output_field=BigIntegerField(),
                ),
            ).exclude(sender=request.user).exclude(hidden_for_users__user=request.user)
            .order_by("-created_at", "-pk").values_list("pk", "chat_id")[:100]
        )
        items = [{"id": pk, "chat_id": chat_id} for pk, chat_id in rows]
    response = JsonResponse({"ok": True, "ids": [item["id"] for item in items], "items": items,
                             "server_time": now.isoformat(), "account_id": request.user.pk})
    response["Cache-Control"] = "private, no-store"
    return response
