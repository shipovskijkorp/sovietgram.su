from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import User
from apps.administration.models import PlatformAudit


class Command(BaseCommand):
    help = "Appoint an existing active account as a Sovietgram platform owner (not Django superuser)."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--role", choices=("owner", "admin", "moderator", "member"), default="owner")
        parser.add_argument("--reason", required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        reason = options["reason"].strip()
        if not 1 <= len(reason) <= 300:
            raise CommandError("Reason must be 1-300 characters.")
        # Lock existing owners and the target in deterministic order.
        target = User.objects.filter(username__iexact=options["username"]).first()
        if target is None:
            raise CommandError("Account not found. Register it normally first.")
        from django.db.models import Q
        locked = {row.pk: row for row in User.objects.select_for_update().filter(
            Q(pk=target.pk) | Q(platform_role="owner")
        ).order_by("pk")}
        target = locked[target.pk]
        role = "" if options["role"] == "member" else options["role"]
        if role and (not target.is_active or target.platform_suspended_at or not target.two_factor_enabled):
            raise CommandError("Account must be active, not suspended, and have two-factor authentication enabled.")
        if target.platform_role == "owner" and role != "owner" and not any(
            user.pk != target.pk and user.platform_role == "owner" for user in locked.values()
        ):
            raise CommandError("Cannot remove the last platform owner.")
        if target.platform_role == role:
            self.stdout.write("Role unchanged.")
            return
        previous = target.platform_role or "member"
        target.platform_role = role
        target.security_version += 1
        target.save(update_fields=["platform_role", "security_version"])
        PlatformAudit.objects.create(actor_label="server CLI", action="role_change", target_kind="user",
            target_id=target.pk, target_label=target.username, reason=f"{previous} -> {role or 'member'}: {reason}"[:300])
        self.stdout.write(self.style.SUCCESS(f"@{target.username}: {options['role']}. Sign in again."))
