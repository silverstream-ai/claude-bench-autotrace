#!/usr/bin/env python3
import json

import logging
import sys
from uuid import uuid4

from cc_tracer_lib.models import (
    ENV_FILE,
    ClaudeCodeTracingSettings,
    HookEvent,
    SubagentStart,
    SubagentStop,
    MessageRole,
)
from cc_tracer_lib.spans import setup_tracer
from cc_tracer_lib.state import SessionStateManager
from opentelemetry.trace import Tracer


def process_event(
    event: HookEvent, tracer: Tracer, manager: SessionStateManager
) -> None:
    if event.hook_event_name == "UserPromptSubmit" and event.prompt is None:
        raise ValueError("UserPromptSubmit event must have a prompt")

    episode_was_active = manager.is_episode_active()
    if (
        event.hook_event_name
        in ("UserPromptSubmit", "PreToolUse", "PostToolUse", "Notification")
        and not episode_was_active
    ):
        if event.hook_event_name == "UserPromptSubmit":
            assert event.prompt is not None  # See check above
            prompt = event.prompt
        else:
            prompt = "(resumed session)"
        manager.start_episode(prompt)

    if event.hook_event_name == "UserPromptSubmit":
        assert event.prompt is not None  # See check above
        manager.add_chat_message(event.prompt, MessageRole.USER)
        if episode_was_active:
            manager.update_prompt(event.prompt)
    elif event.hook_event_name == "PreToolUse":
        manager.handle_tool_selected(event)
    elif event.hook_event_name == "PostToolUse":
        manager.handle_tool_use(tracer, event)
    elif event.hook_event_name == "Notification":
        manager.handle_notification(tracer, event)
    elif event.hook_event_name == "Stop":
        manager.handle_stop(tracer, event)
    elif event.hook_event_name == "SubagentStart":
        manager.handle_subagent_start(SubagentStart.from_hook_event(event))
    elif event.hook_event_name == "SubagentStop":
        logging.info("STOP EVENT!! %s", event)
        manager.handle_subagent_stop(tracer, SubagentStop.from_hook_event(event))
    elif event.hook_event_name == "SessionEnd":
        manager.handle_session_end(tracer, event)
        return
    else:
        logging.info("Unknown event received: %s", event.hook_event_name)

    manager.save(event.session_id)


def main() -> None:
    settings = ClaudeCodeTracingSettings()
    event_data = json.load(sys.stdin)
    logging.debug("Received event: %s", json.dumps(event_data, indent=4))
    event = HookEvent.model_validate(event_data)
    logging.debug("Received event: %s", event.hook_event_name)

    if not settings.endpoint_code or not settings.collector_base_url:
        if event.hook_event_name == "SessionStart":
            # Output to stdout so Claude sees it, and log to file
            print(
                f'{{"status":"info","message":"Tracing disabled. Set both CLAUDE_CODE_ENDPOINT_CODE and CLAUDE_CODE_COLLECTOR_BASE_URL in {ENV_FILE} to enable."}}'
            )
            logging.warning(
                "Claude Code tracing disabled (set CLAUDE_CODE_ENDPOINT_CODE and CLAUDE_CODE_COLLECTOR_BASE_URL in %s to enable)",
                ENV_FILE,
            )

        else:
            logging.debug("(Hook existing, no endpoint config in %s)", ENV_FILE)
        return

    manager = SessionStateManager.from_session_id(event.session_id, settings.notify_sessions)
    if event.hook_event_name == "SessionStart":
        manager.save(event.session_id)
        print(
                f'{{"status":"ok","message":"Telemetry active. Trace ID: {manager.get_trace_id()}", "systemMessage": "puzzi un sacco! WELCOME !"}}'
        )
        logging.info("Started new session: %s", event.session_id)
        return

    tracer = setup_tracer(
        collector_base_url=settings.collector_base_url,
        endpoint_code=settings.endpoint_code,
        model=settings.model,
        harness=settings.harness,
    )
    process_event(event, tracer, manager)
    #print(f'{{"status":"ok","event":"{event.hook_event_name}"}}')


if __name__ == "__main__":
    logging.basicConfig(filename="ss_claude_trace_hook.log", level=logging.DEBUG)
    try:
        main()
    except Exception:
        logging.exception("Event processing failed")
