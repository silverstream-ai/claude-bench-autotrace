import json
from unittest.mock import MagicMock

from pytest import CaptureFixture

from cc_tracer_lib.models import HookEvent

from cc_tracer import process_event


def _make_session_start_event() -> HookEvent:
    return HookEvent(
        hook_event_name="SessionStart",
        session_id="test-session-123",
        cwd="/tmp",
        transcript_path="/tmp/transcript.jsonl",
    )


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


def test_process_event_session_start_no_status_ok_message(capsys: CaptureFixture[str]) -> None:
    tracer = MagicMock()
    manager = MagicMock()

    process_event(_make_session_start_event(), tracer, manager)

    captured = capsys.readouterr()
    assert "Telemetry active" not in captured.out
