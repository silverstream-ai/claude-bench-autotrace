#!/usr/bin/env python3
import json
import logging
import pathlib
import sys
from uuid import UUID

BENCH_AUTOTRACE_CLAUDE_MD = pathlib.Path(__file__).parent.parent / "CLAUDE.md"

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
from cc_tracer_lib.claude_output import ClaudeCodeHookOutput, SessionStartOutput, send_message_to_claude


def process_event(
    event: HookEvent,
    tracer: Tracer,
    manager: SessionStateManager,
    settings: ClaudeCodeTracingSettings,
) -> ClaudeCodeHookOutput | None:
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
        if settings.endpoint_code is not None:
            try:
                tracker_id = UUID(settings.endpoint_code)
                system_message = manager.handle_stop(tracer, event, settings.collector_base_url, tracker_id)
                return ClaudeCodeHookOutput(hook_specific_output=None, system_message=system_message)
            except ValueError:
                logging.warning("CLAUDE_CODE_ENDPOINT_CODE is not a valid UUID: %s", settings.endpoint_code)
        return None
    elif event.hook_event_name == "SubagentStart":
        manager.handle_subagent_start(SubagentStart.from_hook_event(event))
    elif event.hook_event_name == "SubagentStop":
        manager.handle_subagent_stop(tracer, SubagentStop.from_hook_event(event))
    elif event.hook_event_name == "SessionStart":
        logging.info("Started new session: %s", event.session_id)
        manager.save(event.session_id)
        return ClaudeCodeHookOutput(
            hook_specific_output=SessionStartOutput(
                additional_context="This session is being recorded by Silverstream Bench."
                + " You can configure telemetry settings for your current working directory"
                + f" by customizing $CLAUDE_PROJECT_DIR/.env, or globally by customizing {ENV_FILE}. "
                + f"Refer to {BENCH_AUTOTRACE_CLAUDE_MD} for specifics on how"
                + " to configure Silverstream Bench for your use case."
            ),
            system_message="This session is being recorded on Silverstream Bench.",
        )
    elif event.hook_event_name == "SessionEnd":
        manager.handle_session_end(tracer, event)
        return None
    else:
        logging.info("Unknown event received: %s", event.hook_event_name)

    manager.save(event.session_id)
    return None


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
