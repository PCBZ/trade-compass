"""Unit tests for the decision record emitted as the eval corpus.

The whole BigQuery sink rests on one fragile property: the line must be *pure*
valid JSON on stdout, because that is the only thing Cloud Run promotes to a
structured `jsonPayload`. A stray prefix (a logging formatter, a banner) turns
every record into unparsed text and the corpus silently becomes worthless, so
that property is worth a test of its own.
"""

from __future__ import annotations

import json

from src.agents.decision import _log_decision


def test_emits_a_parseable_record_with_the_expected_fields(capsys):
    _log_decision("MU", "PROMPT TEXT", {"verdict": "BUY", "confidence": "high"})

    record = json.loads(capsys.readouterr().out.strip())
    assert record["event_type"] == "decision"  # the sink filter keys on this
    assert record["ticker"] == "MU"
    assert record["prompt"] == "PROMPT TEXT"
    assert record["response"] == {"verdict": "BUY", "confidence": "high"}
    assert record["ts"]


def test_line_is_pure_json_with_no_prefix(capsys):
    """A logging formatter's timestamp prefix would break jsonPayload parsing."""
    _log_decision("MU", "p", {})
    out = capsys.readouterr().out.strip()
    assert out.startswith("{")
    assert out.endswith("}")
    assert len(out.splitlines()) == 1  # one record per line


def test_the_prompt_is_not_truncated(capsys):
    """Eval needs the exact prompt; a judge cannot check grounding against a stub."""
    prompt = "x" * 20_000
    _log_decision("MU", prompt, {})
    assert json.loads(capsys.readouterr().out)["prompt"] == prompt


def test_capture_failure_never_breaks_the_decision(capsys):
    """A corpus is not worth losing a verdict over."""

    class Unserializable:
        pass

    _log_decision("MU", "p", {"bad": Unserializable()})  # must not raise
    assert capsys.readouterr().out == ""
