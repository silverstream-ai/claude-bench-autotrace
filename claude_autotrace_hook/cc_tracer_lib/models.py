from datetime import datetime
from enum import StrEnum
import logging
import pathlib
from typing import Any, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
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


logger = logging.getLogger(__name__)


class ContentBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: str
    id: str | None = None
    name: str | None = None
    input: dict[str, Any] | None = None
    thinking: str | None = None
    signature: str | None = None
    text: str | None = None


class AssistantMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    model: str
    id: str
    type: str
    role: str
    content: list[ContentBlock]
    stop_reason: str | None = None
    stop_sequence: str | None = None
    usage: dict[str, Any] | None = None


class TranscriptEntry(BaseModel):
    # TODO(#3264): this can be made much better with a discriminated union
    model_config = ConfigDict(extra="ignore")
    type: str
    data: dict[str, Any] | None = None
    uuid: str | None = None
    parentToolUseID: str | None = None
    timestamp: datetime | None = None
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
    notify_sessions: bool = Field(default=True)


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    INFO = "info"
    INFEASIBLE = "infeasible"


class ChatMessage(BaseModel):
    role: MessageRole
    message: str
    timestamp: float


class EpisodeState(BaseModel):
    span_id: UUID
    start_ns: int
    prompt_text: str | None = None
    prompt_received_ns: int | None = None
    prompt_metadata_id: str | None = None


class SessionState(BaseModel):
    trace_id: UUID
    chat_history: list[ChatMessage] = []
    episode: EpisodeState | None = None
    pending_tools: dict[str, int] = {}

    @classmethod
    def from_session_id(cls, session_id: str) -> Self | None:
        STATE_DIR.mkdir(exist_ok=True)
        path = STATE_DIR / f"{session_id}.json"
        if path.exists():
            return cls.model_validate_json(path.read_text())
        return None

    def save(self, session_id: str) -> None:
        STATE_DIR.mkdir(exist_ok=True)
        path = STATE_DIR / f"{session_id}.json"
        path.write_text(self.model_dump_json())

    @staticmethod
    def delete(session_id: str) -> None:
        path = STATE_DIR / f"{session_id}.json"
        if path.exists():
            path.unlink()

    def check_new_assistant_messages(
        self, chat: list[ChatMessage]
    ) -> list[ChatMessage]:
        """
        Filters all new (i.e. previously unknown for this session) messages from the assistant.
        """
        # set of already-known assistant messages
        seen = {
            (m.message, m.timestamp)
            for m in self.chat_history
            if m.role is MessageRole.ASSISTANT
        }

        # de-dupe incoming assistant messages + filter out already-known ones (O(n))
        new: list[ChatMessage] = []
        for m in chat:
            if m.role is not MessageRole.ASSISTANT:
                raise ValueError(
                    "merge_new_assistant_messages called with message role: %s", m.role
                )
            k = (m.message, m.timestamp)
            if k in seen:
                continue
            seen.add(k)
            new.append(m)

        new.sort(key=lambda m: m.timestamp)
        return new

    def add_new_assistant_messages(self, new: list[ChatMessage]) -> None:
        """
        Checks all messages from the assistant into the state.
        """
        logger.debug("Found %d new chat messages, appending them in chat", len(new))

        # merge two sorted lists in O(n+m)
        merged: list[ChatMessage] = []
        old = self.chat_history
        i = 0
        j = 0
        while i < len(old) and j < len(new):
            if old[i].timestamp <= new[j].timestamp:
                merged.append(old[i])
                i += 1
            else:
                merged.append(new[j])
                j += 1
        if i < len(old):
            merged.extend(old[i:])
        if j < len(new):
            merged.extend(new[j:])

        self.chat_history = merged
