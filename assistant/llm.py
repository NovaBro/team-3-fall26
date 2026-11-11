"""Shared Anthropic client setup."""

import anthropic
from django.conf import settings


def is_configured():
    return bool(settings.ANTHROPIC_API_KEY)


def get_client(timeout=20.0, max_retries=1):
    return anthropic.Anthropic(
        api_key=settings.ANTHROPIC_API_KEY, timeout=timeout, max_retries=max_retries
    )
