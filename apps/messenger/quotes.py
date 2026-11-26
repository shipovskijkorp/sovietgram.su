"""A quote is a verified range in an accessible original, not copied text."""
import hashlib
import hmac
import re

from django.utils import timezone


MAX_QUOTE = 1024


def _digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _available(reply):
    return (
        reply is not None and not reply.is_deleted and not reply.special_type
        and (reply.expires_at is None or reply.expires_at > timezone.now())
    )


def make_quote(reply, raw):
    if not raw:
        return ""
    if not isinstance(raw, str) or not raw.strip() or len(raw) > MAX_QUOTE:
        raise ValueError("Выберите фрагмент текста до 1024 символов.")
    if not _available(reply):
        raise ValueError("Исходное сообщение для цитаты недоступно.")
    start = reply.text.find(raw)
    if start < 0:
        raise ValueError("Цитата не совпадает с исходным сообщением. Выделите текст заново.")
    return f"{start}:{len(raw)}:{_digest(raw)}"


def resolve_quote(reply, reference):
    if not reference or not _available(reply):
        return ""
    match = re.fullmatch(r"([0-9]{1,4}):([0-9]{1,4}):([a-f0-9]{64})", reference)
    if not match:
        return ""
    start, length = map(int, match.group(1, 2))
    if not 0 < length <= MAX_QUOTE or start + length > len(reply.text):
        return ""
    text = reply.text[start:start+length]
    return text if hmac.compare_digest(_digest(text), match.group(3)) else ""
