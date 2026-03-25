from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

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
