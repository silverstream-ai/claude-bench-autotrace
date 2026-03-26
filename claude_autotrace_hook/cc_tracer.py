#!/usr/bin/env python3
import json
import logging
import sys

from opentelemetry.trace import Tracer

from cc_tracer_lib.claude_output import (
    ClaudeCodeHookOutput,
    build_output_end_message,
    build_output_start_message,
    send_message_to_claude,
)
from cc_tracer_lib.models import (
    HookEvent,
    SubagentStart,
    SubagentStop,
)
from cc_tracer_lib.settings import ENV_FILE, ClaudeCodeTracingSettings
from cc_tracer_lib.spans import setup_tracer
from cc_tracer_lib.state import SessionStateManager


def process_event(
    event: HookEvent,
    tracer: Tracer,
    manager: SessionStateManager,
    settings: ClaudeCodeTracingSettings,
) -> ClaudeCodeHookOutput | None:
    output: ClaudeCodeHookOutput | None = None

    name = event.hook_event_name
    if name == "PreToolUse":
        manager.handle_tool_selected(event)
    elif name == "PostToolUse":
        manager.handle_tool_use(tracer, event)
    elif name == "Notification":
        manager.handle_notification(tracer, event)
    elif name == "UserPromptSubmit":
        if event.prompt is None:
            raise ValueError("UserPromptSubmit event must have a prompt")
        manager.handle_prompt_submit(event.prompt)
    elif name == "Stop":
        # Despite the unfortunate name, this is basically the other end of `UserPromptSubmit`.
        manager.handle_stop(tracer, event)
        output = build_output_end_message(
            settings.collector_base_url,
            settings.endpoint_code,
            manager.get_trace_id(),
        )
    elif name == "SubagentStart":
        manager.handle_subagent_start(SubagentStart.from_hook_event(event))
    elif name == "SubagentStop":
        manager.handle_subagent_stop(tracer, SubagentStop.from_hook_event(event))
    elif name == "SessionStart":
        logging.info("Started new session: %s", event.session_id)
        manager.save(event.session_id)
        output = build_output_start_message(
            settings.collector_base_url,
            settings.endpoint_code,
            manager.get_trace_id(),
        )
    elif name == "SessionEnd":
        manager.handle_session_end(tracer, event)
        return None
    else:
        logging.info("Unknown event received: %s", name)

    manager.save(event.session_id)
    return output


def main() -> None:
    settings = ClaudeCodeTracingSettings()
    event_data = json.load(sys.stdin)
    event = HookEvent.model_validate(event_data)
    logging.debug("Received event: %s", event.hook_event_name)

    if settings.endpoint_code is None or settings.collector_base_url is None:
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
            logging.debug("(Hook exiting, no endpoint config in %s)", ENV_FILE)
        return

    manager = SessionStateManager.from_session_id(event.session_id, settings.notify_sessions)
    tracer = setup_tracer(
        collector_base_url=settings.collector_base_url,
        endpoint_code=settings.endpoint_code,
        model=settings.model,
        harness=settings.harness,
    )
    output = process_event(event, tracer, manager, settings)
    if output is not None:
        send_message_to_claude(output)
    else:
        print(f'{{"status":"ok","event":"{event.hook_event_name}"}}')


if __name__ == "__main__":
    logging.basicConfig(filename="ss_claude_trace_hook.log", level=logging.INFO)
    try:
        main()
    except Exception:
        logging.exception("Event processing failed")
