from django.contrib.auth import (
    BACKEND_SESSION_KEY,
    HASH_SESSION_KEY,
    SESSION_KEY,
    get_user_model,
)
from django.utils.crypto import constant_time_compare
from django.middleware.csrf import rotate_token


MULTI_ACCOUNT_KEY = "sovietgram_accounts_v1"
MAX_ACCOUNTS = 8


def _entry(user, backend):
    return {
        "user_id": str(user.pk),
        "backend": backend,
        "session_hash": user.get_session_auth_hash(),
    }


def _raw_accounts(request):
    value = request.session.get(MULTI_ACCOUNT_KEY, [])
    return value if isinstance(value, list) else []


def _save_accounts(request, accounts):
    request.session[MULTI_ACCOUNT_KEY] = accounts[:MAX_ACCOUNTS]
    request.session.modified = True


def remember_current_account(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return
    backend = request.session.get(BACKEND_SESSION_KEY)
    if not backend:
        return
    accounts = [
        item for item in _raw_accounts(request)
        if str(item.get("user_id")) != str(request.user.pk)
    ]
    accounts.insert(0, _entry(request.user, backend))
    _save_accounts(request, accounts)


def account_slots(request):
    User = get_user_model()
    current_id = str(request.user.pk) if request.user.is_authenticated else None
    entries = _raw_accounts(request)
    ids = [item.get("user_id") for item in entries if item.get("user_id")]
    users = {
        str(user.pk): user
        for user in User.objects.filter(pk__in=ids, is_active=True)
    }

    cleaned = []
    slots = []
    changed = False
    for item in entries:
        user_id = str(item.get("user_id", ""))
        user = users.get(user_id)
        backend = item.get("backend")
        stored_hash = item.get("session_hash", "")
        if not user or not backend:
            changed = True
            continue

        if user_id == current_id:
            stored_hash = user.get_session_auth_hash()
            item = _entry(user, backend)
        elif not constant_time_compare(stored_hash, user.get_session_auth_hash()):
            changed = True
            continue

        cleaned.append(item)
        slots.append(
            {
                "user": user,
                "is_current": user_id == current_id,
            }
        )

    if request.user.is_authenticated and current_id not in {
        str(item.get("user_id")) for item in cleaned
    }:
        backend = request.session.get(BACKEND_SESSION_KEY)
        if backend:
            current = _entry(request.user, backend)
            cleaned.insert(0, current)
            slots.insert(0, {"user": request.user, "is_current": True})
            changed = True

    if changed:
        _save_accounts(request, cleaned)
    return slots


def activate_account(request, user_id):
    User = get_user_model()
    for item in _raw_accounts(request):
        if str(item.get("user_id")) != str(user_id):
            continue
        user = User.objects.filter(pk=user_id, is_active=True).first()
        if not user:
            break
        if not constant_time_compare(
            item.get("session_hash", ""),
            user.get_session_auth_hash(),
        ):
            break

        request.session[SESSION_KEY] = str(user.pk)
        request.session[BACKEND_SESSION_KEY] = item["backend"]
        request.session[HASH_SESSION_KEY] = item["session_hash"]
        request.session.cycle_key()
        request.user = user
        rotate_token(request)
        remember_current_account(request)
        return user
    return None


def add_authenticated_account(request, user, backend):
    remember_current_account(request)
    accounts = [
        item for item in _raw_accounts(request)
        if str(item.get("user_id")) != str(user.pk)
    ]
    accounts.insert(0, _entry(user, backend))
    _save_accounts(request, accounts)
    return activate_account(request, user.pk)


def remove_current_account(request):
    current_id = str(request.user.pk) if request.user.is_authenticated else None
    accounts = [
        item for item in _raw_accounts(request)
        if str(item.get("user_id")) != current_id
    ]
    _save_accounts(request, accounts)
    if accounts:
        return activate_account(request, accounts[0]["user_id"])
    return None
