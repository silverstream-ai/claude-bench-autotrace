import json
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

from cc_tracer import process_event, run_hook
from opentelemetry.trace import Tracer
from pytest import CaptureFixture

from cc_tracer_lib.models import HookEvent, SessionState


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
    manager.get_trace_id.return_value = _FAKE_TRACE_ID

    output = process_event(_make_session_start_event(), tracer, manager, _make_settings())
    assert output is not None
    send_message_to_claude(output)

    captured = capsys.readouterr()
    parsed = json.loads(captured.out.strip())

    assert parsed["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert len(parsed["hookSpecificOutput"]["additionalContext"]) > 0
    assert parsed["systemMessage"] is None


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
