import json
import logging
from functools import wraps

import anthropic
from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from assistant.chat import run_chat
from assistant.llm import is_configured
from search.find_food import in_nyc

logger = logging.getLogger(__name__)

SESSION_KEY = "assistant_history"
MAX_MESSAGE_CHARS = 1000
MAX_HISTORY_TURNS = 20
DAY_SECONDS = 24 * 60 * 60
BUSY = "The assistant is busy right now. Please try again in a minute."
UNAVAILABLE = "The assistant isn't available right now. Please try again later."


def _login_required_json(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Log in to use the assistant."}, status=401)
        return view(request, *args, **kwargs)

    return wrapper


def _over_daily_limit(user):
    """Count this message. The count is per worker process, so it's approximate."""
    key = f"assistant:messages:{user.id}:{timezone.now():%Y-%m-%d}"
    cache.add(key, 0, DAY_SECONDS)
    return cache.incr(key) > settings.ASSISTANT_DAILY_MESSAGES


def _location(body):
    """Return (coordinates, status) from a request. The status goes to the model."""
    lat, lng = body.get("lat"), body.get("lng")
    if lat is None and lng is None:
        return None, "not shared"
    if (
        isinstance(lat, bool)
        or isinstance(lng, bool)
        or not isinstance(lat, (int, float))
        or not isinstance(lng, (int, float))
    ):
        return None, "not shared"
    if not in_nyc(lat, lng):
        return None, "shared, but outside NYC"
    return (float(lat), float(lng)), "shared"


def _trimmed(history):
    history = history[-MAX_HISTORY_TURNS:]
    while history and history[0]["role"] != "user":
        history = history[1:]
    return history


@require_GET
@_login_required_json
def history(request):
    return JsonResponse({"messages": request.session.get(SESSION_KEY, [])})


@require_POST
@_login_required_json
def reset(request):
    request.session.pop(SESSION_KEY, None)
    return JsonResponse({"messages": []})


@require_POST
@_login_required_json
def chat(request):
    if not is_configured():
        return JsonResponse({"error": UNAVAILABLE}, status=503)
    try:
        body = json.loads(request.body)
        message = body.get("message", "")
    except (ValueError, AttributeError):
        return JsonResponse({"error": "Send a message."}, status=400)
    if not isinstance(message, str) or not message.strip():
        return JsonResponse({"error": "Send a message."}, status=400)
    message = message.strip()
    if len(message) > MAX_MESSAGE_CHARS:
        return JsonResponse(
            {"error": f"Keep messages under {MAX_MESSAGE_CHARS} characters."},
            status=400,
        )
    if _over_daily_limit(request.user):
        return JsonResponse(
            {"error": "You've reached today's message limit. Try again tomorrow."},
            status=429,
        )

    turns = _trimmed(request.session.get(SESSION_KEY, []))
    try:
        location, location_status = _location(body)
        result = run_chat(request.user, turns, message, location, location_status)
    except anthropic.RateLimitError:
        return JsonResponse({"error": BUSY}, status=503)
    except anthropic.APIConnectionError:
        logger.warning("Assistant couldn't reach the API", exc_info=True)
        return JsonResponse({"error": BUSY}, status=503)
    except anthropic.APIStatusError as error:
        logger.error(
            "Assistant API error: status=%s request_id=%s",
            error.status_code,
            error.request_id,
        )
        return JsonResponse({"error": UNAVAILABLE}, status=503)

    turns = turns + [
        {"role": "user", "text": message},
        {"role": "assistant", "text": result.reply, "places": result.places},
    ]
    request.session[SESSION_KEY] = _trimmed(turns)
    return JsonResponse({"reply": result.reply, "places": result.places})
