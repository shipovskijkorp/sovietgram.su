from pathlib import Path

from django.conf import settings


def _static_version():
    static_dir = Path(settings.BASE_DIR) / "static"
    latest = 0
    if static_dir.exists():
        for path in static_dir.rglob("*"):
            if not path.is_file():
                continue
            try:
                latest = max(latest, int(path.stat().st_mtime))
            except OSError:
                continue
    return str(latest)


STATIC_VERSION = _static_version()


def static_version(request):
    # During local development static files can change without Django's
    # Python autoreloader restarting the process. Recompute the cache key
    # per request so a git pull cannot leave the browser on stale JS/CSS.
    version = _static_version() if settings.DEBUG else STATIC_VERSION
    return {"static_version": version}
