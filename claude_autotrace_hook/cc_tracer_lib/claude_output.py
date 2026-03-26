import contextlib
import logging
from pathlib import Path
import tempfile
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from cc_tracer_lib.models import BENCH_AUTOTRACE_CLAUDE_MD
from cc_tracer_lib.settings import ENV_FILE
from cc_tracer_lib.url_generator import build_deep_dive_url

"""
Claude Code hooks can send additional context to the agent by printing structured output to stdout.

See https://code.claude.com/docs/en/hooks#json-output for the supported schemas.
"""


class SessionStartOutput(BaseModel):
    """
    Use this model to send a message to Claude on Session Start.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    hook_event_name: Literal["SessionStart"] = Field(default="SessionStart", alias="hookEventName")
    additional_context: str = Field(alias="additionalContext")


HookSpecificOutput = Annotated[SessionStartOutput, Field(discriminator="hook_event_name")]


class ClaudeCodeHookOutput(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    hook_specific_output: HookSpecificOutput | None = Field(alias="hookSpecificOutput")
    system_message: str | None = Field(alias="systemMessage")


def send_message_to_claude(message: ClaudeCodeHookOutput) -> None:
    print(message.model_dump_json(by_alias=True, exclude_none=True))


def build_output_start_message(
    collector_base_url: str | None,
    endpoint_code: str | None,
    trace_id: UUID,
) -> ClaudeCodeHookOutput | None:
    if collector_base_url is None or endpoint_code is None:
        return None
    try:
        tracker_id = UUID(endpoint_code)
    except ValueError:
        logging.warning("CLAUDE_CODE_ENDPOINT_CODE is not a valid UUID: %s", endpoint_code)
        return None

    deep_dive_url = build_deep_dive_url(collector_base_url, tracker_id, trace_id)
    with contextlib.suppress(OSError):
        Path(tempfile.gettempdir(), "bench_deep_dive_url").write_text(deep_dive_url)

    return ClaudeCodeHookOutput(
        hook_specific_output=SessionStartOutput(
            additional_context="This session is being recorded by Silverstream Bench."
            + " You can configure telemetry settings for your current working directory"
            + f" by customizing $CLAUDE_PROJECT_DIR/.env, or globally by customizing {ENV_FILE}. "
            + f"Refer to {BENCH_AUTOTRACE_CLAUDE_MD} for specifics on how"
            + " to configure Silverstream Bench for your use case."
        ),
        system_message=None,
    )
