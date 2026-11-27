from config.operations import job_run

from django.core.management.base import BaseCommand, CommandError

from apps.accounts.maintenance import purge_inactive_accounts
from apps.messenger.services import purge_expired_messages
from apps.messenger.sticker_auto_update import refresh_due_sticker_packs


class Command(BaseCommand):
    help = "Remove expired data and refresh opted-in sticker packs in bounded background batches."

    def add_arguments(self, parser):
        parser.add_argument("--message-limit", type=int, default=500)
        parser.add_argument("--account-limit", type=int, default=25)
        parser.add_argument("--sticker-limit", type=int, default=10)

    def handle(self, *args, **options):
        messages = options["message_limit"]
        accounts = options["account_limit"]
        stickers = options["sticker_limit"]
        if not 0 <= messages <= 10000 or not 0 <= accounts <= 1000 or not 0 <= stickers <= 100:
            raise CommandError("Limits: 0–10000 messages, 0–1000 accounts, 0–100 sticker packs.")
        with job_run("maintenance"):
            removed_messages = purge_expired_messages(limit=messages)
            removed_accounts = purge_inactive_accounts(limit=accounts)
            added_stickers = refresh_due_sticker_packs(limit=stickers)
            self.stdout.write(
                f"Maintenance: removed {removed_messages} expired message(s), "
                f"{removed_accounts} inactive account(s). Added {added_stickers} sticker(s)."
            )
