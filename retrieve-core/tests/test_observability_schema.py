"""Contract tests for structured JSONL observability events."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import retrieve.observability as obs


@pytest.fixture
def isolated_observability(monkeypatch, tmp_path: Path) -> Path:
    """Reset module globals so each test gets an isolated JSONL sink."""
    log_path = tmp_path / "retrieve-test.jsonl"
    monkeypatch.setattr(obs, "_sink", None)
    monkeypatch.setattr(obs, "_event_journal", None)
    obs.configure_observability(log_path=log_path)
    return log_path


def _read_events(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_jsonl_schema_success_path(isolated_observability: Path):
    with obs.operation(
        "test.success", source="test", metadata={"suite": "schema"}, operation_id="op-success"
    ):
        with obs.step("phase.load", sample="ok"):
            obs.emit_progress("Progress ping")

    events = _read_events(isolated_observability)
    assert events, "Expected at least one event"

    required_common = {"schema_version", "timestamp", "event_type", "level", "message"}
    for event in events:
        assert required_common.issubset(event.keys())
        assert event["schema_version"] == 1
        assert isinstance(event["timestamp"], str)
        assert isinstance(event["event_type"], str)
        assert isinstance(event["level"], str)
        assert isinstance(event["message"], str)

        # All events emitted inside operation/step contexts must carry operation fields.
        assert event["operation_id"] == "op-success"
        assert event["operation_name"] == "test.success"
        assert event["operation_source"] == "test"
        assert isinstance(event["operation_elapsed_ms"], int)
        assert isinstance(event["operation_metadata"], dict)

    by_type = {e["event_type"]: e for e in events}
    assert by_type["operation_start"]["message"].startswith("Operation started")
    assert by_type["step_start"]["step_name"] == "phase.load"
    assert by_type["step_end"]["step_name"] == "phase.load"
    assert by_type["step_end"]["status"] == "success"
    assert isinstance(by_type["step_end"]["duration_ms"], int)
    assert by_type["progress"]["stage"] == "general"
    assert by_type["operation_end"]["status"] == "success"


def test_jsonl_schema_failure_path(isolated_observability: Path):
    with pytest.raises(RuntimeError):
        with obs.operation("test.failure", source="test", operation_id="op-fail"):
            with obs.step("phase.fail"):
                raise RuntimeError("boom")

    events = _read_events(isolated_observability)
    assert events, "Expected events in failure path"

    error_events = [e for e in events if e["event_type"] == "error"]
    assert error_events, "Failure path should emit error event"
    err = error_events[-1]
    assert err["operation_id"] == "op-fail"
    assert err["stage"] == "general"
    assert err["exception_type"] == "RuntimeError"
    assert "boom" in err["exception_message"]
    assert "RuntimeError" in err["traceback"]

    step_end = [e for e in events if e["event_type"] == "step_end"][-1]
    op_end = [e for e in events if e["event_type"] == "operation_end"][-1]
    assert step_end["status"] == "failed"
    assert op_end["status"] == "failed"


@pytest.mark.asyncio
async def test_sse_replays_durable_events_with_sequence_ids(
    isolated_observability: Path,
):
    journal: list[dict] = []

    def persist(event: dict) -> int:
        sequence = len(journal) + 1
        journal.append({**event, "event_sequence": sequence})
        return sequence

    obs.configure_event_journal(persist)
    with obs.operation("test.replay", source="test", operation_id="op-replay"):
        obs.emit_progress("persisted progress", stage="phase.persist")

    def load(operation_id: str, after_sequence: int) -> list[dict]:
        return [
            event
            for event in journal
            if event["operation_id"] == operation_id and event["event_sequence"] > after_sequence
        ]

    chunks = [
        chunk
        async for chunk in obs.sse_event_stream(
            "op-replay",
            event_loader=load,
            after_sequence=1,
            done=True,
        )
    ]

    assert chunks[-1] == "event: done\ndata: \n\n"
    assert all("id: 1\n" not in chunk for chunk in chunks)
    assert any("persisted progress" in chunk for chunk in chunks)
    assert any(chunk.startswith("id: 2\n") for chunk in chunks)
