from config.operations import job_run

from django.core.management.base import BaseCommand

from apps.messenger.scheduled import deliver_due_messages


class Command(BaseCommand):
    help = "Deliver due scheduled messages; safe to run repeatedly or concurrently."

    def handle(self, *args, **options):
        with job_run("scheduled"):
            count = deliver_due_messages(limit=100)
            self.stdout.write(f"Delivered {count} scheduled message(s).")
