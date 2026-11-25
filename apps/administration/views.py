from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404, HttpResponseBadRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from apps.accounts.models import User
from apps.messenger.models import Chat, ChatInviteLink, ChatJoinRequest, ChatParticipant, Message
from apps.messenger.community_permissions import is_banned
from apps.messenger.services import delete_message_content

from .models import PlatformAudit, PlatformReport
from .permissions import check_locked_actor, panel_permission, permits

COLLECTIVES = (Chat.Type.GROUP, Chat.Type.CHANNEL)
MAX_ID = 9223372036854775807


def panel(request, screen, **context):
    return render(request, "administration/panel.html", {
        "screen": screen,
        "can_users": permits(request.user, "users"),
        "can_communities": permits(request.user, "communities"),
        "can_audit": permits(request.user, "audit"),
        "can_roles": permits(request.user, "roles"),
        **context,
    })


def page(request, queryset):
    return Paginator(queryset, 40).get_page(request.GET.get("page", 1))


def query_text(request):
    return request.GET.get("q", "").strip()[:150]


def log(actor, action, kind, pk, label, reason):
    PlatformAudit.objects.create(actor=actor, actor_label=actor.username, action=action,
        target_kind=kind, target_id=pk, target_label=str(label)[:180], reason=reason[:300])


def post_reason(request):
    if request.POST.get("account_id") != str(request.user.pk):
        return None
    reason = request.POST.get("reason", "").strip()
    return reason if 1 <= len(reason) <= 300 else None


def ordinary(user):
    return not (user.platform_role or user.is_staff or user.is_superuser)


def valid_id(pk):
    if not 0 < pk <= MAX_ID:
        raise Http404


@panel_permission("dashboard")
@require_GET
def dashboard(request):
    now = timezone.now()
    metrics = [
        ("Открытые жалобы", PlatformReport.objects.filter(status="open").count()),
        ("Решённые жалобы", PlatformReport.objects.filter(status="resolved").count()),
    ]
    if permits(request.user, "users"):
        metrics += [
            ("Аккаунты", User.objects.count()),
            ("Активные за 24 ч", User.objects.filter(is_active=True, last_seen_at__gte=now-timedelta(days=1)).count()),
            ("Заблокированные", User.objects.filter(platform_suspended_at__isnull=False).count()),
            ("Группы", Chat.objects.filter(type=Chat.Type.GROUP).count()),
            ("Каналы", Chat.objects.filter(type=Chat.Type.CHANNEL).count()),
            ("Административные аккаунты", User.objects.exclude(platform_role="").count()),
        ]
    return panel(request, "dashboard", metrics=metrics, recent=PlatformReport.objects.filter(status="open")[:8])


@panel_permission("users")
@require_GET
def users(request):
    q = query_text(request)
    status = request.GET.get("status", "")
    rows = User.objects.order_by("-pk")
    if q:
        condition = Q(username__icontains=q.lstrip("@")) | Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__iexact=q)
        if q.isascii() and q.isdigit() and len(q) < 19:
            condition |= Q(pk=int(q))
        rows = rows.filter(condition)
    if status == "suspended":
        rows = rows.filter(platform_suspended_at__isnull=False)
    elif status == "active":
        rows = rows.filter(is_active=True)
    elif status == "admin":
        rows = rows.exclude(platform_role="")
    elif status == "inactive":
        rows = rows.filter(is_active=False, platform_suspended_at__isnull=True)
    return panel(request, "users", rows=page(request, rows), q=q, status=status)


@panel_permission("users")
@require_GET
def user_detail(request, pk):
    valid_id(pk)
    target = get_object_or_404(User, pk=pk)
    return panel(request, "user", target=target, ordinary=ordinary(target),
        can_assign=permits(request.user, "roles") and target.pk != request.user.pk and target.platform_role != "owner" and not target.is_staff and not target.is_superuser,
        reports_count=PlatformReport.objects.filter(kind="user", target_id=pk).count())


