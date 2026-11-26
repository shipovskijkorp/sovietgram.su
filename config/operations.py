"""Bounded operational checks and task heartbeats. Never expose credentials."""
import json
import logging
import os
import shutil
import tempfile
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from time import monotonic
from uuid import uuid4

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

logger = logging.getLogger(__name__)
JOBS = {
    "scheduled": ("Отложенная отправка", 120, 180),
    "maintenance": ("Очистка данных", 300, 660),
    "backup": ("Резервное копирование", 36 * 3600, 3700),
}


@never_cache
@require_safe
def liveness(request):
    # Deliberately cheap and non-sensitive. DB/cache readiness is checked
    # privately, not by an unauthenticated request.
    return JsonResponse({"ok": True})


def heartbeat_path(job):
    if job not in JOBS:
        raise ValueError("Unknown operational job")
    return Path(settings.SOVIETGRAM_OPS_DIR) / (job + ".json")


def read_heartbeat(job):
    try:
        with heartbeat_path(job).open("rb") as stream:
            value = json.loads(stream.read(8193))
        if isinstance(value, dict):
            return value
    except (OSError, ValueError, TypeError):
        pass
    return {}


def write_heartbeat(job, data):
    target = heartbeat_path(job)
    temporary = None
    try:
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         prefix="." + job + "-", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except OSError:
        # Telemetry must never change the actual outcome of a job.
        logger.warning("Could not record heartbeat for %s", job)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


@contextmanager
def job_run(job):
    started = timezone.now().isoformat()
    data = {"state": "running", "started_at": started,
            "success_at": read_heartbeat(job).get("success_at")}
    write_heartbeat(job, data)
    try:
        yield
    except BaseException:
        data.update(state="failed", finished_at=timezone.now().isoformat(),
                    success_at=read_heartbeat(job).get("success_at"))
        write_heartbeat(job, data)
        raise
    else:
        ended = timezone.now().isoformat()
        data.update(state="ok", finished_at=ended, success_at=ended)
        write_heartbeat(job, data)


def parsed(value):
    if not isinstance(value, str):
        return None
    try:
        result = parse_datetime(value)
        return result if result and timezone.is_aware(result) else None
    except (ValueError, OverflowError):
        return None


def job_status(job, now):
    label, stale, max_runtime = JOBS[job]
    data = read_heartbeat(job)
    started = parsed(data.get("started_at"))
    success = parsed(data.get("success_at"))
    state, status = "unknown", "Нет данных"
    if job == "maintenance" and not settings.SOVIETGRAM_BACKGROUND_MAINTENANCE:
        state, status = "unknown", "Фоновый режим выключен"
    elif data.get("state") == "failed":
        state, status = "error", "Последний запуск завершился ошибкой"
    elif data.get("state") == "running":
        if started and now - started <= timedelta(seconds=max_runtime):
            state, status = "warning", "Выполняется"
        else:
            state, status = "error", "Нет завершения запуска"
    elif success:
        if now - success > timedelta(seconds=stale):
            state, status = "warning", "Давно не было успешного запуска"
        else:
            state, status = "ok", "Выполнено"
    return {"label": label, "state": state, "status": status,
            "started_at": started, "success_at": success}


def check_database():
    start = monotonic()
    state, label, ms = "error", "Недоступна", None
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            if cursor.fetchone()[0] == 1:
                state, label, ms = "ok", "Работает", round((monotonic()-start)*1000, 1)
    except Exception:
        logger.warning("Database readiness probe failed")
    return {"state": state, "label": label, "ms": ms,
            "engine": connection.vendor}


def check_cache():
    start = monotonic()
    state, label, ms = "error", "Недоступен", None
    key = "ops:probe:" + uuid4().hex
    shared = settings.CACHES["default"]["BACKEND"].endswith(".RedisCache")
    try:
        cache.set(key, "ok", 15)
        if cache.get(key) == "ok":
            cache.delete(key)
            state, label = ("ok", "Работает") if shared else ("warning", "Локальный")
            ms = round((monotonic()-start)*1000, 1)
    except Exception:
        logger.warning("Cache readiness probe failed")
    return {"state": state, "label": label, "ms": ms,
            "backend": "Redis" if shared else "Локальный кэш / другой backend"}


def gib(value):
    return f"{value / 1024**3:.2f} ГиБ"


def resource(label, used, total):
    if not total or used < 0 or used > total:
        return {"label": label, "state": "unknown", "value": "—", "detail": "Нет данных", "percent": None}
    percent = min(100, round(100 * used / total))
    state = "error" if percent >= 95 else "warning" if percent >= 85 else "ok"
    return {"label": label, "state": state, "value": f"{percent}%",
            "detail": f"{gib(used)} из {gib(total)}", "percent": percent}


def resource_status():
    metrics = []
    try:
        usage = shutil.disk_usage(settings.RUNTIME_DIR)
        metrics.append(resource("Диск", usage.total-usage.free, usage.total))
    except OSError:
        metrics.append(resource("Диск", 0, 0))
    try:
        values = {}
        with open("/proc/meminfo", encoding="ascii") as stream:
            for line in stream:
                if line.startswith(("MemTotal:", "MemAvailable:")):
                    key, raw = line.split(":", 1)
                    values[key] = int(raw.split()[0]) * 1024
        total, available = values["MemTotal"], values["MemAvailable"]
        metrics.append(resource("Оперативная память", total-available, total))
    except (OSError, KeyError, ValueError):
        metrics.append(resource("Оперативная память", 0, 0))
    try:
        one, five, fifteen = os.getloadavg()
        cores = os.cpu_count() or 1
        state = "warning" if one >= cores else "ok"
        metrics.append({"label": "Нагрузка CPU (load average)", "state": state,
                        "value": f"{one:.2f}", "detail": f"5 мин: {five:.2f} · 15 мин: {fifteen:.2f} · CPU: {cores}",
                        "percent": None})
    except (OSError, AttributeError):
        metrics.append(resource("Нагрузка CPU (load average)", 0, 0))
    return metrics


def queue_status(now):
    from apps.messenger.models import ScheduledMessage

    try:
        rows = ScheduledMessage.objects
        pending = rows.filter(status=ScheduledMessage.Status.PENDING)
        return {"pending": pending.count(),
                "overdue": pending.filter(next_attempt_at__lte=now-timedelta(minutes=1)).count(),
                "failed": rows.filter(status=ScheduledMessage.Status.FAILED).count()}
    except Exception:
        logger.warning("Scheduled-message queue probe failed")
        return {"pending": None, "overdue": None, "failed": None}


def collect_status():
    now = timezone.now()
    return {"checked_at": now, "database": check_database(), "cache": check_cache(),
            "resources": resource_status(), "jobs": [job_status(job, now) for job in JOBS],
            "queue": queue_status(now)}
