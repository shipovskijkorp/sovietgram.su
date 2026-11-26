"""Public installable-app resources; never include account data."""
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_safe
from PIL import Image, ImageOps


def public(response, max_age=0):
    response["Cache-Control"] = f"public, max-age={max_age}" if max_age else "no-cache"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_safe
def manifest(request):
    return public(JsonResponse({
        "id": "/", "name": "Sovietgram", "short_name": "Sovietgram",
        "description": "Общение, группы и каналы Sovietgram",
        "lang": "ru", "start_url": "/", "scope": "/",
        "display": "standalone", "background_color": "#171412",
        "theme_color": "#cc0000",
        "icons": [
            {"src": reverse("pwa_icon", args=[size]), "sizes": f"{size}x{size}",
             "type": "image/png", "purpose": "any"} for size in (192, 512)
        ],
    }, content_type="application/manifest+json", json_dumps_params={"ensure_ascii": False}))


@lru_cache(maxsize=2)
def icon_bytes(size):
    source = Path(settings.BASE_DIR) / "static" / "img" / "sovietgram-icon.png"
    with Image.open(source) as image:
        artwork = ImageOps.contain(image.convert("RGBA"), (size, size), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        canvas.alpha_composite(artwork, ((size-artwork.width)//2, (size-artwork.height)//2))
        output = BytesIO()
        canvas.save(output, format="PNG")
        return output.getvalue()


@require_safe
def icon(request, size):
    if size not in (192, 512):
        raise Http404
    return public(HttpResponse(icon_bytes(size), content_type="image/png"), 86400)


@require_safe
def service_worker(request):
    script = (Path(settings.BASE_DIR) / "static" / "js" / "service-worker.js").read_bytes()
    response = public(HttpResponse(script, content_type="application/javascript; charset=utf-8"))
    response["Service-Worker-Allowed"] = "/"
    return response


@require_safe
def offline(request):
    # Fixed public HTML, no template context or cookies, no history or drafts.
    html = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Sovietgram — нет соединения</title>
<style>html{color-scheme:light dark}body{margin:0;min-height:100vh;display:grid;place-items:center;font:16px/1.5 system-ui,sans-serif;background:#f8f2e7;color:#2a241d}main{max-width:360px;padding:24px;text-align:center}img{width:80px;height:80px}h1{font-size:24px}a{display:inline-block;background:#b32932;color:#fff;text-decoration:none;border-radius:9px;padding:10px 18px}@media(prefers-color-scheme:dark){body{background:#171412;color:#eee5d8}}</style></head>
<body><main><img src="/app-icon/192.png" alt="Sovietgram"><h1>Нет подключения</h1>
<p>Подключитесь к интернету и попробуйте снова. Переписки не сохраняются в офлайн-кэше этого приложения.</p><a href="/">Повторить</a></main></body></html>"""
    return public(HttpResponse(html, content_type="text/html; charset=utf-8"))
