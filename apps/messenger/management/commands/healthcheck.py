from django.core.management.base import BaseCommand, CommandError

from config.operations import check_cache, check_database, resource_status


class Command(BaseCommand):
    help = "Check database, cache and disk availability; exit nonzero on critical errors."

    def handle(self, *args, **options):
        database, cache = check_database(), check_cache()
        disk = resource_status()[0]
        self.stdout.write(f"Database: {database['state']} ({database['engine']})")
        self.stdout.write(f"Cache: {cache['state']} ({cache['backend']})")
        self.stdout.write(f"Disk: {disk['state']} ({disk['value']})")
        if database["state"] != "ok" or cache["state"] == "error" or disk["state"] in {"error", "unknown"}:
            raise CommandError("Critical readiness check failed.")
