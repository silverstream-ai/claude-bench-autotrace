from datetime import datetime
import json
import logging
import time
from typing import Any, Self
from uuid import uuid4

from opentelemetry.trace import Tracer
from pydantic import TypeAdapter

from cc_tracer_lib.models import (
    AL2_EXPERIMENT,
    AL2_NAME,
    AL2_TYPE,
    THINK_MAX_LENGTH,
    TYPE_EPISODE,
    TYPE_STEP,
    ChatMessage,
    EpisodeState,
    HookEvent,
    MessageRole,
    SessionState,
)
from cc_tracer_lib.spans import make_context, send_span
from cc_tracer_lib.transcript import (
    extract_chat_from_transcript,
    extract_think_for_tool,
    truncate,
)

logger = logging.getLogger(__name__)


class SessionStateManager:
    def __init__(self, state: SessionState):
        self._state = state

    @classmethod
    def from_session_id(cls, session_id: str) -> Self:
        state = SessionState.from_session_id(session_id)
        return cls(state)

    def save(self, session_id: str) -> None:
        self._state.save(session_id)

    def delete(self, session_id: str) -> None:
        SessionState.delete(session_id)

    def is_episode_active(self) -> bool:
        return self._state.episode is not None

    def start_episode(self, prompt: str) -> None:
        if self.is_episode_active():
            logger.warning("Starting new episode while one is already active")

        logger.info("Starting episode, trace id: %s", self._state.trace_id)
        self._state.episode = EpisodeState(
            span_id=uuid4(),
            start_ns=time.time_ns(),
            prompt_metadata_id=str(uuid4()),
            prompt_received_ns=time.time_ns(),
            prompt_text=prompt,
        )

    def end_episode(self) -> EpisodeState | None:
        if self._state.episode is None:
            return None
        result = self._state.episode
        self._state.episode = None
        return result

    def add_chat_message(self, chat_msg: str, role: MessageRole) -> None:
        if self._state.episode is None:
            logger.warning("Updating prompt without active episode")
            return
        self._state.chat_history.append(
            ChatMessage(
                message=chat_msg,
                role=role,
                timestamp=datetime.now().timestamp(),
            )
        )

    def update_prompt(self, prompt: str) -> None:
        if self._state.episode is None:
            logger.warning("Updating prompt without active episode")
            return
        self._state.episode.prompt_text = prompt
        self._state.episode.prompt_metadata_id = str(uuid4())
        self._state.episode.prompt_received_ns = time.time_ns()

    def _check_transcript_for_new_chats(
        self, tracer: Tracer, transcript_path: str
    ) -> None:
        # Parse transcript for new chat messages from the assistant, and sends spans accordingly.
        # This solution is horrible, but as of today there's no way for a hook to get data regarding assistant
        # responses/messages :(
        transcript_chat = extract_chat_from_transcript(transcript_path)
        if transcript_chat is None:
            logger.warning("Failed to extract chat from transcript")
            return

        logger.debug(
            "Extracted %d chat messages from transcript.", len(transcript_chat)
        )
        new = self._state.check_new_assistant_messages(transcript_chat)
        episode = self._state.episode
        if episode is not None and len(new) > 0:
            logger.info(
                "Found %d new chat messages in transcript, creating spans for those",
                len(new),
            )
            for n in new:
                attributes: dict[str, Any] = {
                    AL2_TYPE: TYPE_STEP,
                    AL2_NAME: "chat",
                    AL2_EXPERIMENT: "claude-code-session",
                    "agent_output": json.dumps(
                        {
                            "actions": [{"name": "Chat", "arguments": n.model_dump()}],
                            "llm_output": {},
                        }
                    ),
                }
                attributes["chat_messages_json"] = (
                    TypeAdapter(list[ChatMessage])
                    .dump_json(self._state.chat_history)
                    .decode("utf-8")
                )

                send_span(
                    tracer,
                    name="claude_code.chat",
                    attributes=attributes,
                    start_time_ns=time.time_ns() - 10,
                    end_time_ns=time.time_ns(),
                    context=make_context(self._state.trace_id, episode.span_id),
                    trace_id=self._state.trace_id,
                )
        self._state.add_new_assistant_messages(new)

    def handle_notification(self, tracer: Tracer, event: HookEvent) -> None:
        if self._state.episode is None:
            logger.warning("Notification received without an active episode")
            return

        self._check_transcript_for_new_chats(tracer, event.transcript_path)

    def handle_stop(self, tracer: Tracer, event: HookEvent) -> None:
        self._check_transcript_for_new_chats(tracer, event.transcript_path)

        episode_data = self.end_episode()
        if episode_data is None:
            return

        task_name = (
            truncate(episode_data.prompt_text, 50).replace("\n", " ")
            if episode_data.prompt_text is not None
            else "turn"
        )

        attributes: dict[str, Any] = {
            AL2_TYPE: TYPE_EPISODE,
            AL2_NAME: task_name,
            AL2_EXPERIMENT: "claude-code-session",
        }
        attributes["chat_messages_json"] = (
            TypeAdapter(list[ChatMessage])
            .dump_json(self._state.chat_history)
            .decode("utf-8")
        )

        send_span(
            tracer,
            name="claude_code.turn",
            attributes=attributes,
            start_time_ns=episode_data.start_ns,
            end_time_ns=time.time_ns(),
            context=make_context(self._state.trace_id),
            trace_id=self._state.trace_id,
            explicit_span_id=episode_data.span_id,
        )

        self._state.episode = None

    def handle_tool_selected(self, event: HookEvent) -> None:
        if event.tool_use_id is not None:
            tool_use_id = event.tool_use_id
        elif event.tool_name is not None:
            tool_use_id = event.tool_name
        else:
            tool_use_id = "unknown"

        self._state.pending_tools[tool_use_id] = time.time_ns()

    def handle_tool_use(self, tracer: Tracer, event: HookEvent) -> None:
        tool_use_id = event.tool_use_id or event.tool_name or "unknown"

        start_time_ns = (
            self._state.pending_tools.pop(tool_use_id, None) or time.time_ns()
        )
        end_time_ns = time.time_ns()

        attributes: dict[str, Any] = {
            AL2_TYPE: TYPE_STEP,
            AL2_NAME: f"tool.{event.tool_name}",
            AL2_EXPERIMENT: "claude-code-session",
        }

        attributes["chat_messages_json"] = (
            TypeAdapter(list[ChatMessage])
            .dump_json(self._state.chat_history)
            .decode("utf-8")
        )
        think = extract_think_for_tool(event.transcript_path, event.tool_use_id)
        attributes["think"] = truncate(think, THINK_MAX_LENGTH) if think else "N/A"

        if event.tool_input:
            agent_output = {
                "actions": [{"name": event.tool_name, "arguments": event.tool_input}],
                "llm_output": {},
            }
            attributes["agent_output"] = json.dumps(agent_output)

        logging.info("Sending span to OTEL collector.")
        episode_span_id = (
            self._state.episode.span_id if self._state.episode is not None else None
        )
        send_span(
            tracer,
            name=f"claude_code.tool.{event.tool_name}",
            attributes=attributes,
            start_time_ns=start_time_ns,
            end_time_ns=end_time_ns,
            context=make_context(self._state.trace_id, episode_span_id),
            trace_id=self._state.trace_id,
        )

    def handle_session_end(self, tracer: Tracer, event: HookEvent) -> None:
        if self.is_episode_active():
            self.handle_stop(tracer, event)
        self.delete(event.session_id)
