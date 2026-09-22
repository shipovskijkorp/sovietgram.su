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
    return {"static_version": STATIC_VERSION}
