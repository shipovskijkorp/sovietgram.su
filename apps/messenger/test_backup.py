import io
import json
import os
import sqlite3
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from .backup import BackupError, create_backup, verify_backup, rehearse_sqlite_backup


class BackupTests(SimpleTestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.base = self.root / "project"
        self.base.mkdir()
        self.media = self.base / "var" / "media"
        self.media.mkdir(parents=True)
        self.target = self.root / "backups"
        self.database = self.base / "var" / "db.sqlite3"
        with sqlite3.connect(self.database) as connection:
            connection.executescript("""
                CREATE TABLE accounts_user (avatar TEXT);
                CREATE TABLE accounts_avatarhistory (image TEXT);
                CREATE TABLE messenger_chat (avatar TEXT);
                CREATE TABLE messenger_messageattachment (file TEXT);
                INSERT INTO accounts_user VALUES ('avatars/profile.webp');
                INSERT INTO accounts_avatarhistory VALUES ('avatars/previous.webp');
                INSERT INTO accounts_avatarhistory VALUES ('avatars/profile.webp');
                INSERT INTO messenger_chat VALUES ('');
                INSERT INTO messenger_messageattachment VALUES ('messages/example.txt');
            """)
        for name, content in (("avatars/profile.webp", b"avatar"),
                              ("avatars/previous.webp", b"previous avatar"),
                              ("messages/example.txt", b"message"),
                              ("messages/orphan.txt", b"orphan")):
            path = self.media / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        (self.base / ".env").write_text("DJANGO_SECRET_KEY=test-only")
        self.db_config = {"ENGINE": "django.db.backends.sqlite3", "NAME": self.database}

    def backup(self, keep=7):
        return create_backup(self.target, keep=keep, database=self.db_config,
                             base=self.base, media_root=self.media)

    def test_database_snapshot_restores_and_referenced_media_is_verified(self):
        result = self.backup()
        manifest = verify_backup(result)
        self.assertEqual(manifest["database"], "sqlite")
        self.assertEqual(set(manifest["files"]), {
            "database.sqlite3", ".env", "media/avatars/profile.webp", "media/avatars/previous.webp",
            "media/messages/example.txt",
        })
        with tarfile.open(result, "r:gz") as archive:
            restored = self.root / "restored.sqlite3"
            restored.write_bytes(archive.extractfile("database.sqlite3").read())
            self.assertEqual(archive.extractfile("media/messages/example.txt").read(), b"message")
            self.assertEqual(archive.extractfile("media/avatars/previous.webp").read(), b"previous avatar")
            self.assertEqual(archive.extractfile(".env").read(), b"DJANGO_SECRET_KEY=test-only")
        with sqlite3.connect(restored) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone(), ("ok",))
            self.assertEqual(connection.execute("SELECT file FROM messenger_messageattachment").fetchone(),
                             ("messages/example.txt",))
        if os.name == "posix":
            self.assertEqual(result.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.target.stat().st_mode & 0o777, 0o700)

    def test_sqlite_rehearsal_checks_integrity_and_referenced_files(self):
        result = self.backup()
        report = rehearse_sqlite_backup(result)
        self.assertEqual(report["tables"], 4)
        self.assertEqual(report["referenced_media"], 3)
        self.assertEqual(report["verified_files"], 5)
        # Reproduce an older archive which has a valid checksum manifest but
        # omitted archived profile photos.
        incomplete = self.root / "incomplete.tar.gz"
        with tarfile.open(result, "r:gz") as source, tarfile.open(incomplete, "w:gz") as target:
            for item in source:
                if item.name == "media/avatars/previous.webp":
                    continue
                contents = source.extractfile(item).read()
                if item.name == "manifest.json":
                    manifest = json.loads(contents)
                    manifest["files"].pop("media/avatars/previous.webp")
                    contents = json.dumps(manifest).encode()
                    item.size = len(contents)
                target.addfile(item, io.BytesIO(contents))
        verify_backup(incomplete)
        with self.assertRaisesRegex(BackupError, "missing 1 referenced"):
            rehearse_sqlite_backup(incomplete)
        self.assertTrue(self.database.exists())
        self.assertTrue((self.media / "avatars/previous.webp").exists())

    def test_pre_avatar_history_database_rehearsal_remains_supported(self):
        with sqlite3.connect(self.database) as connection:
            connection.execute("DROP TABLE accounts_avatarhistory")
        report = rehearse_sqlite_backup(self.backup())
        self.assertEqual(report["tables"], 3)
        self.assertEqual(report["referenced_media"], 2)

    def test_missing_archived_avatar_preserves_previous_backup(self):
        previous = self.backup(keep=1)
        (self.media / "avatars/previous.webp").unlink()
        with self.assertRaises((OSError, BackupError)):
            self.backup(keep=1)
        self.assertEqual(list(self.target.iterdir()), [previous])
        verify_backup(previous)

    def test_failed_backup_never_replaces_last_good_backup(self):
        previous = self.backup(keep=1)
        (self.media / "messages" / "example.txt").unlink()
        with self.assertRaises((OSError, BackupError)):
            self.backup(keep=1)
        self.assertEqual(list(self.target.iterdir()), [previous])
        verify_backup(previous)

    def test_rotation_only_after_success_and_only_own_archives(self):
        previous = self.backup(keep=1)
        unrelated = self.target / "manual.tar.gz"
        unrelated.write_bytes(b"manual")
        latest = self.backup(keep=1)
        self.assertFalse(previous.exists())
        self.assertTrue(unrelated.exists())
        verify_backup(latest)

    def test_verification_rejects_changed_content(self):
        result = self.backup()
        modified = self.root / "modified.tar.gz"
        with tarfile.open(result, "r:gz") as source, tarfile.open(modified, "w:gz") as target:
            for item in source:
                contents = source.extractfile(item).read()
                if item.name == "media/messages/example.txt":
                    contents = b"altered"
                    item.size = len(contents)
                target.addfile(item, io.BytesIO(contents))
        with self.assertRaises(BackupError):
            verify_backup(modified)

    def test_rejects_path_traversal_and_project_backup_directory(self):
        with sqlite3.connect(self.database) as connection:
            connection.execute("INSERT INTO messenger_messageattachment VALUES ('../.env')")
        with self.assertRaises(BackupError):
            self.backup()
        with self.assertRaises(BackupError):
            create_backup(self.base / "backups", database=self.db_config,
                          base=self.base, media_root=self.media)
