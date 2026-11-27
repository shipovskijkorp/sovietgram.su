"""Private, verified database and referenced-media snapshots for Sovietgram.

No application data is modified. A missing or changed file aborts publication
of a new backup, rather than replacing the last known-good backup.
"""
import gzip
import hashlib
import io
import json
import os
import re
import sqlite3
import stat
import subprocess
import tarfile
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from uuid import uuid4

from django.conf import settings


class BackupError(Exception):
    pass


CHUNK = 1024 * 1024
MANIFEST_LIMIT = 64 * 1024 * 1024
BACKUP_NAME = re.compile(r"sovietgram-\d{8}T\d{12}Z-[a-f0-9]{8}\.tar\.gz\Z")
MEDIA_QUERY = """
SELECT avatar FROM accounts_user WHERE avatar <> ''
UNION
SELECT avatar FROM messenger_chat WHERE avatar <> ''
UNION
SELECT file FROM messenger_messageattachment WHERE file <> ''
"""
AVATAR_HISTORY_QUERY = "\nUNION\nSELECT image FROM accounts_avatarhistory WHERE image <> ''"
SCHEDULED_MEDIA_QUERY = "\nUNION\nSELECT file FROM messenger_scheduledattachment WHERE file <> ''"
GIF_MEDIA_QUERY = "\nUNION\nSELECT file FROM messenger_savedgif WHERE file <> ''"


def sqlite_media_names(connection):
    # Old archives can predate avatar history; newer archives must include it.
    has_history = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='accounts_avatarhistory'"
    ).fetchone()
    has_scheduled_media = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='messenger_scheduledattachment'"
    ).fetchone()
    has_gifs = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='messenger_savedgif'"
    ).fetchone()
    query = MEDIA_QUERY + (AVATAR_HISTORY_QUERY if has_history else "") + (SCHEDULED_MEDIA_QUERY if has_scheduled_media else "") + (GIF_MEDIA_QUERY if has_gifs else "")
    return sorted(media_name(row[0]) for row in connection.execute(query))


def media_name(value):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise BackupError("Invalid stored media path.")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value or value == ".":
        raise BackupError("Invalid stored media path.")
    return value


def sqlite_snapshot(database, work):
    source = Path(database["NAME"]).resolve(strict=True)
    destination = work / "database.sqlite3"
    # SQLite's backup API copies a coherent database, including committed WAL
    # pages. Never copy a live db.sqlite3 file with ordinary file operations.
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=30)) as live, \
         closing(sqlite3.connect(destination)) as snapshot:
        live.backup(snapshot, pages=256, sleep=.05)
        if snapshot.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise BackupError("SQLite snapshot failed quick_check.")
        media = sqlite_media_names(snapshot)
    return "sqlite", destination, media


def postgres_snapshot(database, work):
    import psycopg

    destination = work / "database.dump"
    kwargs = {
        key: str(database[source])
        for key, source in (
            ("dbname", "NAME"), ("user", "USER"), ("password", "PASSWORD"),
            ("host", "HOST"), ("port", "PORT"),
        )
        if database.get(source) not in (None, "")
    }
    env = os.environ.copy()
    for key, source in (
        ("PGDATABASE", "NAME"), ("PGUSER", "USER"), ("PGPASSWORD", "PASSWORD"),
        ("PGHOST", "HOST"), ("PGPORT", "PORT"),
    ):
        if database.get(source) not in (None, ""):
            env[key] = str(database[source])
        else:
            env.pop(key, None)
    env.pop("PGSERVICE", None)
    # Read file references and dump the database using one MVCC snapshot.
    # Credentials are passed through the process environment, not argv.
    with psycopg.connect(**kwargs, connect_timeout=10) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        snapshot_id = connection.execute("SELECT pg_export_snapshot()").fetchone()[0]
        # Production schema is expected to be migrated before backups run.
        media = sorted(media_name(row[0]) for row in connection.execute(MEDIA_QUERY + AVATAR_HISTORY_QUERY + SCHEDULED_MEDIA_QUERY + GIF_MEDIA_QUERY))
        subprocess.run(
            ["pg_dump", "--format=custom", "--no-password", "--snapshot=" + snapshot_id,
             "--file=" + str(destination)],
            env=env, check=True, timeout=3300,
        )
    # Validate the archive format/table of contents. A real restore rehearsal
    # is still required to prove recoverability.
    subprocess.run(
        ["pg_restore", "--list", str(destination)],
        check=True, stdout=subprocess.DEVNULL, timeout=60,
    )
    return "postgresql", destination, media


