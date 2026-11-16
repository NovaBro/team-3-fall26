"""Outline SVG icons from Tabler Icons (health goal cards, daily check-in).

Tabler Icons (https://tabler.io/icons) - MIT License, Copyright (c) 2020-2024
Pawel Kuna. Only the path data is copied, so no icon font or CDN is needed;
``stroke="currentColor"`` makes an icon follow the text color (and dark mode).
"""

from django.utils.html import format_html_join
from django.utils.safestring import mark_safe

# Tabler icon name -> SVG path data
ICON_PATHS = {
    "scale": (
        "M7 20l10 0",
        "M6 6l6 -1l6 1",
        "M12 3l0 17",
        "M9 12l-3 -6l-3 6a3 3 0 0 0 6 0",
        "M21 12l-3 -6l-3 6a3 3 0 0 0 6 0",
    ),
    "barbell": (
        "M2 12h1",
        "M6 8h-2a1 1 0 0 0 -1 1v6a1 1 0 0 0 1 1h2",
        "M6 7v10a1 1 0 0 0 1 1h1a1 1 0 0 0 1 -1v-10a1 1 0 0 0 -1 -1h-1a1 1 0 0 0 -1 1",
        "M9 12h6",
        "M15 7v10a1 1 0 0 0 1 1h1a1 1 0 0 0 1 -1v-10a1 1 0 0 0 -1 -1h-1a1 1 0 0 0 -1 1",
        "M18 8h2a1 1 0 0 1 1 1v6a1 1 0 0 1 -1 1h-2",
        "M22 12h-1",
    ),
    "heartbeat": (
        "M19.5 13.572l-7.5 7.428l-2.896 -2.868m-6.117 -8.104a5 5 0 0 1 9.013 -3.022a5 5 0 1 1 7.5 6.572",  # noqa: E501
        "M3 13h2l2 3l2 -6l1 3h3",
    ),
    "candy-off": (
        "M11.174 7.17l.119 -.12a2 2 0 0 1 2.828 0l2.829 2.83a2 2 0 0 1 0 2.828l-.124 .124m-2 2l-2.123 2.123a2 2 0 0 1 -2.828 0l-2.829 -2.831a2 2 0 0 1 0 -2.828l2.113 -2.112",  # noqa: E501
        "M16.243 9.172l3.086 -.772a1.5 1.5 0 0 0 .697 -2.516l-2.216 -2.217a1.5 1.5 0 0 0 -2.44 .47l-1.248 2.913",  # noqa: E501
        "M9.172 16.243l-.772 3.086a1.5 1.5 0 0 1 -2.516 .697l-2.217 -2.216a1.5 1.5 0 0 1 .47 -2.44l2.913 -1.248",  # noqa: E501
        "M3 3l18 18",
    ),
    "salad": (
        "M4 11h16a1 1 0 0 1 1 1v.5c0 1.5 -2.517 5.573 -4 6.5v1a1 1 0 0 1 -1 1h-8a1 1 0 0 1 -1 -1v-1c-1.687 -1.054 -4 -5 -4 -6.5v-.5a1 1 0 0 1 1 -1",  # noqa: E501
        "M18.5 11c.351 -1.017 .426 -2.236 .5 -3.714v-1.286h-2.256c-2.83 0 -4.616 .804 -5.64 2.076",  # noqa: E501
        "M5.255 11.008a12.204 12.204 0 0 1 -.255 -2.008v-1h1.755c.98 0 1.801 .124 2.479 .35",  # noqa: E501
        "M8 8l1 -4l4 2.5",
        "M13 11v-.5a2.5 2.5 0 1 0 -5 0v.5",
    ),
    "bread-off": (
        "M8 4l10 .005v-.005a3 3 0 0 1 2 5.235v6.765m-.59 3.418c-.36 .36 -.86 .582 -1.41 .582h-12a2 2 0 0 1 -2 -2v-8.764a3 3 0 0 1 .418 -4.785",  # noqa: E501
        "M3 3l18 18",
    ),
    "mood-cry": (
        "M9 10l.01 0",
        "M15 10l.01 0",
        "M9.5 15.25a3.5 3.5 0 0 1 5 0",
        "M17.566 17.606a2 2 0 1 0 2.897 .03l-1.463 -1.636l-1.434 1.606",
        "M20.865 13.517a8.937 8.937 0 0 0 .135 -1.517a9 9 0 1 0 -9 9c.69 0 1.36 -.076 2 -.222",  # noqa: E501
    ),
    "mood-sad": (
        "M3 12a9 9 0 1 0 18 0a9 9 0 1 0 -18 0",
        "M9 10l.01 0",
        "M15 10l.01 0",
        "M9.5 15.25a3.5 3.5 0 0 1 5 0",
    ),
    "mood-empty": (
        "M3 12a9 9 0 1 0 18 0a9 9 0 1 0 -18 0",
        "M9 10l.01 0",
        "M15 10l.01 0",
        "M9 15l6 0",
    ),
    "mood-smile": (
        "M3 12a9 9 0 1 0 18 0a9 9 0 1 0 -18 0",
        "M9 10l.01 0",
        "M15 10l.01 0",
        "M9.5 15a3.5 3.5 0 0 0 5 0",
    ),
    "mood-happy": (
        "M3 12a9 9 0 1 0 18 0a9 9 0 1 0 -18 0",
        "M9 9l.01 0",
        "M15 9l.01 0",
        "M8 13a4 4 0 1 0 8 0h-8",
    ),
    "battery": (
        "M6 7h11a2 2 0 0 1 2 2v.5a.5 .5 0 0 0 .5 .5a.5 .5 0 0 1 .5 .5v3a.5 .5 0 0 1 -.5 .5a.5 .5 0 0 0 -.5 .5v.5a2 2 0 0 1 -2 2h-11a2 2 0 0 1 -2 -2v-6a2 2 0 0 1 2 -2",  # noqa: E501
    ),
    "battery-1": (
        "M6 7h11a2 2 0 0 1 2 2v.5a.5 .5 0 0 0 .5 .5a.5 .5 0 0 1 .5 .5v3a.5 .5 0 0 1 -.5 .5a.5 .5 0 0 0 -.5 .5v.5a2 2 0 0 1 -2 2h-11a2 2 0 0 1 -2 -2v-6a2 2 0 0 1 2 -2",  # noqa: E501
        "M7 10l0 4",
    ),
    "battery-2": (
        "M6 7h11a2 2 0 0 1 2 2v.5a.5 .5 0 0 0 .5 .5a.5 .5 0 0 1 .5 .5v3a.5 .5 0 0 1 -.5 .5a.5 .5 0 0 0 -.5 .5v.5a2 2 0 0 1 -2 2h-11a2 2 0 0 1 -2 -2v-6a2 2 0 0 1 2 -2",  # noqa: E501
        "M7 10l0 4",
        "M10 10l0 4",
    ),
    "battery-3": (
        "M6 7h11a2 2 0 0 1 2 2v.5a.5 .5 0 0 0 .5 .5a.5 .5 0 0 1 .5 .5v3a.5 .5 0 0 1 -.5 .5a.5 .5 0 0 0 -.5 .5v.5a2 2 0 0 1 -2 2h-11a2 2 0 0 1 -2 -2v-6a2 2 0 0 1 2 -2",  # noqa: E501
        "M7 10l0 4",
        "M10 10l0 4",
        "M13 10l0 4",
    ),
    "battery-4": (
        "M6 7h11a2 2 0 0 1 2 2v.5a.5 .5 0 0 0 .5 .5a.5 .5 0 0 1 .5 .5v3a.5 .5 0 0 1 -.5 .5a.5 .5 0 0 0 -.5 .5v.5a2 2 0 0 1 -2 2h-11a2 2 0 0 1 -2 -2v-6a2 2 0 0 1 2 -2",  # noqa: E501
        "M7 10l0 4",
        "M10 10l0 4",
        "M13 10l0 4",
        "M16 10l0 4",
    ),
}

