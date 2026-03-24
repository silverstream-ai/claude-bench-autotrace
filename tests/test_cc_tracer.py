import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

from cc_tracer import process_event, run_hook
from opentelemetry.trace import Tracer
from pytest import CaptureFixture

from cc_tracer_lib.models import SEEN_EVENTS_MAX, HookEvent, SessionState


def _make_session_start_event() -> HookEvent:
    return HookEvent(
        hook_event_name="SessionStart",
        session_id="test-session-123",
        cwd="/tmp",
        transcript_path="/tmp/transcript.jsonl",
    )


def _make_pre_tool_use(session_id: str, tool_use_id: str) -> dict[str, Any]:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": session_id,
        "cwd": "/tmp",
        "transcript_path": "/tmp/transcript.jsonl",
        "tool_use_id": tool_use_id,
    }


def test_process_event_session_start_sends_structured_output(capsys: CaptureFixture[str]) -> None:
    tracer = MagicMock()
    manager = MagicMock()

    process_event(_make_session_start_event(), tracer, manager)

    captured = capsys.readouterr()
    output = captured.out.strip()
    parsed = json.loads(output)

    assert parsed["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert len(parsed["hookSpecificOutput"]["additionalContext"]) > 0
    assert parsed["systemMessage"] is None


def test_dedup_under_concurrency() -> None:
    session_id = f"test-dedup-{uuid4()}"
    n_unique = SEEN_EVENTS_MAX
    n_total = 10_000

    events = [
        {
            "hook_event_name": "PreToolUse",
            "session_id": session_id,
            "cwd": "/tmp",
            "transcript_path": "/tmp/transcript.jsonl",
            "tool_use_id": f"tu_{i}",
        }
        for i in range(n_unique)
    ]
    tasks = [events[i % n_unique] for i in range(n_total)]

    tracer = MagicMock(spec=Tracer)

    def invoke(event_data: dict) -> str | None:
        return run_hook(event_data, tracer, False)

    try:
        with ThreadPoolExecutor(max_workers=50) as pool:
            results = list(pool.map(invoke, tasks))

        assert sum(1 for r in results if r is not None) == n_unique
    finally:
        SessionState.delete(session_id)


def test_run_hook_creates_session_state() -> None:
    session_id = f"test-{uuid4()}"
    tracer = MagicMock(spec=Tracer)

    try:
        run_hook(_make_pre_tool_use(session_id, "tu_0"), tracer, False)

        state = SessionState.from_session_id(session_id)
        assert state is not None
    finally:
        SessionState.delete(session_id)


def test_run_hook_accumulates_state_across_events() -> None:
    session_id = f"test-{uuid4()}"
    tracer = MagicMock(spec=Tracer)

    try:
        run_hook(_make_pre_tool_use(session_id, "tu_0"), tracer, False)
        run_hook(_make_pre_tool_use(session_id, "tu_1"), tracer, False)

        state = SessionState.from_session_id(session_id)
        assert state is not None
        assert len(state.pending_tools) == 2
    finally:
        SessionState.delete(session_id)


def test_run_hook_session_end_deletes_state() -> None:
    session_id = f"test-{uuid4()}"
    tracer = MagicMock(spec=Tracer)
    session_end = {
        "hook_event_name": "SessionEnd",
        "session_id": session_id,
        "cwd": "/tmp",
        "transcript_path": "/tmp/transcript.jsonl",
    }

    run_hook(session_end, tracer, False)

    assert SessionState.from_session_id(session_id) is None
