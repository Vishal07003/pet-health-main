import logging
from datetime import timedelta
from typing import Dict, Any, Optional

from django.core.management.base import BaseCommand
from django.utils import timezone

from pets.models import Pet
from insights.services import PetAnalyticsService
from notifications.services import NotificationDispatcher

logger = logging.getLogger(__name__)


def process_daily_summaries(target_date: Optional[timezone.datetime.date] = None) -> Dict[str, int]:
    """
    Evaluates real daily activity for all registered pets on target_date
    and dispatches a daily summary push notification to owners if sufficient real data exists.
    Prevents duplicate notifications for the same pet and date.
    """
    date = target_date or timezone.now().date()
    sent_count = 0
    skipped_count = 0

    for pet in Pet.objects.select_related("owner").all():
        daily_metrics = PetAnalyticsService.get_daily_summary(
            pet=pet,
            target_date=date,
            include_simulation=False,  # strictly real data
        )

        notif = NotificationDispatcher.dispatch_daily_summary(
            pet=pet,
            daily_metrics=daily_metrics,
            target_date=date,
        )

        if notif:
            sent_count += 1
        else:
            skipped_count += 1

    return {"sent": sent_count, "skipped": skipped_count}


def process_weekly_insights(week_end_date: Optional[timezone.datetime.date] = None) -> Dict[str, int]:
    """
    Evaluates rolling 7-day analytics for all registered pets
    and dispatches a weekly insights push notification to owners if sufficient history exists.
    Prevents duplicate weekly notifications.
    """
    end_date = week_end_date or timezone.now().date()
    sent_count = 0
    skipped_count = 0

    for pet in Pet.objects.select_related("owner").all():
        analytics = PetAnalyticsService.generate_pet_analytics(
            pet=pet,
            include_simulation=False,  # strictly real data
        )

        notif = NotificationDispatcher.dispatch_weekly_insights(
            pet=pet,
            analytics=analytics,
            week_end_date=end_date,
        )

        if notif:
            sent_count += 1
        else:
            skipped_count += 1

    return {"sent": sent_count, "skipped": skipped_count}


class Command(BaseCommand):
    help = "Dispatches daily activity summaries or weekly health insights to pet owners via FCM"

    def add_arguments(self, parser):
        parser.add_argument(
            "--mode",
            type=str,
            choices=["daily", "weekly", "all"],
            default="daily",
            help="Run daily summary, weekly insights, or both",
        )
        parser.add_argument(
            "--date",
            type=str,
            default=None,
            help="Target date in YYYY-MM-DD format (defaults to today)",
        )

    def handle(self, *args, **options):
        mode = options["mode"]
        date_str = options["date"]

        target_date = None
        if date_str:
            target_date = timezone.datetime.strptime(date_str, "%Y-%m-%d").date()

        self.stdout.write(self.style.NOTICE(f"Starting notification batch runner [Mode: {mode}]..."))

        if mode in ["daily", "all"]:
            res_daily = process_daily_summaries(target_date=target_date)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Daily Summaries: {res_daily['sent']} sent, {res_daily['skipped']} skipped."
                )
            )

        if mode in ["weekly", "all"]:
            res_weekly = process_weekly_insights(week_end_date=target_date)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Weekly Insights: {res_weekly['sent']} sent, {res_weekly['skipped']} skipped."
                )
            )
