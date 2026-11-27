import json
import sqlite3
import subprocess
import tarfile

from django.core.management.base import BaseCommand, CommandError

from apps.messenger.backup import BackupError, create_backup, verify_backup, rehearse_sqlite_backup
from config.operations import job_run


class Command(BaseCommand):
    help = "Create or verify a private Sovietgram database/media backup."

    def add_arguments(self, parser):
        parser.add_argument("--directory", default="/var/lib/sovietgram-backup")
        parser.add_argument("--keep", type=int, default=7)
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--verify", metavar="ARCHIVE")
        mode.add_argument("--rehearse-sqlite", metavar="ARCHIVE",
                          help="Verify and restore a SQLite snapshot into a temporary directory.")

    def handle(self, *args, **options):
        try:
            if options["rehearse_sqlite"]:
                report = rehearse_sqlite_backup(options["rehearse_sqlite"])
                self.stdout.write(self.style.SUCCESS(
                    f"SQLite restore rehearsal passed: {report['tables']} tables, "
                    f"{report['referenced_media']} referenced media, "
                    f"{report['verified_files']} verified files."
                ))
                return
            if options["verify"]:
                manifest = verify_backup(options["verify"])
                self.stdout.write(self.style.SUCCESS(
                    f"Verified {manifest['database']} backup: {len(manifest['files'])} files."
                ))
                return
            with job_run("backup"):
                result = create_backup(options["directory"], keep=options["keep"])
        except (BackupError, OSError, EOFError, sqlite3.Error, subprocess.SubprocessError,
                tarfile.TarError, json.JSONDecodeError) as exc:
            raise CommandError(f"Backup failed: {exc}") from exc
        self.stdout.write(self.style.SUCCESS(f"Backup created and verified: {result}"))
