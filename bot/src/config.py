"""Bot configuration loader.

Reads config.json at startup. Single source of truth for
configurable options (LLM models, etc.).
"""

import json
from pathlib import Path
from typing import Any

_CONFIG_PATH = Path(__file__).parent / "config.json"


def _load() -> dict[str, Any]:
    with open(_CONFIG_PATH) as f:
        return json.load(f)


_config = _load()


# ── LLM models ────────────────────────────────────────────────────────────────


def get_llm_models() -> list[dict[str, Any]]:
    """Return all configured LLM models."""
    return _config["llm_models"]


def get_default_model_id() -> str:
    """Return the default model ID (marked default=true in config.json)."""
    for m in _config["llm_models"]:
        if m.get("default"):
            return m["id"]
    return _config["llm_models"][0]["id"]


def get_model_ids() -> list[str]:
    """Return all valid model IDs for validation."""
    return [m["id"] for m in _config["llm_models"]]


def is_valid_model(model_id: str) -> bool:
    """Check if a model ID is in the configured list."""
    return model_id in get_model_ids()
