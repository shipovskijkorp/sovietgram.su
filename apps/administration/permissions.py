from functools import wraps

from django.contrib.auth import HASH_SESSION_KEY
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.utils.crypto import constant_time_compare
from django.views.decorators.cache import never_cache
from django.contrib.auth.decorators import login_required

from apps.accounts.models import User

ROLES = {
    User.PlatformRole.MODERATOR: frozenset({"dashboard", "reports"}),
    User.PlatformRole.ADMIN: frozenset({"dashboard", "reports", "users", "communities", "audit", "operations"}),
    User.PlatformRole.OWNER: frozenset({"dashboard", "reports", "users", "communities", "audit", "roles", "operations"}),
}


def permits(user, permission):
    return user.is_authenticated and user.is_active and not user.platform_suspended_at and permission in ROLES.get(user.platform_role, ())


def check_locked_actor(request, actor, permission):
    if not permits(actor, permission) or not actor.two_factor_enabled or not constant_time_compare(
        str(request.session.get(HASH_SESSION_KEY, "")), actor.get_session_auth_hash()
    ):
        raise PermissionDenied


def panel_permission(permission):
    def decorate(view):
        @login_required
        @never_cache
        @wraps(view)
        def guarded(request, *args, **kwargs):
            if not permits(request.user, permission):
                raise PermissionDenied
            if not request.user.two_factor_enabled:
                if request.method != "GET":
                    raise PermissionDenied
                return redirect("accounts:two_factor")
            response = view(request, *args, **kwargs)
            response["X-Robots-Tag"] = "noindex, nofollow"
            return response
        return guarded
    return decorate
