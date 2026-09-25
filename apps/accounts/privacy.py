from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.db.models import Q
from django.utils import timezone

from .models import UserBlock


PRIVACY_OPTIONS = (
    ("everyone", "Все"),
    ("contacts", "Мои контакты"),
    ("nobody", "Никто"),
)
PRIVACY_OPTION_LABELS = dict(PRIVACY_OPTIONS)

PRIVACY_RULES = {
    "last_seen": {
        "title": "Время последней активности",
        "question": "Кто видит время моей последней активности?",
        "default": "everyone",
    },
    "profile_photo": {
        "title": "Фотография профиля",
        "question": "Кто видит мою фотографию профиля?",
        "default": "everyone",
    },
    "forwards": {
        "title": "Пересылка сообщений",
        "question": "Кто может добавлять ссылку на мой аккаунт при пересылке моих сообщений?",
        "default": "everyone",
    },
    "calls": {
        "title": "Звонки",
        "question": "Кто может мне звонить?",
        "default": "everyone",
    },
    "voice_messages": {
        "title": "Голосовые сообщения",
        "question": "Кто может отправлять мне голосовые и аудиосообщения?",
        "default": "everyone",
    },
    "messages": {
        "title": "Сообщения",
        "question": "Кто может отправлять мне личные сообщения?",
        "default": "everyone",
    },
    "birthday": {
        "title": "День рождения",
        "question": "Кто видит мой день рождения?",
        "default": "contacts",
    },
    "bio": {
        "title": "О себе",
        "question": "Кто видит раздел «О себе»?",
        "default": "everyone",
    },
    "invites": {
        "title": "Группы и каналы",
        "question": "Кто может добавлять меня в группы и каналы?",
        "default": "everyone",
    },
}

INACTIVITY_CHOICES = {
    30: "1 месяц",
    90: "3 месяца",
    180: "6 месяцев",
    365: "1 год",
    730: "2 года",
}

AUTO_DELETE_CHOICES = {
    0: "Выкл.",
    86400: "1 день",
    604800: "1 неделя",
    2592000: "1 месяц",
}


def _clean_ids(values):
    result = []
    seen = set()
    for raw in values or []:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value > 0 and value not in seen:
            seen.add(value)
            result.append(value)
    return result[:200]


def get_privacy_rule(user, key):
    meta = PRIVACY_RULES.get(key)
    if meta is None:
        raise KeyError(key)
    raw = (user.privacy_settings or {}).get(key)
    raw = raw if isinstance(raw, dict) else {}
    option = raw.get("option")
    if option not in PRIVACY_OPTION_LABELS:
        option = meta["default"]
    always = _clean_ids(raw.get("always"))
    never = _clean_ids(raw.get("never"))
    never_set = set(never)
    always = [value for value in always if value not in never_set]
    return {
        "option": option,
        "always": always,
        "never": never,
    }


def set_privacy_rule(user, key, option, always=None, never=None):
    if key not in PRIVACY_RULES:
        raise ValueError("Неизвестная настройка конфиденциальности.")
    if option not in PRIVACY_OPTION_LABELS:
        raise ValueError("Неизвестный вариант конфиденциальности.")

    always_ids = _clean_ids(always)
    never_ids = _clean_ids(never)
    own_id = int(user.pk)
    always_ids = [value for value in always_ids if value != own_id]
    never_ids = [value for value in never_ids if value != own_id]
    never_set = set(never_ids)
    always_ids = [value for value in always_ids if value not in never_set]

    User = get_user_model()
    existing = set(
        User.objects.filter(
            pk__in=set(always_ids) | set(never_ids),
            is_active=True,
        ).values_list("pk", flat=True)
    )
    always_ids = [value for value in always_ids if value in existing]
    never_ids = [value for value in never_ids if value in existing]

    settings = dict(user.privacy_settings or {})
    settings[key] = {
        "option": option,
        "always": always_ids,
        "never": never_ids,
    }
    user.privacy_settings = settings
    user.save(update_fields=["privacy_settings"])
    return get_privacy_rule(user, key)


def _owner_has_contact(owner, viewer):
    if not owner.pk or not viewer or not getattr(viewer, "pk", None):
        return False
    from apps.messenger.models import Contact

    return Contact.objects.filter(owner=owner, user=viewer).exists()


def is_blocked_between(first, second):
    if not first or not second or not getattr(first, "pk", None) or not getattr(second, "pk", None):
        return False
    if first.pk == second.pk:
        return False
    return UserBlock.objects.filter(
        Q(blocker=first, blocked=second) | Q(blocker=second, blocked=first)
    ).exists()


