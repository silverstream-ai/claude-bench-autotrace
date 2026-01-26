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
