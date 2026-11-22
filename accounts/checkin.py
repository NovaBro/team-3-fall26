"""Today's mood / energy check-in, as used on the home page.

The home page saves mood and energy one at a time (a dropdown each next to
the Top picks title). Both go into the same MoodLog row for the day, so the
profile's check-in history still shows one line per day from the home page.
"Today" is the New York calendar day.

The banner above Top picks shows a headline that matches today's check-in.
Ranking may also use today's MoodLog when both mood and energy are set.
"""

from datetime import datetime, time
from zoneinfo import ZoneInfo

from accounts.goal_icons import ENERGY_ICONS, MOOD_ICONS, icon
from accounts.models import MoodLog
from accounts.mood import today_ny

NEW_YORK = ZoneInfo("America/New_York")
EMPTY_ICONS = {"mood": "mood-plus", "energy": "battery-charging"}
FIELDS = {"mood": "mood", "energy": "energy_level"}

DEFAULT_HEADLINE = ("Down for a healthy bite?", "Find your place, your way")

# (mood level, energy level) -> (headline, line under it). Levels: 2 high
# (Good, Great / Alert, Energized), 1 middle (Okay), 0 low (the two lowest).
HEADLINES = {
    (2, 2): ("Ready for something great?", "Big energy, bigger flavors"),
    (2, 1): ("Good day for a good meal", "Fresh picks to match your mood"),
    (2, 0): ("Recharge, deliciously", "Easy, nourishing picks for a slow day"),
    (1, 2): ("Up for something new?", "Try a place you haven't been"),
    (1, 1): ("Just a solid meal today", "Healthy picks, no fuss"),
    (1, 0): ("Running on low?", "Simple, fresh plates to refuel"),
    (0, 2): ("Shake off the day", "Treat yourself to something fresh"),
    (0, 1): ("Something to look forward to", "A little comfort, still healthy"),
    (0, 0): ("Take it easy today", "Comforting picks, no pressure"),
}


def _level(value):
    """1-5 scale -> 0 low, 1 middle, 2 high; None stays None."""
    if value is None:
        return None
    if value >= 4:
        return 2
    if value == 3:
        return 1
    return 0


def headline(mood=None, energy=None):
    """(headline, line) for today's mood and energy (1-5, or None)."""
    mood_level, energy_level = _level(mood), _level(energy)
    if mood_level is None and energy_level is None:
        return DEFAULT_HEADLINE
    # Only one picked: treat the other as middle.
    key = (
        1 if mood_level is None else mood_level,
        1 if energy_level is None else energy_level,
    )
    return HEADLINES[key]


def start_of_today(now=None):
    """The start of today in New York, as an aware datetime."""
    now = (now or datetime.now(NEW_YORK)).astimezone(NEW_YORK)
    return datetime.combine(now.date(), time.min, tzinfo=NEW_YORK)


def todays_log(user, now=None):
    """The user's check-in for today's New York calendar day, or None."""
    if user is None or not user.is_authenticated:
        return None
    return MoodLog.objects.filter(user=user, log_date=today_ny(now)).first()


def save_today(user, kind, value, now=None):
    """Set today's mood or energy (kind "mood" / "energy", value 1-5).

    Updates today's latest check-in, or starts one with only this field.
    """
    field = FIELDS[kind]
    log = todays_log(user, now)
    if log is None:
        log = MoodLog(user=user)
    setattr(log, field, value)
    log.save()
    return log


def _options(choices, icons):
    # Best first, the way the dropdown lists them.
    return [
        {
            "value": value,
            "label": label,
            "icon": icon(icons[value], "mood-pick__ic", 20),
        }
        for value, label in reversed(choices)
    ]


def picker_context(user, now=None):
    """Template context for the home page check-in dropdowns and banner."""
    log = todays_log(user, now)
    mood = log.mood if log else None
    energy = log.energy_level if log else None
    title, lede = headline(mood, energy)

    def current(kind, value, icons, choices):
        if value is None:
            return {
                "value": None,
                "label": "",
                "icon": icon(EMPTY_ICONS[kind], "mood-pick__ic", 22),
            }
        return {
            "value": value,
            "label": dict(choices)[value],
            "icon": icon(icons[value], "mood-pick__ic", 22),
        }

    return {
        "hero_title": title,
        "hero_lede": lede,
        "mood_now": current("mood", mood, MOOD_ICONS, MoodLog.MOOD_CHOICES),
        "energy_now": current("energy", energy, ENERGY_ICONS, MoodLog.ENERGY_CHOICES),
        "mood_options": _options(MoodLog.MOOD_CHOICES, MOOD_ICONS),
        "energy_options": _options(MoodLog.ENERGY_CHOICES, ENERGY_ICONS),
    }
