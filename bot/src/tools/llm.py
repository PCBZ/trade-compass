"""LLM client via OpenRouter.

Model is selected dynamically from user preferences (set via /model in Telegram).
Available models are defined in bot/config.json.
Default model is whichever entry has "default": true in config.json.

Every configured model is a `:free` variant, which OpenRouter serves from a pool
shared across all of its users. When that pool saturates the provider answers 429
with no warning, so a single-model call fails for reasons that have nothing to do
with our request — hence `ainvoke_with_fallback`.
"""

import logging
import os
from typing import Any, Type

from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from ..config import get_default_model_id, get_model_ids

log = logging.getLogger(__name__)

_OPENROUTER_BASE = "https://openrouter.ai/api/v1"


def get_llm(
    model: str | None = None,
    output_schema: Type[BaseModel] | None = None,
) -> Any:
    """
    Returns a LangChain ChatOpenAI client pointed at OpenRouter.

    Model priority:
      1. model argument (from user preferences, set via /model in Telegram)
      2. default model defined in bot/config.json

    If output_schema is provided, returns llm.with_structured_output(schema)
    which guarantees the response is parsed into the given Pydantic model.

    Prefer ainvoke_with_fallback() for anything user-facing — it survives a
    saturated free pool, which this client alone does not.
    """
    model = model or get_default_model_id()

    llm = ChatOpenAI(
        model=model,
        openai_api_key=os.environ.get("OPENROUTER_API_KEY", ""),
        openai_api_base=_OPENROUTER_BASE,
        temperature=0.2,  # low temperature for consistent financial analysis
    )

    if output_schema is not None:
        return llm.with_structured_output(output_schema)

    return llm


def _fallback_order(preferred: str | None) -> list[str]:
    """Preferred model first, then every other configured one."""
    preferred = preferred or get_default_model_id()
    return [preferred] + [m for m in get_model_ids() if m != preferred]


async def ainvoke_with_fallback(
    prompt: str,
    output_schema: Type[BaseModel],
    preferred: str | None = None,
) -> Any:
    """Invoke the preferred model, falling through the rest if it fails.

    Retrying the same model is usually pointless: a saturated free pool stays
    saturated for minutes, and a model whose free tier was withdrawn answers 404
    forever. Another provider's pool is the thing likely to work right now.

    Raises the last error if every configured model fails.
    """
    models = _fallback_order(preferred)
    last: Exception | None = None

    for i, model in enumerate(models):
        try:
            result = await get_llm(model, output_schema).ainvoke(prompt)
            if i:
                log.warning("answered by fallback model %s", model)
            return result
        except Exception as exc:  # noqa: BLE001 — any failure is worth a fallback
            log.warning("model %s failed: %r", model, exc)
            last = exc

    raise last if last else RuntimeError("no LLM models configured")
