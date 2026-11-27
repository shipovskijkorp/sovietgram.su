"""Local QR cards: private invitations require current admin rights."""
import base64
from io import BytesIO

import qrcode
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from apps.messenger.community_permissions import has_admin_right, is_banned
from apps.messenger.models import Chat, ChatInviteLink, ChatParticipant
from apps.messenger.ratelimit import rate_limit


def _card(request, *, title, path, note):
    origin = settings.SOVIETGRAM_PUBLIC_URL
    url = origin.rstrip("/") + path if origin else request.build_absolute_uri(path)
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    stream = BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(stream, format="PNG")
    response = render(request, "accounts/share_qr.html", {
        "title": title, "share_url": url, "note": note,
        "qr_png": "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii"),
    })
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


@never_cache
@require_GET
@rate_limit("share_qr")
def profile_qr(request, username):
    user = get_object_or_404(get_user_model(), username__iexact=username, is_active=True)
    return _card(request, title="@" + user.username,
                 path=reverse("accounts:public_profile", args=[user.username]),
                 note="Отсканируйте код, чтобы открыть профиль в Sovietgram.")


@never_cache
@login_required
@require_GET
@rate_limit("share_qr")
def invite_qr(request, chat_id, invite_id):
    member = ChatParticipant.objects.select_related("chat").filter(
        chat_id=chat_id, user=request.user, is_hidden=False,
        chat__type__in=(Chat.Type.GROUP, Chat.Type.CHANNEL),
    ).first()
    if not has_admin_right(member, "invite_users") or is_banned(member.chat, request.user.pk):
        raise Http404
    invite = get_object_or_404(ChatInviteLink, pk=invite_id, chat_id=chat_id)
    if not invite.is_active:
        raise Http404
    return _card(request, title=member.chat.title,
                 path=reverse("messenger:join_invite", args=[invite.token]),
                 note="Код содержит действующую ссылку-приглашение. Передавайте его только тем, кого хотите пригласить.")
