#!/usr/bin/env python3
import base64
import json
import logging
import sys
import urllib.parse
import urllib.request

from opentelemetry.trace import Tracer

from cc_tracer_lib.models import (
    ENV_FILE,
    ClaudeCodeTracingSettings,
    HookEvent,
    SubagentStart,
    SubagentStop,
)
from cc_tracer_lib.spans import setup_tracer
from cc_tracer_lib.state import SessionStateManager


def process_event(event: HookEvent, tracer: Tracer, manager: SessionStateManager) -> None:
    if event.hook_event_name == "PreToolUse":
        manager.handle_tool_selected(event)
    elif event.hook_event_name == "PostToolUse":
        manager.handle_tool_use(tracer, event)
    elif event.hook_event_name == "Notification":
        manager.handle_notification(tracer, event)
    elif event.hook_event_name == "UserPromptSubmit":
        if event.prompt is None:
            raise ValueError("UserPromptSubmit event must have a prompt")
        manager.handle_prompt_submit(event.prompt)
    elif event.hook_event_name == "Stop":
        # Despite the unfortunate name, this is basically the other end of `UserPromptSubmit`.
        manager.handle_stop(tracer, event)
    elif event.hook_event_name == "SubagentStart":
        manager.handle_subagent_start(SubagentStart.from_hook_event(event))
    elif event.hook_event_name == "SubagentStop":
        manager.handle_subagent_stop(tracer, SubagentStop.from_hook_event(event))
    elif event.hook_event_name == "SessionStart":
        print(f'{{"status":"ok","message":"Telemetry active. Trace ID: {manager.get_trace_id()}"}}')
        logging.info("Started new session: %s", event.session_id)
    elif event.hook_event_name == "SessionEnd":
        manager.handle_session_end(tracer, event)
        return
    else:
        logging.info("Unknown event received: %s", event.hook_event_name)

    manager.save(event.session_id)


def main() -> None:
    settings = ClaudeCodeTracingSettings()
    event_data = json.load(sys.stdin)
    event = HookEvent.model_validate(event_data)
    logging.debug("Received event: %s", event.hook_event_name)

    if not settings.endpoint_code or not settings.collector_base_url:
        if event.hook_event_name == "SessionStart":
            # Output to stdout so Claude sees it, and log to file
            print(
                f'{{"status":"info","message":"Tracing disabled. '
                f'Set both CLAUDE_CODE_ENDPOINT_CODE and CLAUDE_CODE_COLLECTOR_BASE_URL in {ENV_FILE} to enable."}}'
            )
            logging.warning(
                "Claude Code tracing disabled "
                "(set CLAUDE_CODE_ENDPOINT_CODE and CLAUDE_CODE_COLLECTOR_BASE_URL in %s to enable)",
                ENV_FILE,
            )

        else:
            logging.debug("(Hook existing, no endpoint config in %s)", ENV_FILE)
        return

    manager = SessionStateManager.from_session_id(event.session_id, settings.notify_sessions)
    tracer = setup_tracer(
        collector_base_url=settings.collector_base_url,
        endpoint_code=settings.endpoint_code,
        model=settings.model,
        harness=settings.harness,
    )
    process_event(event, tracer, manager)
    if event.hook_event_name == "SessionEnd":
        base = settings.collector_base_url
        tracker = settings.endpoint_code
        trace_id_b64 = base64.b64encode(manager.get_trace_id().bytes).decode()
        url = f"{base}/last-runs?tracker={tracker}"
        try:
            api_url = f"{base}/api/leaderboard/last-runs?tracker={tracker}&limit=5"
            with urllib.request.urlopen(api_url, timeout=3) as resp:
                runs = json.loads(resp.read()).get("runs", [])
            for run in runs:
                if run.get("trace_id_b64") == trace_id_b64:
                    encoded_b64 = urllib.parse.quote(trace_id_b64)
                    url = f"{base}/deep-dive/run/{run['run_id']}?tracker={tracker}&traceIdB64={encoded_b64}"
                    break
        except Exception:
            pass
        try:
            with open("/dev/tty", "w") as tty:
                tty.write(f"\nSession trace: {url}\n")
        except OSError:
            pass
    print(f'{{"status":"ok","event":"{event.hook_event_name}"}}')


if __name__ == "__main__":
    logging.basicConfig(filename="ss_claude_trace_hook.log", level=logging.INFO)
    try:
        main()
    except Exception:
        logging.exception("Event processing failed")