GOAL_ICONS = {
    "weight-loss": "scale",
    "muscle-gain": "barbell",
    "heart-health": "heartbeat",
    "less-sugar": "candy-off",
    "balanced-diet": "salad",
    "low-carb": "bread-off",
}
# 1-5 check-in values (accounts.models.MoodLog choices)
MOOD_ICONS = {
    1: "mood-cry",
    2: "mood-sad",
    3: "mood-empty",
    4: "mood-smile",
    5: "mood-happy",
}
ENERGY_ICONS = {
    1: "battery",
    2: "battery-1",
    3: "battery-2",
    4: "battery-3",
    5: "battery-4",
}


def icon(name, css_class="icon", size=22):
    """Inline SVG for a Tabler icon name, or "" when it is unknown."""
    paths = ICON_PATHS.get(name)
    if not paths:
        return ""
    inner = format_html_join("", '<path d="{}"/>', ((d,) for d in paths))
    return mark_safe(
        f'<svg class="{css_class}" xmlns="http://www.w3.org/2000/svg" '
        f'width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        f'stroke-linejoin="round" aria-hidden="true">{inner}</svg>'
    )


def goal_icon(goal):
    """Icon for a health goal card, or ""."""
    return icon(GOAL_ICONS.get(goal, ""), "goal-card__icon")
