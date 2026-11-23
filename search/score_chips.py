"""Plain-words chips for the restaurant score: what helped, what held it back.

Built from the score breakdown's steps (search/recommend.py), so no new data
and no API calls. Numbers stay in the "See how it's calculated" section.
"""

import re

_NUM = re.compile(r"^\s*([+\-−])\s*0*\.?0*([0-9.]*)")


def _signed(value):
    """+1, -1 or 0 from a step value like "+0.20", "−0.10", "0"."""
    m = _NUM.match(str(value))
    if not m:
        return 0
    try:
        amount = float(m.group(2) or 0)
    except ValueError:
        amount = 0
    if amount == 0:
        return 0
    return 1 if m.group(1) == "+" else -1


def _clean(label):
    label = str(label)
    if label.startswith("Cuisine ("):
        return label[len("Cuisine ("):].rstrip(")") + " cuisine"
    if label.startswith("AI review score"):
        return "Reviews sound healthy"
    if label.startswith("Review keywords"):
        return "Reviews mention healthy food"
    return re.sub(r"\s*\(.*?\)\s*$", "", label)


def build_chips(breakdown):
    """{"helped": [...], "held": [...], "notes": [...]} for the template."""
    helped, held, notes = [], [], []
    if not breakdown:
        return {"helped": helped, "held": held, "notes": notes}
    for part in breakdown.get("parts") or []:
        label = str(part.get("label", ""))
        steps = part.get("steps") or []
        value = part.get("value_0_1") or 0
        if label.startswith("Rating"):
            google = next((v for k, v in steps if k == "Google"), "")
            m = re.match(r"([0-9.]+)★ \(([\d,]+) reviews\)", str(google))
            text = f"{m.group(1)}★ from {m.group(2)} reviews" if m else "Ratings"
            (helped if value >= 0.6 else held if value < 0.4 else notes).append(text)
            continue
        for key, val in steps:
            key = str(key)
            if "estimated menu" in key.lower() or key.startswith("AI-estimated menu"):
                kcal = re.search(r"~?(\d{3,4}) kcal", key)
                if kcal:
                    try:
                        score = float(str(val).split()[0])
                    except ValueError:
                        score = None
                    text = f"Meals around {kcal.group(1)} kcal"
                    if score is not None and score >= 0.6:
                        helped.append(text)
                    elif score is not None:
                        held.append(text)
                continue
            sign = _signed(val)
            if sign > 0:
                helped.append(_clean(key))
            elif sign < 0:
                if key.startswith("AI review score"):
                    held.append("Reviews don't sound very healthy")
                elif key.startswith("Review keywords"):
                    held.append("Reviews mention less healthy food")
                else:
                    held.append(_clean(key))
    if not breakdown.get("has_menu"):
        notes.append("Menu is estimated" if breakdown.get("estimated_menu_health") is not None else "No menu data yet")
    seen = set()

    def uniq(items):
        out = []
        for x in items:
            if x and x not in seen:
                seen.add(x)
                out.append(x)
        return out[:5]

    return {"helped": uniq(helped), "held": uniq(held), "notes": uniq(notes)}