@panel_permission("users")
@require_POST
@transaction.atomic
def user_action(request, pk):
    valid_id(pk)
    reason = post_reason(request)
    if reason is None:
        return HttpResponseBadRequest("Укажите причину и проверьте активный аккаунт.")
    locked = {row.pk: row for row in User.objects.select_for_update().filter(pk__in={pk, request.user.pk}).order_by("pk")}
    actor, target = locked.get(request.user.pk), locked.get(pk)
    if not actor or not target:
        raise Http404
    check_locked_actor(request, actor, "users")
    action = request.POST.get("action")
    if actor.pk == target.pk:
        raise PermissionDenied
    fields = ["security_version"]
    if action == "role":
        check_locked_actor(request, actor, "roles")
        role = request.POST.get("role", "")
        if role not in {"", "admin", "moderator"} or target.platform_role == "owner" or target.is_staff or target.is_superuser:
            raise PermissionDenied
        if role and (not target.is_active or target.platform_suspended_at or not target.two_factor_enabled):
            return HttpResponseBadRequest("Для административной роли необходим активный аккаунт с 2FA.")
        previous = target.platform_role or "member"
        if target.platform_role == role:
            return redirect("administration:user_detail", pk=pk)
        target.platform_role = role
        fields.append("platform_role")
        reason = f"{previous} -> {role or 'member'}: {reason}"
    else:
        if not ordinary(target):
            raise PermissionDenied
        if action == "suspend":
            if not target.is_active or target.platform_suspended_at:
                return HttpResponseBadRequest("Аккаунт уже неактивен.")
            target.is_active = False
            target.platform_suspended_at = timezone.now()
            target.platform_suspension_reason = reason
            fields += ["is_active", "platform_suspended_at", "platform_suspension_reason"]
        elif action == "restore":
            if not target.platform_suspended_at:
                return HttpResponseBadRequest("Аккаунт не был заблокирован платформой.")
            target.is_active = True
            target.platform_suspended_at = None
            target.platform_suspension_reason = ""
            fields += ["is_active", "platform_suspended_at", "platform_suspension_reason"]
        elif action == "revoke_sessions":
            if not target.is_active:
                return HttpResponseBadRequest("Аккаунт неактивен.")
        else:
            return HttpResponseBadRequest("Неизвестное действие.")
    target.security_version += 1
    target.save(update_fields=fields)
    log(actor, action, "user", target.pk, target.username, reason)
    messages.success(request, "Изменения сохранены. Прежние сеансы аккаунта аннулированы.")
    return redirect("administration:user_detail", pk=pk)


@panel_permission("communities")
@require_GET
def communities(request):
    q = query_text(request)
    status = request.GET.get("status", "")
    rows = Chat.objects.filter(type__in=COLLECTIVES).annotate(member_count=Count("memberships")).order_by("-pk")
    if q:
        condition = Q(title__icontains=q) | Q(username__icontains=q.lstrip("@"))
        if q.isascii() and q.isdigit() and len(q) < 19:
            condition |= Q(pk=int(q))
        rows = rows.filter(condition)
    if status == "group" or status == "channel":
        rows = rows.filter(type=status)
    elif status == "restricted":
        rows = rows.filter(platform_public_restricted=True)
    return panel(request, "communities", rows=page(request, rows), q=q, status=status)


@panel_permission("communities")
@require_GET
def community_detail(request, pk):
    valid_id(pk)
    target = get_object_or_404(Chat, pk=pk, type__in=COLLECTIVES)
    return panel(request, "community", target=target, member_count=target.memberships.count(),
        owners=target.memberships.filter(role="owner").select_related("user")[:10],
        invite_count=target.invite_links.filter(revoked_at__isnull=True).count())


@panel_permission("communities")
@require_POST
@transaction.atomic
def community_action(request, pk):
    valid_id(pk)
    reason = post_reason(request)
    if reason is None:
        return HttpResponseBadRequest("Укажите причину и проверьте аккаунт.")
    actor = get_object_or_404(User.objects.select_for_update(), pk=request.user.pk)
    check_locked_actor(request, actor, "communities")
    target = get_object_or_404(Chat.objects.select_for_update(), pk=pk, type__in=COLLECTIVES)
    action = request.POST.get("action")
    if action == "restrict_public":
        if not target.platform_public_restricted:
            target.platform_public_restricted = True
            target.username = None
            target.save(update_fields=["platform_public_restricted", "username", "updated_at"])
        else:
            return redirect("administration:community_detail", pk=pk)
    elif action == "restore_public":
        if not target.platform_public_restricted:
            return redirect("administration:community_detail", pk=pk)
        target.platform_public_restricted = False
        target.save(update_fields=["platform_public_restricted", "updated_at"])
    elif action == "revoke_invites":
        now = timezone.now()
        ChatInviteLink.objects.filter(chat=target, revoked_at__isnull=True).update(revoked_at=now)
        ChatJoinRequest.objects.filter(chat=target, status="pending").update(status="rejected", decided_at=now, decided_by=actor)
    else:
        return HttpResponseBadRequest("Неизвестное действие.")
    log(actor, action, "community", target.pk, target.title, reason)
    messages.success(request, "Изменения сохранены.")
    return redirect("administration:community_detail", pk=pk)


