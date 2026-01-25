#!/usr/bin/env python3
import json
import logging
import sys
from uuid import uuid4

from cc_tracer_lib.models import ENV_FILE, ClaudeCodeTracingSettings, HookEvent, SessionState
from cc_tracer_lib.spans import setup_tracer
from cc_tracer_lib.state import SessionStateManager
from opentelemetry.trace import Tracer


def process_event(event: HookEvent, tracer: Tracer, manager: SessionStateManager) -> None:
    if event.hook_event_name == "UserPromptSubmit" and event.prompt is None:
        raise ValueError("UserPromptSubmit event must have a prompt")

    episode_was_inactive = not manager.is_episode_active()
    if event.hook_event_name in ("UserPromptSubmit", "PreToolUse", "PostToolUse") and episode_was_inactive:
        if event.hook_event_name == "UserPromptSubmit":
            assert event.prompt is not None  # See check above
            prompt = event.prompt
        else:
            prompt = "(resumed session)"
        manager.start_episode(prompt)

    if event.hook_event_name == "UserPromptSubmit":
        if not episode_was_inactive:
            assert event.prompt
            manager.update_prompt(event.prompt)
    elif event.hook_event_name == "PreToolUse":
        manager.handle_tool_use(tracer, event, is_post=False)
    elif event.hook_event_name == "PostToolUse":
        manager.handle_tool_use(tracer, event, is_post=True)
    elif event.hook_event_name == "Stop":
        manager.handle_stop(tracer, event)
    elif event.hook_event_name == "SessionEnd":
        manager.handle_session_end(tracer, event)
        return

    manager.save(event.session_id)


def main() -> None:
    settings = ClaudeCodeTracingSettings()
    event_data = json.load(sys.stdin)
    event = HookEvent.model_validate(event_data)
    logging.debug("Received event: %s", event.hook_event_name)

    if not settings.endpoint_code:
        if event.hook_event_name == "SessionStart":
            # Output to stdout so Claude sees it, and log to file
            print(f'{{"status":"info","message":"Tracing disabled. Set CLAUDE_CODE_ENDPOINT_CODE in {ENV_FILE} to enable."}}')
            logging.warning("Claude Code tracing disabled (set CLAUDE_CODE_ENDPOINT_CODE in %s to enable)", ENV_FILE)
        else:
            logging.debug("(Hook existing, no endpoint code in %s)", ENV_FILE)
        return

    if event.hook_event_name == "SessionStart":
        state = SessionState(trace_id=str(uuid4()))
        state.save(event.session_id)
        print(f'{{"status":"ok","message":"Telemetry active. Trace ID: {state.trace_id}"}}')
        logging.info("Started new session: %s", event.session_id)
        return

    tracer = setup_tracer(settings)
    manager = SessionStateManager.from_session_id(event.session_id)
    process_event(event, tracer, manager)
    print(f'{{"status":"ok","event":"{event.hook_event_name}"}}')


if __name__ == "__main__":
    logging.basicConfig(filename="ss_claude_trace_hook.log", level=logging.INFO)
    main()
