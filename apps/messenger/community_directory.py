"""Authenticated directory of already-public communities."""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Exists, OuterRef, Q
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .models import Chat, ChatMemberModeration, ChatParticipant, community_search_key
from .ratelimit import rate_limit


@login_required
@never_cache
@require_GET
@rate_limit("community_directory")
def community_directory(request):
    query = request.GET.get("q", "").strip()[:120]
    kind = request.GET.get("kind", "all")
    sort = request.GET.get("sort", "popular")
    if kind not in {"all", Chat.Type.GROUP, Chat.Type.CHANNEL}:
        kind = "all"
    if sort not in {"popular", "new", "active"}:
        sort = "popular"
    membership = ChatParticipant.objects.filter(chat_id=OuterRef("pk"), user=request.user, is_hidden=False)
    bans = ChatMemberModeration.objects.filter(
        chat_id=OuterRef("pk"), user=request.user, banned=True,
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
    chats = Chat.objects.filter(type__in=(Chat.Type.GROUP, Chat.Type.CHANNEL),
                                platform_public_restricted=False).exclude(username__isnull=True).exclude(username="")
    chats = chats.exclude(Exists(bans))
    if kind != "all":
        chats = chats.filter(type=kind)
    for word in community_search_key(query.lstrip("@")).split()[:10]:
        chats = chats.filter(directory_search_key__contains=word)
    chats = chats.annotate(
        joined=Exists(membership),
        directory_members=Count("memberships", filter=Q(
            memberships__is_hidden=False, memberships__user__is_active=True,
            memberships__user__platform_suspended_at__isnull=True,
        )),
    )
    ordering = {"popular": ("-directory_members", "-pk"), "new": ("-created_at", "-pk"), "active": ("-updated_at", "-pk")}
    page = Paginator(chats.order_by(*ordering[sort]), 20).get_page(request.GET.get("page"))
    response = render(request, "messenger/community_directory.html",
                      {"page": page, "query": query, "kind": kind, "sort": sort})
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Referrer-Policy"] = "no-referrer"
    return response
