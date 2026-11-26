from django.core.management.base import BaseCommand, CommandError

from apps.accounts.maintenance import purge_inactive_accounts
from apps.messenger.services import purge_expired_messages


class Command(BaseCommand):
    help = "Remove expired messages and inactive accounts in bounded background batches."

    def add_arguments(self, parser):
        parser.add_argument("--message-limit", type=int, default=500)
        parser.add_argument("--account-limit", type=int, default=25)

    def handle(self, *args, **options):
        messages = options["message_limit"]
        accounts = options["account_limit"]
        if not 0 <= messages <= 10000 or not 0 <= accounts <= 1000:
            raise CommandError("Limits: 0–10000 messages, 0–1000 accounts.")
        removed_messages = purge_expired_messages(limit=messages)
        removed_accounts = purge_inactive_accounts(limit=accounts)
        self.stdout.write(
            f"Maintenance: removed {removed_messages} expired message(s), "
            f"{removed_accounts} inactive account(s)."
        )
