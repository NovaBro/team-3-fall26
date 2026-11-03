"""Send a promotional email to users who opted in.

Usage:
    python manage.py send_promo_email --subject "New this week" --message "..."
"""

from django.conf import settings
from django.core.mail import send_mass_mail
from django.core.management.base import BaseCommand, CommandError

from accounts.models import UserProfile


class Command(BaseCommand):
    help = "Email every user who opted into promotions (UserProfile.promo_opt_in)."

    def add_arguments(self, parser):
        parser.add_argument("--subject", required=True)
        parser.add_argument("--message", required=True)

    def handle(self, *args, **options):
        recipients = list(
            UserProfile.objects.filter(promo_opt_in=True)
            .exclude(user__email="")
            .values_list("user__email", flat=True)
        )
        if not recipients:
            raise CommandError("No users have opted into promotions.")

        # One message per recipient (not one message addressed to everyone)
        # so opted-in users never see each other's email addresses.
        messages = [
            (
                options["subject"],
                options["message"],
                settings.DEFAULT_FROM_EMAIL,
                [email],
            )
            for email in recipients
        ]
        send_mass_mail(messages)
        self.stdout.write(self.style.SUCCESS(f"Sent to {len(recipients)} user(s)."))
