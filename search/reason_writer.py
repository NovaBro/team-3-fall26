"""Turn a restaurant's reason list into a short, natural paragraph with Gemini.

The detail page writes a paragraph on a restaurant's first visit (when
GEMINI_API_KEY is set) and stores it in community.ReasonBlurb; later visits
read the stored one. ``python manage.py write_reasons`` can fill many ahead of
time. With no key, or if Gemini fails, the page shows the plain reason list.

Only facts we computed ourselves go into the prompt (no Google review text:
Google's terms bar building content from it; the page shows Google's own
review summary instead). The prompt tells the model not to add anything else.
"""

import os
import re
from functools import lru_cache

from django.conf import settings

DEFAULT_MODEL = "gemini-3.5-flash-lite"
LIVE_TIMEOUT_MS = 12000  # Gemini needs at least 10 s; page waits at most this long
PROMPT_VERSION = "v2"  # bump when the prompt changes; older paragraphs are redone
MAX_CHARS = 320

PROMPT = """You write one short note for a healthy-restaurant finder in New York City.
Explain to a diner why this restaurant is a good healthy pick.

Rules:
- One or two sentences, at most 40 words, plain English.
- Use ONLY the facts below. Do not invent dishes, prices, awards, reviews,
  places nearby, or numbers that are not there.
- No emojis, hashtags, quotation marks, or exclamation marks.
- Do not start with the restaurant's name.

Restaurant: {name}
Cuisine: {cuisine}
Facts:
{facts}
"""


class RateLimited(Exception):
    """Gemini said we sent too many requests (HTTP 429)."""


def build_prompt(name, cuisine, reasons):
    facts = "\n".join(f"- {reason}" for reason in reasons) or "- (none)"
    return PROMPT.format(
        name=name or "Unknown", cuisine=cuisine or "Unknown", facts=facts
    )


def model_tag(model_name):
    """What we store in ReasonBlurb.model_name: model plus prompt version."""
    return f"{model_name}|{PROMPT_VERSION}"


def is_current(stored_tag):
    """True if a stored paragraph was written with the current prompt."""
    return (stored_tag or "").endswith(f"|{PROMPT_VERSION}")


def clean_output(text):
    """Tidy the model's answer; return "" if it is not usable."""
    text = " ".join((text or "").split())
    text = text.strip(" \"'“”‘’")
    if not text or "http" in text.lower() or "<" in text:
        return ""
    if len(text) > MAX_CHARS:
        cut = text[:MAX_CHARS]
        end = max(cut.rfind(". "), cut.rfind("."))
        text = cut[: end + 1] if end > 40 else ""
    return re.sub(r"\s+([.,;])", r"\1", text)


def write_blurb(name, cuisine, reasons, generate):
    """Return a cleaned paragraph, or "" when there is nothing to say.

    ``generate`` takes a prompt and returns the model's text (a fake in
    tests, Gemini in the command).
    """
    if not reasons:
        return ""
    return clean_output(generate(build_prompt(name, cuisine, reasons)))


def gemini_generate(model_name=DEFAULT_MODEL, api_key=None, timeout_ms=None):
    """Return a ``generate(prompt) -> text`` function backed by Gemini."""
    api_key = (
        api_key
        or getattr(settings, "GEMINI_API_KEY", "")
        or os.environ.get("GEMINI_API_KEY", "")
    )
    if not api_key:
        raise RuntimeError("Set GEMINI_API_KEY in .env (from aistudio.google.com).")
    try:
        from google import genai
    except ImportError as exc:  # pragma: no cover - depends on local install
        raise RuntimeError(
            "google-genai is not installed. Run: pip install -r requirements-ml.txt"
        ) from exc
    options = {"timeout": timeout_ms} if timeout_ms else None
    client = genai.Client(api_key=api_key, http_options=options)

    def generate(prompt):
        try:
            response = client.models.generate_content(model=model_name, contents=prompt)
        except Exception as exc:
            if getattr(exc, "code", None) in (402, 429) or "RESOURCE_EXHAUSTED" in str(
                exc
            ):
                raise RateLimited(str(exc)) from exc
            raise
        return response.text or ""

    return generate


@lru_cache(maxsize=1)
def live_generate():
    """One shared Gemini client for detail-page requests (short timeout)."""
    return gemini_generate(
        settings.GEMINI_MODEL, settings.GEMINI_API_KEY, timeout_ms=LIVE_TIMEOUT_MS
    )
