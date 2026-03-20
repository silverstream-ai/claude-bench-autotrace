import json
from concurrent.futures import ThreadPoolExecutor
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
