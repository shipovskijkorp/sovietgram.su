"""Explicit, bounded link previews. Never fetch a URL supplied independently of a visible message."""
import hashlib
import http.client
import ipaddress
import re
import socket
import ssl
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from . import views
from .markdown import render_message_markdown
from .ratelimit import rate_limit

MAX_BYTES = 96 * 1024
MAX_REDIRECTS = 2
TIMEOUT = 3
CACHE_SECONDS = 3600


class PreviewError(ValueError):
    pass


class Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href") or ""
            if href.startswith(("https://", "http://")):
                self.urls.append(href)


class Metadata(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.fields = {}
        self.in_title = False
        self.title = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "title":
            self.in_title = True
        if tag == "meta":
            key = (attrs.get("property") or attrs.get("name") or "").lower()
            if key in {"og:title", "og:description", "og:site_name", "twitter:title", "twitter:description", "description"}:
                self.fields.setdefault(key, attrs.get("content") or "")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, text):
        if self.in_title:
            self.title.append(text)

    def result(self):
        def compact(value, maximum):
            # Metadata is data, never markup. Strip control characters.
            return " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", value).split())[:maximum]
        return {
            "title": compact(self.fields.get("og:title") or self.fields.get("twitter:title") or " ".join(self.title), 180),
            "description": compact(self.fields.get("og:description") or self.fields.get("twitter:description") or self.fields.get("description") or "", 420),
            "site_name": compact(self.fields.get("og:site_name") or "", 100),
        }


def public_ipv4(value):
    try:
        address = ipaddress.IPv4Address(value)
    except ValueError:
        return False
    # Explicit cloud virtual platform address and special-use networks.
    return (address.is_global and not address.is_multicast and not address.is_reserved
            and not address.is_loopback and not address.is_link_local
            and not any(address in ipaddress.IPv4Network(network) for network in (
                "192.0.0.0/24", "192.88.99.0/24", "198.18.0.0/15", "240.0.0.0/4",
            ))
            and str(address) != "168.63.129.16")


def safe_target(url):
    if not isinstance(url, str) or len(url) > 2048 or any(ord(c) <= 32 or ord(c) == 127 for c in url) or "\\" in url:
        raise PreviewError("Некорректная ссылка.")
    try:
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        if scheme not in {"http", "https"} or parts.username is not None or parts.password is not None:
            raise ValueError
        host = (parts.hostname or "").rstrip(".").encode("idna").decode("ascii").lower()
        port = 443 if scheme == "https" else 80
        if parts.port not in (None, port):
            raise ValueError
        # DNS names only; refuse IP literals, local names and ambiguous hosts.
        if not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,62}", host):
            raise ValueError
        if host.endswith((".local", ".localhost", ".internal", ".home.arpa", ".onion", ".test", ".invalid")):
            raise ValueError
        # Only IPv4 is supported. Reject the entire DNS result if any answer
        # is non-public, then connect directly to the validated numeric IP.
        answers = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
        addresses = list(dict.fromkeys(answer[4][0] for answer in answers))
        if not addresses or not all(public_ipv4(address) for address in addresses):
            raise ValueError
        path = urlunsplit(("", "", parts.path or "/", parts.query, ""))
        # http.client expects ASCII request targets; Markdown usually already encodes URLs.
        path.encode("ascii")
    except (ValueError, UnicodeError, OSError, OverflowError):
        raise PreviewError("Предпросмотр этой ссылки недоступен.") from None
    return scheme, host, port, addresses[0], path


def fetch_metadata(url):
    current = url
    deadline = time.monotonic() + 8
    for attempt in range(MAX_REDIRECTS + 1):
        scheme, host, port, address, path = safe_target(current)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise PreviewError("Истекло время получения предпросмотра.")
        timeout = min(TIMEOUT, remaining)
        if scheme == "https":
            connection = http.client.HTTPSConnection(host, port, timeout=timeout, context=ssl.create_default_context())
        else:
            connection = http.client.HTTPConnection(host, port, timeout=timeout)
        # Preserve Host and TLS SNI/certificate validation for the original
        # hostname, but never resolve it a second time at connect time.
        connection._create_connection = lambda _destination, timeout, source_address=None: socket.create_connection(
            (address, port), timeout, source_address,
        )
        try:
            connection.request("GET", path, headers={
                "User-Agent": "Sovietgram-LinkPreview/1.0",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Encoding": "identity",
                "Connection": "close",
                "Range": f"bytes=0-{MAX_BYTES - 1}",
            })
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location or attempt >= MAX_REDIRECTS:
                    raise PreviewError("Слишком много перенаправлений.")
                next_url = urljoin(current, location)
                if scheme == "https" and urlsplit(next_url).scheme != "https":
                    raise PreviewError("Небезопасное перенаправление.")
                current = next_url
                continue
            if response.status not in {200, 206}:
                raise PreviewError("Сайт не предоставил предпросмотр.")
            mime = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
            if mime not in {"text/html", "application/xhtml+xml"}:
                raise PreviewError("Ссылка не ведёт на HTML-страницу.")
            if response.getheader("Content-Encoding", "identity").lower() != "identity":
                raise PreviewError("Неподдерживаемое кодирование ответа.")
            data = bytearray()
            while len(data) < MAX_BYTES:
                if time.monotonic() >= deadline:
                    raise PreviewError("Истекло время получения предпросмотра.")
                chunk = response.read1(min(8192, MAX_BYTES - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
                if b"</head" in data.lower():
                    break
            charset = re.search(r"charset\s*=\s*['\"]?([a-zA-Z0-9_-]+)", response.getheader("Content-Type", ""), re.I)
            encoding = charset.group(1) if charset else "utf-8"
            if encoding.lower() not in {"utf-8", "utf8", "windows-1251", "cp1251", "windows-1252", "iso-8859-1"}:
                encoding = "utf-8"
            parser = Metadata()
            parser.feed(bytes(data).decode(encoding, errors="replace"))
            result = parser.result()
            result.update({"domain": host, "title": result["title"] or host})
            return result
        except (OSError, http.client.HTTPException, ValueError) as exc:
            if isinstance(exc, PreviewError):
                raise
            raise PreviewError("Не удалось получить предпросмотр ссылки.") from None
        finally:
            connection.close()
    raise PreviewError("Предпросмотр недоступен.")


def first_link(text):
    parser = Links()
    parser.feed(render_message_markdown(text))
    return parser.urls[0] if parser.urls else ""


@login_required
@require_POST
@rate_limit("link_preview")
def link_preview(request, chat_id):
    if request.POST.get("account_id") != str(request.user.pk):
        return JsonResponse({"ok": False, "error": "Аккаунт изменился."}, status=409)
    chat = views._chat_for_user(request.user, chat_id)
    try:
        message_id = int(request.POST.get("message_id", ""))
        if not 0 < message_id <= 9223372036854775807:
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        return JsonResponse({"ok": False, "error": "Некорректное сообщение."}, status=400)
    message = get_object_or_404(views._visible_message_queryset(chat, request.user),
                                pk=message_id, is_deleted=False, special_type="")
    url = first_link(message.text)
    if not url or url != request.POST.get("url"):
        return JsonResponse({"ok": False, "error": "Ссылка изменилась или отсутствует."}, status=400)
    key = "sg:link-preview:v1:" + hashlib.sha256(url.encode()).hexdigest()
    result = cache.get(key)
    if result is None:
        try:
            result = fetch_metadata(url)
        except PreviewError as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=422)
        cache.set(key, result, CACHE_SECONDS)
    response = JsonResponse({"ok": True, "url": url, "preview": result})
    response["Cache-Control"] = "private, no-store"
    return response