def privacy_allows(owner, viewer, key):
    if viewer and getattr(viewer, "is_authenticated", False) and viewer.pk == owner.pk:
        return True
    if not viewer or not getattr(viewer, "is_authenticated", False):
        viewer = None

    rule = get_privacy_rule(owner, key)
    viewer_id = getattr(viewer, "pk", None)
    if viewer_id is not None:
        if viewer_id in rule["never"]:
            return False
        if viewer_id in rule["always"]:
            return True
        if UserBlock.objects.filter(blocker=owner, blocked_id=viewer_id).exists():
            return False

    option = rule["option"]
    if option == "everyone":
        return True
    if option == "nobody":
        return False
    return bool(viewer and _owner_has_contact(owner, viewer))


def privacy_rule_payload(user):
    ids = set()
    raw_rules = {}
    for key, meta in PRIVACY_RULES.items():
        rule = get_privacy_rule(user, key)
        raw_rules[key] = rule
        ids.update(rule["always"])
        ids.update(rule["never"])

    User = get_user_model()
    people = {
        item.pk: item
        for item in User.objects.filter(pk__in=ids, is_active=True)
    }

    payload = {}
    for key, meta in PRIVACY_RULES.items():
        rule = raw_rules[key]

        def person_payload(pk):
            person = people.get(pk)
            if person is None:
                return None
            return {
                "id": person.pk,
                "username": person.username,
                "display_name": person.display_name,
                "initials": person.initials,
                "avatar_url": person.avatar.url if person.avatar else "",
            }

        always = [person_payload(pk) for pk in rule["always"]]
        never = [person_payload(pk) for pk in rule["never"]]
        always = [item for item in always if item]
        never = [item for item in never if item]
        payload[key] = {
            "key": key,
            "title": meta["title"],
            "question": meta["question"],
            "option": rule["option"],
            "option_label": PRIVACY_OPTION_LABELS[rule["option"]],
            "always": always,
            "never": never,
        }
    return payload


def blocked_users_payload(user):
    links = (
        UserBlock.objects.filter(blocker=user)
        .select_related("blocked")
        .order_by("-created_at")
    )
    return [
        {
            "id": link.blocked_id,
            "username": link.blocked.username,
            "display_name": link.blocked.display_name,
            "initials": link.blocked.initials,
            "avatar_url": link.blocked.avatar.url if link.blocked.avatar else "",
        }
        for link in links
        if link.blocked.is_active
    ]


def _session_contains_user(session, user_id):
    try:
        data = session.get_decoded()
    except Exception:
        return False
    if str(data.get("_auth_user_id", "")) == str(user_id):
        return True
    accounts = data.get("sovietgram_accounts_v1")
    if not isinstance(accounts, list):
        return False
    return any(str(item.get("user_id", "")) == str(user_id) for item in accounts if isinstance(item, dict))


def _session_token(session_key):
    import hashlib

    return hashlib.sha256(session_key.encode("utf-8")).hexdigest()[:24]


def active_sessions_payload(user, current_session_key=""):
    now = timezone.now()
    result = []
    sessions = Session.objects.filter(expire_date__gt=now).order_by("-expire_date")
    for session in sessions.iterator():
        if not _session_contains_user(session, user.pk):
            continue
        try:
            data = session.get_decoded()
        except Exception:
            data = {}
        user_agent = str(data.get("sovietgram_session_user_agent", "") or "").strip()
        ip = str(data.get("sovietgram_session_ip", "") or "").strip()
        result.append(
            {
                "token": _session_token(session.session_key),
                "current": session.session_key == current_session_key,
                "user_agent": user_agent or "Неизвестное устройство",
                "ip": ip,
                "expires": timezone.localtime(session.expire_date).strftime("%d.%m.%Y %H:%M"),
            }
        )
    result.sort(key=lambda item: (not item["current"], item["user_agent"].lower()))
    return result


def terminate_sessions(user, current_session_key="", token=None, others=False):
    deleted = 0
    now = timezone.now()
    sessions = Session.objects.filter(expire_date__gt=now)
    for session in sessions.iterator():
        if not _session_contains_user(session, user.pk):
            continue
        if session.session_key == current_session_key:
            continue
        if token and _session_token(session.session_key) != token:
            continue
        session.delete()
        deleted += 1
        if token and not others:
            break
    return deleted


def remember_session_device(request):
    request.session["sovietgram_session_user_agent"] = (
        request.META.get("HTTP_USER_AGENT", "") or ""
    )[:240]
    forwarded = (request.META.get("HTTP_X_FORWARDED_FOR", "") or "").split(",", 1)[0].strip()
    request.session["sovietgram_session_ip"] = (
        forwarded or request.META.get("REMOTE_ADDR", "") or ""
    )[:64]
    request.session.modified = True


def inactivity_label(days):
    return INACTIVITY_CHOICES.get(int(days or 0), f"{int(days or 0)} дн.")


def auto_delete_label(seconds):
    return AUTO_DELETE_CHOICES.get(int(seconds or 0), f"{int(seconds or 0)} сек.")


def account_expired_for_inactivity(user, now=None):
    now = now or timezone.now()
    base = user.last_seen_at or user.date_joined
    days = int(user.delete_after_inactive_days or 365)
    return bool(base and base <= now - timedelta(days=days))
