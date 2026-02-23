import logging
from pathlib import Path

from pydantic import ValidationError

from cc_tracer_lib.models import (
    AssistantMessage,
    ChatMessage,
    MessageRole,
    TranscriptEntry,
    TranscriptState,
    ToolParent,
    AgentParent,
    StepParent,
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


def extract_think_for_tool(
    transcript_path: Path, tool_use_id: str | None
) -> str | None:
    if not tool_use_id:
        return None

    entries = _load_transcript(transcript_path)
    if not entries:
        return None

    pending_think: str | None = None
    for entry in entries:
        if entry.type != "assistant" or not isinstance(entry.message, AssistantMessage):
            continue
        if entry.timestamp is None:
            # Preserve prior behavior from _iter_assistant_blocks(), which skipped
            # malformed assistant entries (including for think extraction).
            logging.warning(
                "Bad transcript entry %s: timestamp is missing for assistant type",
                entry.model_dump_json(),
            )
            continue

        for content in entry.message.content:
            match content.type:
                case "thinking":
                    pending_think = content.thinking
                case "tool_use":
                    if content.id == tool_use_id:
                        return pending_think
                    pending_think = None

    return None


def update_transcript(
    agent_state: TranscriptState,
    transcript_path: Path,
) -> None:
    entries = _load_transcript(Path(transcript_path))
    if entries is None:
        return

    # Single pass through entries to cache parent relationships and assistant chat messages
    logger.debug("%d entries in %s", len(entries), transcript_path)
    chat_messages: list[ChatMessage] = []
    for entry in entries:
        # Check for progress entry indicating agent spawned by tool
        # It has type = progress, parentToolUseID=<parent tool>, data = {agentId=<child agent id>}
        if entry.type == "progress":
            parent_tool_id = entry.parentToolUseID
            if (
                parent_tool_id is not None
                and entry.data
                and isinstance(entry.data, dict)
            ):
                agent_id = entry.data.get("agentId")
                if agent_id is not None and agent_id not in agent_state.agent_parents:
                    agent_state.agent_parents[agent_id] = ToolParent(
                        tool_use_id=parent_tool_id
                    )
                    logger.debug(
                        "Cached agent parent: agent %s -> tool %s",
                        agent_id,
                        parent_tool_id,
                    )

        # Check for assistant messages to cache tool parent relationships
        # It has agentId = <parent agentid>, message= {content: [... {type: tool_use, id: <child tool_use id>}]}
        elif entry.type == "assistant" and isinstance(entry.message, AssistantMessage):
            agent_id = entry.agentId

            if agent_id is not None:
                for content in entry.message.content:
                    if content.type == "tool_use" and content.id:
                        if content.id not in agent_state.tool_parents:
                            agent_state.tool_parents[content.id] = AgentParent(
                                agent_id=agent_id
                            )
                            logger.debug(
                                "Cached tool parent: tool %s -> agent %s",
                                content.id,
                                agent_id,
                            )

            if entry.timestamp is None:
                # TODO(#3264): This isn't needed if we catch errors at parse time
                logging.warning(
                    "Bad transcript entry %s: timestamp is missing for assistant type",
                    entry.model_dump_json(),
                )
                continue

            for content in entry.message.content:
                if content.type != "text":
                    continue
                if content.text is None:
                    # TODO(#3264): This isn't needed if we catch errors at parse time
                    logging.warning(
                        "Bad transcript block %s: text is missing for assistant type",
                        content.model_dump_json(),
                    )
                    continue
                chat_messages.append(
                    ChatMessage(
                        message=content.text,
                        role=MessageRole.ASSISTANT,
                        timestamp=entry.timestamp.timestamp(),
                    )
                )

    agent_state.chat_messages = chat_messages


def search_tool_parent_in_subagent_transcript(
    subagent_transcript_path: Path, agent_state: TranscriptState, tool_use_id: str
) -> StepParent | None:
    """
    Scan a subagent transcript to cache all tool parent relationships.

    Scans for assistant messages with tool_use blocks. Each tool found
    has this agent as its parent.

    Args:
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


def search_tool_parent_in_transcript(
    transcript_path: str, state: TranscriptState, tool_use_id: str
) -> StepParent | None:
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
    logger.debug("Searching for tool use: %s in: %s", tool_use_id, transcript_path)
    # Check cache first
    if tool_use_id in state.tool_parents:
        return state.tool_parents[tool_use_id]

    # Update transcript to cache relationships
    update_transcript(state, Path(transcript_path))

    # Return the tool's parent if we have it cached
    return state.tool_parents.get(tool_use_id)


def search_agent_parent_in_transcript(
    transcript_path: str, state: TranscriptState, agent_id: str
) -> StepParent | None:
    """
    Scan a transcript searching for the parent of an agent.
    If a scan of the transcript is needed, all found relationships are cached.

    Args:
        transcript_path: Path to the main transcript
        state: TranscriptState to update with cached relationships
        agent_id: The agent ID we're looking for

    Returns:
        StepParent if the agent parent is found, None otherwise
    """
    # Check cache first
    if agent_id in state.agent_parents:
        return state.agent_parents[agent_id]

    # Update transcript to cache relationships
    update_transcript(state, Path(transcript_path))

    # Return the agent's parent if we have it cached
    return state.agent_parents.get(agent_id)


def search_agent_parent_in_subagent_transcript(
    subagent_transcript_path: Path, agent_state: TranscriptState, agent_id: str
) -> StepParent | None:
    """
    Scan a subagent transcript searching for the parent of an agent.
    If a scan of the transcript is needed, all found relationships are cached.

    Args:
        subagent_transcript_path: Path to the subagent's transcript
        agent_state: TranscriptState for this specific subagent
        agent_id: The agent ID we're looking for

    Returns:
        StepParent if the agent is found in this subagent's transcript, None otherwise
    """
    # Check cache first
    if agent_id in agent_state.agent_parents:
        return agent_state.agent_parents[agent_id]

    # Update transcript to cache relationships
    update_transcript(agent_state, Path(subagent_transcript_path))

    # Return the requested agent's parent if found
    return agent_state.agent_parents.get(agent_id)
