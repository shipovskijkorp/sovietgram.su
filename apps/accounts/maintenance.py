from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from .lifecycle import delete_user_account


def purge_inactive_accounts(*, now=None, exclude_user_id=None, limit=25):
    """Select only expired ordinary accounts; bound each maintenance run."""
    now = now or timezone.now()
    if limit <= 0:
        return 0
    candidates = get_user_model().objects.filter(
        is_active=True, platform_role="", is_staff=False, is_superuser=False,
        platform_suspended_at__isnull=True,
    )
    if exclude_user_id is not None:
        candidates = candidates.exclude(pk=exclude_user_id)
    # There are normally five configured inactivity choices. Respect older
    # or administrator-set durations as well (zero means the default year).
    durations = candidates.order_by().values_list("delete_after_inactive_days", flat=True).distinct()
    expired = Q(pk__in=[])
    for days in durations:
        cutoff = now - timedelta(days=int(days or 365))
        expired |= Q(delete_after_inactive_days=days) & (
            Q(last_seen_at__lte=cutoff) | Q(last_seen_at__isnull=True, date_joined__lte=cutoff)
        )
    ids = list(candidates.filter(expired).order_by("pk").values_list("pk", flat=True)[:limit])
    deleted = 0
    for user_id in ids:
        user = candidates.filter(pk=user_id).first()
        if user and delete_user_account(user, inactive_at=now):
            deleted += 1
    return deleted
