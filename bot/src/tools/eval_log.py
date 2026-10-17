"""Decision records emitted for the eval corpus.

One plain JSON line per decision on stdout. Cloud Run parses a stdout line that
is valid JSON into a structured `jsonPayload`, which is what the BigQuery sink
filters and what eval later reads — so the contract is the line being pure JSON,
nothing wrapping or prefixing it.

The payload is flat: a nested object becomes a BigQuery RECORD, which breaks
rows when the shape changes, while flat keys stay queryable as plain columns.
"""

import json
from datetime import UTC, datetime
from typing import Any

# Cloud Logging reads this key off a structured line instead of guessing.
_SEVERITY = "INFO"


def log_decision(ticker: str, prompt: str, response: dict[str, Any]) -> None:
    """Record one decision. Never raises: a corpus is not worth a lost verdict."""
    try:
        record = {
            **response,
            "severity": _SEVERITY,
            "event_type": "decision",
            "ts": datetime.now(UTC).isoformat(),
            "ticker": ticker,
            "prompt": prompt,
        }
        print(json.dumps(record), flush=True)
    except Exception:  # noqa: BLE001 — capture must never break the decision
        pass
