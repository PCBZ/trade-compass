"""Unit tests for the decision record emitted as the eval corpus.

The sink rests on one fragile property: the line must be pure valid JSON on
stdout, because that is the only thing Cloud Run promotes to a structured
`jsonPayload`. A stray prefix turns every record into unparsed text and the
corpus silently becomes worthless, so it is worth a test of its own.
"""

from __future__ import annotations

import json
import logging

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


def test_capture_failure_warns_without_leaking_the_record(capsys, caplog):
    """A corpus is not worth losing a verdict over — but losing one *silently*
    is the failure this corpus exists to prevent, so it has to say something.

    Only the exception type and ticker: the record carries real positions, and
    a warning goes to ordinary logs rather than the sink's dataset.
    """

    class Unserializable:
        pass

    prompt = "Weight: 19.5% of portfolio | Cost basis: $1,068.27 per share"
    with caplog.at_level(logging.WARNING):
        log_decision("MU", prompt, {"bad": Unserializable()})  # must not raise

    assert capsys.readouterr().out == ""  # nothing half-written to the corpus
    assert "MU" in caplog.text
    assert "TypeError" in caplog.text
    assert "1,068.27" not in caplog.text
    assert prompt not in caplog.text
