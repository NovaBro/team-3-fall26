"""The chat loop: Claude asks for tools, Django runs them, Claude answers."""

import logging
from dataclasses import dataclass, field

from django.conf import settings

from assistant.llm import get_client
from assistant.profile import preferences, render_context
from assistant.prompts import CHAT_SYSTEM_PROMPT
from assistant.tools import TOOLS, ToolRunner

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 4
MAX_CARDS = 5
MAX_TOKENS = 3000  # Thinking counts toward this, so leave room beyond the reply.
FALLBACK_REPLY = "Sorry, I couldn't come up with an answer. Please try rephrasing."
REFUSAL_REPLY = "Sorry, I can't help with that. I can help you find food in NYC."
CUT_OFF_NOTE = "\n\n(My answer was cut off. Ask me to continue.)"


@dataclass
class ChatResult:
    reply: str
    places: list = field(default_factory=list)


def _text(response):
    return "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()


def _create(client, system, messages, **extra):
    response = client.messages.create(
        model=settings.ASSISTANT_MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        tools=TOOLS,
        messages=messages,
        output_config={"effort": "low"},
        **extra,
    )
    usage = response.usage
    logger.info(
        "Assistant call: stop=%s input=%s output=%s cache_read=%s",
        response.stop_reason,
        usage.input_tokens,
        usage.output_tokens,
        usage.cache_read_input_tokens,
    )
    return response


def _final_reply(response):
    if response.stop_reason == "refusal":
        return REFUSAL_REPLY
    text = _text(response)
    if response.stop_reason == "max_tokens":
        return (text + CUT_OFF_NOTE) if text else FALLBACK_REPLY
    return text or FALLBACK_REPLY


def run_chat(user, history, message, location=None, location_status="not shared"):
    """Answer *message*. *history* is a list of {"role", "text"} earlier turns.

    *location* is (lat, lng) for tools only. The model just sees the status.

    Earlier turns are replayed as plain text. Within this turn the assistant's
    blocks are sent back unchanged, as the API requires for thinking blocks.
    """
    prefs = preferences(user)
    runner = ToolRunner(user, location=location)
    system = [
        {
            "type": "text",
            "text": CHAT_SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": render_context(prefs, location_status)},
    ]
    messages = [{"role": turn["role"], "content": turn["text"]} for turn in history]
    messages.append({"role": "user", "content": message})

    client = get_client()
    for _round in range(MAX_TOOL_ROUNDS):
        response = _create(client, system, messages)
        if response.stop_reason != "tool_use":
            break
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            content, is_error = runner.run(block.name, block.input)
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content,
                    "is_error": is_error,
                }
            )
        messages.append({"role": "user", "content": results})
    else:
        # Out of rounds: make Claude answer with what it has.
        response = _create(client, system, messages, tool_choice={"type": "none"})

    reply = _final_reply(response)
    return ChatResult(
        reply=reply,
        places=mentioned_places(reply, runner.places),
    )


def _normalize(text):
    return text.replace("’", "'").casefold()


def mentioned_places(reply, places):
    """Cards for places a tool returned and the reply names, in reply order."""
    text = _normalize(reply)
    found = {}
    for place in places.values():
        name = _normalize(place["name"])
        position = text.find(name)
        if position >= 0 and name not in found:
            found[name] = (position, place)
    ordered = sorted(found.values(), key=lambda pair: pair[0])
    return [place for _position, place in ordered][:MAX_CARDS]
