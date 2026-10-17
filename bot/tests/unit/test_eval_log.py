"""Unit tests for the decision record emitted as the eval corpus.

The sink rests on one fragile property: the line must be pure valid JSON on
stdout, because that is the only thing Cloud Run promotes to a structured
`jsonPayload`. A stray prefix turns every record into unparsed text and the
corpus silently becomes worthless, so it is worth a test of its own.
"""

from __future__ import annotations

import json

from src.tools.eval_log import log_decision


def test_emits_a_parseable_record(capsys):
    log_decision("MU", "PROMPT TEXT", {"verdict": "BUY", "confidence": "high"})

    record = json.loads(capsys.readouterr().out.strip())
    assert record["event_type"] == "decision"  # the sink filter keys on this
    assert record["ticker"] == "MU"
    assert record["prompt"] == "PROMPT TEXT"
    assert record["severity"] == "INFO"
    assert record["ts"]


def test_response_is_flattened_not_nested(capsys):
    """Nested objects become BigQuery RECORDs, which break on a shape change."""
    log_decision("MU", "p", {"verdict": "BUY", "target_price": 1.5})

    record = json.loads(capsys.readouterr().out)
    assert record["verdict"] == "BUY"
    assert record["target_price"] == 1.5
    assert "response" not in record
    assert all(not isinstance(v, dict) for v in record.values())


def test_envelope_wins_over_a_colliding_response_key(capsys):
    log_decision("MU", "p", {"ticker": "WRONG"})
    assert json.loads(capsys.readouterr().out)["ticker"] == "MU"


def test_line_is_pure_json_with_no_prefix(capsys):
    """A logging formatter's timestamp prefix would break jsonPayload parsing."""
    log_decision("MU", "p", {})
    out = capsys.readouterr().out.strip()
    assert out.startswith("{")
    assert out.endswith("}")
    assert len(out.splitlines()) == 1  # one record per line


def test_the_prompt_is_not_truncated(capsys):
    """Eval needs the exact prompt; a judge cannot check grounding against a stub."""
    prompt = "x" * 20_000
    log_decision("MU", prompt, {})
    assert json.loads(capsys.readouterr().out)["prompt"] == prompt


def test_capture_failure_never_breaks_the_decision(capsys):
    """A corpus is not worth losing a verdict over."""

    class Unserializable:
        pass

    log_decision("MU", "p", {"bad": Unserializable()})  # must not raise
    assert capsys.readouterr().out == ""