def snapshot_database(database, work):
    engine = database["ENGINE"]
    if engine == "django.db.backends.sqlite3":
        return sqlite_snapshot(database, work)
    if engine == "django.db.backends.postgresql":
        return postgres_snapshot(database, work)
    raise BackupError("Unsupported database engine for backup.")


class HashReader:
    def __init__(self, source):
        self.source = source
        self.hash = hashlib.sha256()
        self.size = 0

    def read(self, count=-1):
        data = self.source.read(count)
        self.hash.update(data)
        self.size += len(data)
        return data

    def result(self):
        return {"sha256": self.hash.hexdigest(), "size": self.size}


def add_regular_file(bundle, source, name):
    if source.is_symlink():
        raise BackupError(f"Refusing symlink in backup: {name}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    with os.fdopen(os.open(source, flags), "rb") as file:
        before = os.fstat(file.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise BackupError(f"Not a regular file: {name}")
        info = tarfile.TarInfo(name)
        info.mode = 0o600
        info.size = before.st_size
        info.mtime = int(before.st_mtime)
        reader = HashReader(file)
        bundle.addfile(info, reader)
        after = os.fstat(file.fileno())
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise BackupError(f"File changed during backup: {name}")
        return reader.result()


def verify_backup(path):
    """Verify every archived byte against the manifest without extracting it."""
    actual = {}
    manifest = None
    with gzip.open(path, "rb") as compressed:
        with tarfile.open(fileobj=compressed, mode="r|") as bundle:
            for item in bundle:
                if manifest is not None or not item.isfile() or item.name in actual:
                    raise BackupError("Unexpected or duplicate archive entry.")
                stream = bundle.extractfile(item)
                if item.name == "manifest.json":
                    if item.size > MANIFEST_LIMIT:
                        raise BackupError("Backup manifest is too large.")
                    manifest = json.load(stream)
                    continue
                if item.name.startswith("media/"):
                    media_name(item.name[len("media/"):])
                elif item.name not in {"database.sqlite3", "database.dump", ".env"}:
                    raise BackupError("Unexpected archive path.")
                reader = HashReader(stream)
                while reader.read(CHUNK):
                    pass
                if reader.size != item.size:
                    raise BackupError("Incomplete archive entry.")
                actual[item.name] = reader.result()
        # Drain through the gzip trailer, including its CRC check.
        while compressed.read(CHUNK):
            pass
    if not isinstance(manifest, dict) or manifest.get("format") != 1:
        raise BackupError("Missing or unsupported backup manifest.")
    if manifest.get("files") != actual:
        raise BackupError("Backup content does not match its manifest.")
    db_name = {"sqlite": "database.sqlite3", "postgresql": "database.dump"}.get(manifest.get("database"))
    if not db_name or db_name not in actual or len(set(actual) & {"database.sqlite3", "database.dump"}) != 1:
        raise BackupError("Backup must contain exactly one database snapshot.")
    return manifest


def rehearse_sqlite_backup(path):
    """Restore only the DB to a private temp directory; never touch live data.

    Verify the entire archive and then verify the extracted snapshot again,
    so a replaced archive cannot silently substitute a different database.
    """
    manifest = verify_backup(path)
    if manifest["database"] != "sqlite":
        raise BackupError("SQLite rehearsal requires an SQLite backup. PostgreSQL needs an isolated pg_restore database.")
    with tempfile.TemporaryDirectory(prefix="sovietgram-rehearsal-") as directory:
        restored = Path(directory) / "database.sqlite3"
        with tarfile.open(path, "r:gz") as archive:
            item = archive.getmember("database.sqlite3")
            if not item.isfile() or item.size != manifest["files"][item.name]["size"]:
                raise BackupError("Restored database entry changed.")
            with archive.extractfile(item) as source, restored.open("xb") as target:
                reader = HashReader(source)
                while chunk := reader.read(CHUNK):
                    target.write(chunk)
                if reader.result() != manifest["files"][item.name]:
                    raise BackupError("Restored database does not match manifest.")
        with closing(sqlite3.connect(restored.as_uri() + "?mode=ro", uri=True)) as connection:
            if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise BackupError("Restored SQLite database failed integrity_check.")
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise BackupError("Restored SQLite database contains broken foreign keys.")
            referenced = sqlite_media_names(connection)
            missing = [name for name in referenced if "media/" + name not in manifest["files"]]
            if missing:
                raise BackupError(f"Backup is missing {len(missing)} referenced media file(s).")
            tables = connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchone()[0]
    return {"database": "sqlite", "tables": tables, "referenced_media": len(referenced),
            "verified_files": len(manifest["files"])}


def backup_directory(directory, base, media_root):
    target = Path(directory).expanduser().resolve()
    if target.is_relative_to(base.resolve()) or target.is_relative_to(media_root.resolve()):
        raise BackupError("Keep backups outside the project and media directories.")
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not target.is_dir() or (os.name == "posix" and stat.S_IMODE(target.stat().st_mode) & 0o077):
        raise BackupError("Backup directory must be private (chmod 700).")
    return target


def create_backup(directory, *, keep=7, database=None, base=None, media_root=None):
    if not 1 <= keep <= 365:
        raise BackupError("Keep between 1 and 365 backups.")
    base = Path(base if base is not None else settings.BASE_DIR).resolve()
    media_root = Path(media_root if media_root is not None else settings.MEDIA_ROOT).resolve()
    database = database if database is not None else settings.DATABASES["default"]
    target = backup_directory(directory, base, media_root)
    created = datetime.now(timezone.utc)
    name = "sovietgram-" + created.strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex[:8] + ".tar.gz"
    result = target / name

    with tempfile.TemporaryDirectory(prefix=".backup-", dir=target) as temporary:
        work = Path(temporary)
        engine, db_file, media = snapshot_database(database, work)
        archive_path = work / name
        entries = {}
        with os.fdopen(os.open(archive_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as raw:
            with tarfile.open(fileobj=raw, mode="w:gz", compresslevel=3) as bundle:
                entries[db_file.name] = add_regular_file(bundle, db_file, db_file.name)
                env_path = base / ".env"
                if env_path.exists() or env_path.is_symlink():
                    entries[".env"] = add_regular_file(bundle, env_path, ".env")
                for relative in media:
                    source = media_root.joinpath(*PurePosixPath(relative).parts)
                    if source.resolve(strict=True) != source:
                        raise BackupError(f"Refusing symlink in media path: {relative}")
                    name_in_archive = "media/" + relative
                    entries[name_in_archive] = add_regular_file(bundle, source, name_in_archive)
                manifest = {
                    "format": 1, "database": engine, "created_at": created.isoformat(),
                    "files": entries,
                }
                payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
                if len(payload) > MANIFEST_LIMIT:
                    raise BackupError("Backup manifest is too large.")
                info = tarfile.TarInfo("manifest.json")
                info.size = len(payload)
                info.mode = 0o600
                bundle.addfile(info, io.BytesIO(payload))
            raw.flush()
            os.fsync(raw.fileno())
        verify_backup(archive_path)
        # Publish only after successful database, media and checksum checks.
        os.replace(archive_path, result)

    # Only rotate complete archives made by this command, after success.
    archives = sorted(
        (item for item in target.iterdir()
         if BACKUP_NAME.fullmatch(item.name) and not item.is_symlink() and item.is_file()),
        key=lambda item: item.name, reverse=True,
    )
    for obsolete in archives[keep:]:
        obsolete.unlink(missing_ok=True)
    return result
