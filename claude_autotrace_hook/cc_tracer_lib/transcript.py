import json
import logging
import pathlib

from pydantic import ValidationError

from cc_tracer_lib.models import AssistantMessage, ContentBlock, TranscriptAdapter

logger = logging.getLogger(__name__)


def truncate(value: str, max_length: int) -> str:
    if len(value) > max_length:
        return value[: max_length - 15] + "...[truncated]"
    return value


def iter_assistant_blocks(path: pathlib.Path) -> list[ContentBlock] | None:
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

    try:
        entries_data = [json.loads(line) for line in text.splitlines()]
    except json.JSONDecodeError as e:
        logger.warning(f"Invalid JSON at line {e.lineno}: {path}")
        return None

    try:
        entries = TranscriptAdapter.validate_python(entries_data)
    except ValidationError as e:
        logger.warning(f"Schema validation failed ({e.error_count()} errors): {path}")
        return None

    blocks = []
    for entry in entries:
        if entry.type == "assistant" and isinstance(entry.message, AssistantMessage):
            blocks.extend(entry.message.content)
    return blocks


def extract_think_for_tool(transcript_path: str, tool_use_id: str | None) -> str | None:
    if not tool_use_id:
        return None

    blocks = iter_assistant_blocks(pathlib.Path(transcript_path))
    if not blocks:
        return None

    pending_think: str | None = None
    for block in blocks:
        match block.type:
            case "thinking":
                pending_think = block.thinking
            case "tool_use":
                if block.id == tool_use_id:
                    return pending_think
                pending_think = None
    return None
