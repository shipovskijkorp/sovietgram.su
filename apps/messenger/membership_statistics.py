"""Membership analytics. Aggregate counts, no actor/user IDs or tokens."""
from datetime import timedelta

from django.db import transaction
from django.db.models import Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from .models import Chat, ChatInviteLink, ChatParticipant, CommunityMembershipEvent

Source = CommunityMembershipEvent.Source
JOIN_SOURCES = (
    Source.CREATED, Source.INITIAL_ADD, Source.MANUAL_ADD, Source.PUBLIC,
    Source.DIRECTORY, Source.INVITE, Source.APPROVAL,
)
LEAVE_SOURCES = (Source.LEAVE, Source.REMOVED, Source.BANNED, Source.ACCOUNT_DELETED)
RETENTION_DAYS = 90


def record_membership_event(chat, source, *, count=1, invite=None):
    if chat.type not in (Chat.Type.GROUP, Chat.Type.CHANNEL) or count <= 0:
        return
    if source not in (*JOIN_SOURCES, *LEAVE_SOURCES):
        raise ValueError("Invalid membership event")
    if invite is not None and (invite.chat_id != chat.pk or source not in (Source.INVITE, Source.APPROVAL)):
        raise ValueError("Invalid membership event invite")
    CommunityMembershipEvent.objects.create(
        chat=chat, source=source, count=count, invite_id=invite.pk if invite else None,
    )


@transaction.atomic
def leave_collective(chat_id, user_id):
    """Serialize a voluntary leave with role changes and other membership actions."""
    chat = Chat.objects.select_for_update().filter(
        pk=chat_id, type__in=(Chat.Type.GROUP, Chat.Type.CHANNEL),
    ).first()
    if chat is None:
        return "missing"
    membership = ChatParticipant.objects.select_for_update().filter(chat=chat, user_id=user_id).first()
    if membership is None:
        return "missing"
    if membership.role == ChatParticipant.Role.OWNER:
        return "owner"
    membership.delete()
    record_membership_event(chat, Source.LEAVE)
    return "left"


def membership_activity(chat_id, start, now, tz, *, include_invite_details=False):
    events = CommunityMembershipEvent.objects.filter(chat_id=chat_id, occurred_at__gte=start, occurred_at__lte=now)
    source_counts = dict(events.order_by().values("source").annotate(total=Sum("count")).values_list("source", "total"))
    joins = sum(source_counts.get(source, 0) for source in JOIN_SOURCES)
    leaves = sum(source_counts.get(source, 0) for source in LEAVE_SOURCES)
    daily = {}
    for day, source, count in (events.order_by().annotate(day=TruncDate("occurred_at", tzinfo=tz))
                               .values("day", "source").annotate(total=Sum("count")).values_list("day", "source", "total")):
        row = daily.setdefault(day, {"joins": 0, "leaves": 0})
        if source in JOIN_SOURCES:
            row["joins"] += count
        elif source in LEAVE_SOURCES:
            row["leaves"] += count
    invite_rows = []
    remaining_invites = 0
    if include_invite_details:
        invite_events = events.filter(source__in=(Source.INVITE, Source.APPROVAL), invite_id__isnull=False)
        top = list(invite_events.order_by().values("invite_id").annotate(total=Sum("count")).order_by("-total", "invite_id")[:20])
        names = dict(ChatInviteLink.objects.filter(chat_id=chat_id, pk__in=[row["invite_id"] for row in top])
                     .values_list("pk", "name"))
        for row in top:
            invite_id = row["invite_id"]
            invite_rows.append({"label": (names.get(invite_id) or "Ссылка") + " #" + str(invite_id),
                                "count": row["total"]})
        remaining_invites = max(0, (invite_events.aggregate(total=Sum("count"))["total"] or 0)
                                - sum(row["count"] for row in invite_rows))
    return {
        "recorded_joins": joins, "recorded_leaves": leaves, "recorded_net": joins - leaves,
        "join_sources": [{"source": source.value, "label": source.label, "count": source_counts.get(source, 0)}
                         for source in JOIN_SOURCES],
        "leave_sources": [{"source": source.value, "label": source.label, "count": source_counts.get(source, 0)}
                          for source in LEAVE_SOURCES],
        "invite_sources": invite_rows if include_invite_details else None,
        "other_invite_joins": remaining_invites,
    }, daily


def purge_membership_events(*, limit=5000, now=None):
    now = now or timezone.now()
    ids = list(CommunityMembershipEvent.objects.filter(occurred_at__lt=now - timedelta(days=RETENTION_DAYS))
               .order_by("occurred_at", "pk").values_list("pk", flat=True)[:limit])
    if not ids:
        return 0
    return CommunityMembershipEvent.objects.filter(pk__in=ids).delete()[0]
