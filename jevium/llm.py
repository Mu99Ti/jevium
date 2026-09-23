"""One generative helper for planner/verifier; Jev itself never generates text."""

import json
import os

from jevium_core.model import post_json


def chat_json(system: str, user: str, model: str | None = None) -> str:
    key = os.environ.get("TEXT_MODEL_API_KEY")
    if not key:
        raise ValueError("TEXT_MODEL_API_KEY is required for this call.")
    base = os.environ.get("TEXT_MODEL_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
    model = model or os.environ.get("TEXT_MODEL", "deepseek-chat")
    reasoning = {"reasoning": {"enabled": False}} if os.environ.get("TEXT_MODEL_REASONING") == "none" else {}
    result = post_json(
        base + "/chat/completions",
        key,
        {
            "model": model,
            "max_tokens": 1024,
            "response_format": {"type": "json_object"},
            **reasoning,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
    )
    try:
        content = result["choices"][0]["message"]["content"]
        json.loads(content)
    except (KeyError, IndexError, TypeError, ValueError):
        raise ValueError("Model returned no valid JSON object.") from None
    return content
