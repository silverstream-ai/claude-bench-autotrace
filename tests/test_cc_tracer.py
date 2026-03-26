import json
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

from cc_tracer import process_event
from pytest import CaptureFixture

from cc_tracer_lib.claude_output import send_message_to_claude
from cc_tracer_lib.models import HookEvent
from cc_tracer_lib.settings import ClaudeCodeTracingSettings

_FAKE_TRACKER_ID = UUID("ffb4acbe-19a1-4d0b-9a40-3cafb29ea895")
_FAKE_TRACE_ID = UUID("12345678-1234-5678-1234-567812345678")


def _make_session_start_event() -> HookEvent:
    return HookEvent(
        hook_event_name="SessionStart",
        session_id="test-session-123",
        cwd="/tmp",
        transcript_path="/tmp/transcript.jsonl",
    )


def _make_settings(**kwargs: Any) -> ClaudeCodeTracingSettings:
    return ClaudeCodeTracingSettings(
        collector_base_url="https://bench.example.com",
        endpoint_code=str(_FAKE_TRACKER_ID),
        **kwargs,
    )


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
    assert "bench.example.com" in parsed["systemMessage"]