def visible_target(request, kind, pk):
    valid_id(pk)
    if kind == "user":
        target = get_object_or_404(User, pk=pk, is_active=True)
        if target.pk == request.user.pk:
            raise Http404
        return target, "@" + target.username
    if kind == "community":
        target = get_object_or_404(Chat, pk=pk, type__in=COLLECTIVES)
        if not target.username and not target.memberships.filter(user=request.user, is_hidden=False).exists():
            raise Http404
        return target, target.title or "Сообщество"
    if kind == "message":
        from apps.messenger.views import _visible_message_queryset
        message = get_object_or_404(Message.objects.select_related("chat", "sender"), pk=pk, is_deleted=False)
        if message.sender_id == request.user.pk or not message.chat.memberships.filter(user=request.user, is_hidden=False).exists() or is_banned(message.chat, request.user.pk):
            raise Http404
        target = get_object_or_404(_visible_message_queryset(message.chat, request.user), pk=pk, is_deleted=False)
        return target, f"Сообщение #{pk} от @{target.sender.username}"
    raise Http404


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def submit_report(request, kind, pk):
    target, label = visible_target(request, kind, pk)
    error = ""
    if request.method == "POST":
        if request.POST.get("account_id") != str(request.user.pk):
            return HttpResponse("Аккаунт изменился.", status=409)
        reason = request.POST.get("reason", "")
        details = request.POST.get("details", "").strip()
        if reason not in PlatformReport.Reason.values or len(details) > 1000:
            error = "Проверьте причину и описание."
        else:
            with transaction.atomic():
                actor = get_object_or_404(User.objects.select_for_update(), pk=request.user.pk, is_active=True)
                target, label = visible_target(request, kind, pk)
                existing = PlatformReport.objects.filter(reporter=actor, kind=kind, target_id=pk, status="open").first()
                if existing:
                    return redirect("administration:my_reports")
                if PlatformReport.objects.filter(reporter=actor, created_at__gte=timezone.now()-timedelta(hours=1)).count() >= 10:
                    return HttpResponse("Лимит жалоб: 10 за час.", status=429)
                PlatformReport.objects.create(reporter=actor, kind=kind, target_id=pk, target_label=label[:180], reason=reason, details=details)
            messages.success(request, "Жалоба отправлена.")
            return redirect("administration:my_reports")
    return render(request, "administration/report.html", {
        "label":label, "kind":kind, "reasons":PlatformReport.Reason.choices, "error":error,
    }, status=400 if error else 200)


@login_required
@never_cache
@require_GET
def my_reports(request):
    return render(request, "administration/my_reports.html", {
        "rows":page(request, PlatformReport.objects.filter(reporter=request.user).order_by("-pk")),
    })


@panel_permission("reports")
@require_GET
def reports(request):
    status = request.GET.get("status", "open")
    rows = PlatformReport.objects.select_related("reporter", "decided_by").order_by("-pk")
    if status in PlatformReport.Status.values:
        rows = rows.filter(status=status)
    return panel(request, "reports", rows=page(request, rows), status=status)


@panel_permission("reports")
@require_GET
def report_detail(request, pk):
    valid_id(pk)
    report = get_object_or_404(PlatformReport.objects.select_related("reporter", "decided_by"), pk=pk)
    evidence = None
    if report.kind == "message" and report.status == "open":
        evidence = Message.objects.filter(pk=report.target_id, is_deleted=False).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
        ).select_related("sender").first()
    return panel(request, "report", report=report, evidence=evidence)


@panel_permission("reports")
@require_POST
@transaction.atomic
def report_action(request, pk):
    valid_id(pk)
    reason = post_reason(request)
    if reason is None:
        return HttpResponseBadRequest("Укажите причину и проверьте аккаунт.")
    actor = get_object_or_404(User.objects.select_for_update(), pk=request.user.pk)
    check_locked_actor(request, actor, "reports")
    report = get_object_or_404(PlatformReport.objects.select_for_update(), pk=pk)
    if report.status != "open":
        return HttpResponse("Жалоба уже рассмотрена.", status=409)
    action = request.POST.get("action")
    if action == "delete_message":
        if report.kind != "message":
            return HttpResponseBadRequest("Жалоба не на сообщение.")
        chat_id = Message.objects.filter(pk=report.target_id).values_list("chat_id", flat=True).first()
        if not chat_id:
            return HttpResponse("Сообщение уже недоступно.", status=409)
        get_object_or_404(Chat.objects.select_for_update(), pk=chat_id)
        message = get_object_or_404(Message.objects.select_for_update(), pk=report.target_id, chat_id=chat_id, is_deleted=False)
        if message.expires_at and message.expires_at <= timezone.now():
            return HttpResponse("Сообщение уже недоступно.", status=409)
        if request.POST.get("revision") != str(message.sync_revision):
            return HttpResponse("Сообщение изменилось. Откройте жалобу заново перед удалением.", status=409)
        delete_message_content(message)
        log(actor, "delete_reported_message", "message", message.pk, report.target_label, reason)
        report.status = "resolved"
    elif action in {"resolved", "dismissed"}:
        report.status = action
    else:
        return HttpResponseBadRequest("Неизвестное действие.")
    report.decided_at = timezone.now()
    report.decided_by = actor
    report.decision = reason
    report.save(update_fields=["status", "decided_at", "decided_by", "decision"])
    log(actor, "report_" + report.status, "report", report.pk, report.target_label, reason)
    messages.success(request, "Жалоба рассмотрена.")
    return redirect("administration:report_detail", pk=pk)


@panel_permission("audit")
@require_GET
def audit(request):
    return panel(request, "audit", rows=page(request, PlatformAudit.objects.order_by("-pk")))
