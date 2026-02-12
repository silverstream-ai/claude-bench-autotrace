from dataclasses import dataclass
from datetime import datetime
import logging
from pathlib import Path

from pydantic import ValidationError

from cc_tracer_lib.models import (
    AssistantMessage,
    ChatMessage,
    ContentBlock,
    MessageRole,
    TranscriptEntry,
    TranscriptState,
    ToolParent,
    AgentParent,
    StepParent
)

logger = logging.getLogger(__name__)


def truncate(value: str, max_length: int) -> str:
    if len(value) > max_length:
        return value[: max_length - 15] + "...[truncated]"
    return value


def _load_transcript(path: Path) -> list[TranscriptEntry] | None:
    try:
        text = path.read_text()
    except FileNotFoundError:
        logger.warning(f"Transcript not found: {path}")
        return None
    except PermissionError:
        logger.warning(f"Permission denied: {path}")
        return None
    except UnicodeDecodeError as e:
        logger.warning(f"Invalid UTF-8 encoding at byte {e.start}: {path}")
        return None

    entries_data = []
    for i, line in enumerate(text.splitlines()):
        try:
            data = TranscriptEntry.model_validate_json(line)
            entries_data.append(data)
        except ValidationError as e:
            logger.warning(f"Invalid JSON at line {i + 1}: {e}")
    return entries_data


@dataclass
class _AssistantBlock:
    message: ContentBlock
    timestamp: datetime


def _iter_assistant_blocks(path: Path) -> list[_AssistantBlock] | None:
    entries = _load_transcript(path)
    if entries is None:
        return None

    blocks: list[_AssistantBlock] = []
    for entry in entries:
        if entry.type == "assistant" and isinstance(entry.message, AssistantMessage):
            if entry.timestamp is None:
                # TODO(#3264): This isn't needed if we catch errors at parse time
                logging.warning(
                    "Bad transcript entry %s: timestamp is missing for assistant type",
                    entry.model_dump_json(),
                )
                continue
            blocks.extend(
                [
                    _AssistantBlock(message=c, timestamp=entry.timestamp)
                    for c in entry.message.content
                ]
            )
    return blocks


def extract_think_for_tool(transcript_path: str, tool_use_id: str | None) -> str | None:
    if not tool_use_id:
        return None

    blocks = _iter_assistant_blocks(Path(transcript_path))
    if not blocks:
        return None

    pending_think: str | None = None
    for block in blocks:
        match block.message.type:
            case "thinking":
                pending_think = block.message.thinking
            case "tool_use":
                if block.message.id == tool_use_id:
                    return pending_think
                pending_think = None
    return None


def extract_chat_from_transcript(transcript_path: str) -> list[ChatMessage] | None:
    blocks = _iter_assistant_blocks(Path(transcript_path))
    if not blocks:
        return None

    result = []
    for block in blocks:
        if block.message.type == "text":
            # This is a chat message from assistant
            if block.message.text is None:
                # TODO(#3264): This isn't needed if we catch errors at parse time
                logging.warning(
                    "Bad transcript block %s: text is missing for assistant type",
                    block.message.model_dump_json(),
                )
                continue

            result.append(
                ChatMessage(
                    message=block.message.text,
                    role=MessageRole.ASSISTANT,
                    timestamp=block.timestamp.timestamp(),
                )
            )

    return result

def update_transcript(
    agent_state: TranscriptState,
    transcript_path: Path,
    ) -> None:
    entries = _load_transcript(Path(transcript_path))
    if entries is None:
        return

    # Single pass through entries to cache parent relationships
    logging.info("%d entries in %s", len(entries), transcript_path)
    for entry in entries:
        # Check for progress entry indicating agent spawned by tool
        # It has type = progress, parentToolUseID=<parent tool>, data = {agentId=<child agent id>}
        if entry.type == "progress":
            parent_tool_id = entry.parentToolUseID
            if parent_tool_id is not None and entry.data and isinstance(entry.data, dict):
                agent_id = entry.data.get("agentId")
                if agent_id is not None and agent_id not in agent_state.agent_parents:
                    agent_state.agent_parents[agent_id] = ToolParent(tool_use_id=parent_tool_id)
                    logger.debug(
                        "Cached agent parent: agent %s -> tool %s",
                        agent_id, parent_tool_id
                    )

        # Check for assistant messages to cache tool parent relationships
        # It has agentId = <parent agentid>, message= {content: [... {type: tool_use, id: <child tool_use id>}]}
        elif entry.type == "assistant" and isinstance(entry.message, AssistantMessage):
            logging.info("Assistant found")
            agent_id = entry.agentId
            if agent_id is not None:
                for content in entry.message.content:
                    if content.type == "tool_use" and content.id:
                        logging.info("Tool use found")
                        if content.id not in agent_state.tool_parents:
                            agent_state.tool_parents[content.id] = AgentParent(agent_id=agent_id)
                            logger.debug(
                                "Cached tool parent: tool %s -> agent %s",
                                content.id, agent_id
                            )


def search_tool_parent_in_subagent_transcript(
    agent_id: str,
    subagent_transcript_path: str,
    agent_state: TranscriptState,
    tool_use_id: str
) -> StepParent | None:
    """
    Scan a subagent transcript to cache all tool parent relationships.

    Scans for assistant messages with tool_use blocks. Each tool found
    has this agent as its parent.

    Args:
        agent_id: The subagent's ID
        subagent_transcript_path: Path to the subagent's transcript
        agent_state: TranscriptState for this specific agent
        tool_use_id: The tool use ID we're looking for

    Returns:
        AgentParent if the tool is found in this subagent's transcript, None otherwise
    """
    # Check cache first
    if tool_use_id in agent_state.tool_parents:
        return agent_state.tool_parents[tool_use_id]

    # Update transcript to cache relationships
    update_transcript(agent_state, Path(subagent_transcript_path))

    # Return the requested tool's parent if found
    return agent_state.tool_parents.get(tool_use_id)


def search_tool_parent_in_transcript(transcript_path: str, state: TranscriptState, tool_use_id: str) -> StepParent | None:
    """
    Scan main transcript to cache all parent relationships.

    Progress entries with parentToolUseID and data.agentId reveal that:
    - The agent (data.agentId) is a child of the tool (parentToolUseID)
    - This is cached as: agent_parents[agent_id] = ToolParent(tool_use_id=parentToolUseID)

    Args:
        transcript_path: Path to the main session transcript
        state: TranscriptState to update with cached relationships
        tool_use_id: The tool use ID we're looking for the parent of

    Returns:
        StepParent if found, None otherwise
    """
    logging.info("Searching for tool use: %s in: %s", tool_use_id, transcript_path)
    # Check cache first
    if tool_use_id in state.tool_parents:
        return state.tool_parents[tool_use_id]

    # Update transcript to cache relationships
    update_transcript(state, Path(transcript_path))

    # Return the tool's parent if we have it cached
    return state.tool_parents.get(tool_use_id)

