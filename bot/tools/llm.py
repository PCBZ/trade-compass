"""LLM client via OpenRouter.

Model is selected dynamically from user preferences (set via /model in Telegram).
Available models are defined in bot/config.json.
Default model is whichever entry has "default": true in config.json.
"""

from __future__ import annotations

import os
from typing import Any, Type

from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from bot.config import get_default_model_id

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

    Usage:
        llm = get_llm(model="deepseek/deepseek-v4-flash:free", output_schema=DecisionOutput)
        result: DecisionOutput = await llm.ainvoke(prompt)
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
