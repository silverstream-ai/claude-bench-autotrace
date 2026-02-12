from datetime import datetime
from pathlib import Path
from enum import StrEnum
import logging
import pathlib
from typing import Any, Self, Literal, Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
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
    agentId: str | None = None

class CacheCreation(BaseModel):
    """Nested model for cache_creation in usage statistics."""
    model_config = ConfigDict(extra="ignore")
    ephemeral_5m_input_tokens: int | None = None
    ephemeral_1h_input_tokens: int | None = None


class Usage(BaseModel):
    """Model for API usage statistics from Task/agent responses."""
    model_config = ConfigDict(extra="ignore")
    input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    cache_creation: CacheCreation | None = None
    output_tokens: int | None = None
    service_tier: str | None = None
    inference_geo: str | None = None


class ToolResponseContentBlock(BaseModel):
    """Content block within Task/agent tool responses."""
    model_config = ConfigDict(extra="ignore")
    type: str
    text: str | None = None
    # Allow other fields that might appear in content blocks
    id: str | None = None
    name: str | None = None
    input: dict[str, Any] | None = None


class ToolResponse(BaseModel):
    """
    Flexible model for tool responses from Claude Code hooks.

    Different tools return different response structures:
    - Bash: stdout, stderr, interrupted, isImage
    - Task/agents: status, prompt, agentId, content, totalDurationMs, totalTokens, totalToolUseCount, usage
    - Other tools may have their own structures

    All fields are optional to accommodate the variety of tool response types.
    """
    model_config = ConfigDict(extra="ignore")

    # Bash tool response fields
    stdout: str | None = None
    stderr: str | None = None
    interrupted: bool | None = None
    isImage: bool | None = None

    # Task/agent response fields
    status: str | None = None
    prompt: str | None = None
    agentId: str | None = None
    content: list[ToolResponseContentBlock] | None = None
    totalDurationMs: int | float | None = None
    totalTokens: int | None = None
    totalToolUseCount: int | None = None
    usage: Usage | None = None

class HookEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hook_event_name: str
    session_id: str
    cwd: str
    transcript_path: str
    permission_mode: str = ""
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    tool_response: ToolResponse | None = None
    tool_use_id: str | None = None
    prompt: str | None = None
    reason: str | None = None
    message: str | None = None
    stop_hook_active: bool | None = None
    # Subagent-related fields
    agent_id: str | None = None
    agent_type: str | None = None
    agent_transcript_path: str | None = None


class SubagentStart(BaseModel, extra="ignore"):
    """
    Parsed SubagentStart event with only relevant fields.
    """
    session_id: str
    transcript_path: str
    cwd: str
    agent_id: str = Field(min_length=1)
    agent_type: str

    @classmethod
    def from_hook_event(cls, event: HookEvent) -> Self:
        """
        Parse a SubagentStart event from a HookEvent.

        Raises:
            ValueError: If the event is not a SubagentStart event or missing required fields.
        """
        if event.hook_event_name != "SubagentStart":
            raise ValueError(
                f"Expected SubagentStart event, got {event.hook_event_name}"
            )

        if event.agent_id is None or event.agent_type is None:
            raise ValueError(
                "SubagentStart event missing required fields: agent_id and/or agent_type"
            )

        return cls(
            session_id=event.session_id,
            transcript_path=event.transcript_path,
            cwd=event.cwd,
            agent_id=event.agent_id,
            agent_type=event.agent_type,
        )


class SubagentStop(BaseModel):
    """
    Parsed SubagentStop event with only relevant fields.
    """
    model_config = ConfigDict(extra="ignore")

    session_id: str
    transcript_path: str
    cwd: str
    agent_id: str = Field(min_length=1)
    agent_transcript_path: str
    stop_hook_active: bool

    @classmethod
    def from_hook_event(cls, event: HookEvent) -> Self:
        """
        Parse a SubagentStop event from a HookEvent.

        Raises:
            ValueError: If the event is not a SubagentStop event or missing required fields.
        """
        if event.hook_event_name != "SubagentStop":
            raise ValueError(
                f"Expected SubagentStop event, got {event.hook_event_name}"
            )

        if event.agent_id is None:
            raise ValueError(
                "SubagentStop event missing required fields: agent_id and/or agent_type"
            )

        if event.agent_transcript_path is None:
            raise ValueError(
                "SubagentStop event missing required field: agent_transcript_path"
            )

        if event.stop_hook_active is None:
            raise ValueError(
                "SubagentStop event missing required field: stop_hook_active"
            )

        return cls(
            session_id=event.session_id,
            transcript_path=event.transcript_path,
            cwd=event.cwd,
            agent_id=event.agent_id,
            agent_transcript_path=event.agent_transcript_path,
            stop_hook_active=event.stop_hook_active,
        )


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


class AgentParent(BaseModel):
    """
    The parent of this step is an agent with the given ID
    """
    type: Literal['agent'] = 'agent'
    agent_id: str


class ToolParent(BaseModel):
    """
    The parent of this step is a tool with the given ID
    """
    type: Literal['tool'] = 'tool'
    tool_use_id: str

StepParent = Annotated[
    AgentParent | ToolParent,
    Field(discriminator="type"),
]

class TranscriptState(BaseModel):
    # Which step is the parent of which subAgent
    agent_parents: dict[str, StepParent]
    # Which step is the parent of which toolUse
    tool_parents: dict[str, StepParent]

class SubagentState(BaseModel):
    agent_id: str
    start_time_ns: int
    agent_type: str
    span_id: UUID
    parent_span_id: UUID | None
    transcript_state: TranscriptState

    def get_transcript_path(self, main_transcript_path: str) -> str:
        """Get the path to this subagent's transcript file."""
        p = Path(main_transcript_path)
        transcript_dir = p.parent / p.stem / "subagents"
        return str(transcript_dir / f"agent-{self.agent_id}.jsonl")


class SessionState(BaseModel):
    trace_id: UUID
    session_start_time: datetime
    chat_history: list[ChatMessage] = []
    episode: EpisodeState | None = None
    pending_tools_start_time: dict[str, int] = {}
    subagents: dict[str, SubagentState] = {}
    # https://github.com/anthropics/claude-code/issues/16424
    # There's currently no way to correlate agent ID with tool use.
    # When pre-tool or post-tool uses are 
    transcript_state: TranscriptState

    @classmethod
    def from_session_id(cls, session_id: str) -> Self | None:
        STATE_DIR.mkdir(exist_ok=True)
        path = STATE_DIR / f"{session_id}.json"
        if path.exists():
            try:
                return cls.model_validate_json(path.read_text())
            except ValidationError as e:
                logger.warning("Session state is corrupted, dropping it: %s.", e)
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
