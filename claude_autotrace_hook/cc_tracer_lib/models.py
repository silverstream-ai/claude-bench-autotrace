import pathlib
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = pathlib.Path(__file__).parent.parent.parent / ".env"
STATE_DIR = pathlib.Path("/tmp/cc_tracer")

# DO NOT EDIT - Mirrored from apps.leaderboard.backend.collector.span_models
AL2_TYPE = "al2.type"
AL2_NAME = "al2.name"
AL2_EXPERIMENT = "al2.experiment"
AL2_MODEL = "al2.model"
AL2_HARNESS = "al2.harness"
TYPE_EXPERIMENT = "experiment"
TYPE_EPISODE = "episode"
TYPE_STEP = "step"

TOOL_ATTR_MAX_LENGTH = 500
THINK_MAX_LENGTH = 10000

INSTRUMENTATION_NAME = "claude-code-hooks"
INSTRUMENTATION_VERSION = "1.0.0"
TRACE_ENDPOINT_PATH = "/traces/collector/{}/v1/traces"
SERVICE_NAME = "claude-code"


class ContentBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str
    id: str | None = None
    name: str | None = None
    input: dict[str, Any] | None = None
    thinking: str | None = None
    signature: str | None = None
    text: str | None = None


class AssistantMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str
    id: str
    type: str
    role: str
    content: list[ContentBlock]
    stop_reason: str | None = None
    stop_sequence: str | None = None
    usage: dict[str, Any] | None = None


class TranscriptEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str
    data: dict[str, Any] | None = None
    uuid: str | None = None
    parentToolUseID: str | None = None
    timestamp: str | None = None
    cwd: str | None = None
    gitBranch: str | None = None
    sessionId: str | None = None
    slug: str | None = None
    version: str | None = None
    parentUuid: str | None = None
    isSidechain: bool | None = None
    userType: str | None = None
    requestId: str | None = None
    thinkingMetadata: dict[str, Any] | None = None
    todos: list[Any] | None = None
    isSnapshotUpdate: bool | None = None
    messageId: str | None = None
    snapshot: dict[str, Any] | None = None
    message: AssistantMessage | dict[str, Any] | str | None = None
    toolUseResult: dict[str, Any] | str | None = None
    sourceToolAssistantUUID: str | None = None
    toolUseID: str | None = None
    stopReason: str | None = None
    preventedContinuation: bool | None = None
    hookInfos: list[Any] | None = None
    hookErrors: list[Any] | None = None
    hookCount: int | None = None
    durationMs: int | float | None = None
    hasOutput: bool | None = None
    isMeta: bool | None = None
    level: str | int | None = None
    subtype: str | None = None
    summary: str | dict[str, Any] | None = None
    isCompactSummary: bool | None = None
    compactMetadata: dict[str, Any] | None = None
    isVisibleInTranscriptOnly: bool | None = None
    leafUuid: str | None = None
    logicalParentUuid: str | None = None
    operation: str | None = None
    content: str | list[Any] | None = None


TranscriptAdapter = TypeAdapter(list[TranscriptEntry])


class HookEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hook_event_name: str
    session_id: str
    cwd: str
    transcript_path: str
    permission_mode: str = ""
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    tool_response: dict[str, Any] | list[Any] | None = None
    tool_use_id: str | None = None
    prompt: str | None = None
    reason: str | None = None
    message: str | None = None
    stop_hook_active: bool | None = None


class ClaudeCodeTracingSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CLAUDE_CODE_", env_file=ENV_FILE, extra="ignore"
    )

    collector_base_url: str | None = None
    endpoint_code: str | None = None
    model: str = Field(default="claude-code")
    harness: str = Field(default="claude-code-hooks")


class SessionState(BaseModel):
    trace_id: str
    episode_span_id: str | None = None
    episode_start_ns: int | None = None

    prompt_text: str | None = None
    prompt_received_ns: int | None = None
    prompt_metadata_id: str | None = None

    pending_tools: dict[str, int] = {}

    @model_validator(mode="after")
    def validate_episode_consistency(self) -> "SessionState":
        if (self.episode_span_id is not None) != (self.episode_start_ns is not None):
            raise ValueError(
                f"episode_span_id and episode_start_ns must both be None or both be set: "
                f"span_id={self.episode_span_id}, start_ns={self.episode_start_ns}"
            )
        return self

    @classmethod
    def from_session_id(cls, session_id: str) -> "SessionState":
        STATE_DIR.mkdir(exist_ok=True)
        path = STATE_DIR / f"{session_id}.json"
        if path.exists():
            return cls.model_validate_json(path.read_text())
        return cls(trace_id=str(uuid4()))

    def save(self, session_id: str) -> None:
        STATE_DIR.mkdir(exist_ok=True)
        path = STATE_DIR / f"{session_id}.json"
        path.write_text(self.model_dump_json())

    @staticmethod
    def delete(session_id: str) -> None:
        path = STATE_DIR / f"{session_id}.json"
        if path.exists():
            path.unlink()
