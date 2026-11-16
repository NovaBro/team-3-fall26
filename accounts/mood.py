"""Daily mood / energy check-ins (one MoodLog per user per NY calendar day)."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

from accounts.models import MoodLog

NYC_TZ = ZoneInfo("America/New_York")


def today_ny(when=None) -> date:
    """America/New_York calendar date for *when* (default: now)."""
    moment = when or timezone.now()
    if timezone.is_naive(moment):
        moment = timezone.make_aware(moment, timezone.get_current_timezone())
    return moment.astimezone(NYC_TZ).date()


def upsert_today_mood(user, mood, energy_level, *, when=None) -> MoodLog:
    """Create or update today's MoodLog for *user* (America/New_York day)."""
    day = today_ny(when)
    log, _created = MoodLog.objects.update_or_create(
        user=user,
        log_date=day,
        defaults={"mood": mood, "energy_level": energy_level},
    )
    return log


def latest_check_in_for(user, *, when=None) -> MoodLog | None:
    """Today's NY check-in if any, else the newest log updated within 24 hours."""
    moment = when or timezone.now()
    if isinstance(moment, datetime) and timezone.is_naive(moment):
        moment = timezone.make_aware(moment, timezone.get_current_timezone())
    today = today_ny(moment)
    today_log = MoodLog.objects.filter(user=user, log_date=today).first()
    if today_log is not None:
        return today_log
    since = moment - timedelta(hours=24)
    return (
        MoodLog.objects.filter(user=user)
        .filter(updated_at__gte=since)
        .order_by("-updated_at", "-created_at")
        .first()
    )
