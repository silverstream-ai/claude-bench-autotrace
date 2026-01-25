import json
import logging
import time
from typing import Any, Self
from uuid import uuid4

from opentelemetry.trace import Tracer

from cc_tracer_lib.models import (
    AL2_EXPERIMENT,
    AL2_NAME,
    AL2_TYPE,
    THINK_MAX_LENGTH,
    TYPE_EPISODE,
    TYPE_STEP,
    HookEvent,
    SessionState,
)
from cc_tracer_lib.spans import make_context, send_span
from cc_tracer_lib.transcript import extract_think_for_tool, truncate

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
        return self._state.episode_span_id is not None

    def start_episode(self, prompt: str) -> None:
        if self.is_episode_active():
            logger.warning("Starting new episode while one is already active")

        logger.info("Starting episode, trace id: %s", self._state.trace_id)
        self._state = SessionState(
            trace_id=self._state.trace_id,
            episode_span_id=str(uuid4()),
            episode_start_ns=time.time_ns(),
            prompt_metadata_id=str(uuid4()),
            prompt_received_ns=time.time_ns(),
            prompt_text=prompt,
        )

    def end_episode(self) -> tuple[str, int, int, str | None] | None:
        if self._state.episode_span_id is None:
            return None

        assert self._state.episode_start_ns is not None
        return (
            self._state.episode_span_id,
            self._state.episode_start_ns,
            time.time_ns(),
            self._state.prompt_text,
        )

    def update_prompt(self, prompt: str) -> None:
        self._state = SessionState(
            trace_id=self._state.trace_id,
            episode_span_id=self._state.episode_span_id,
            episode_start_ns=self._state.episode_start_ns,
            prompt_text=prompt,
            prompt_metadata_id=str(uuid4()),
            prompt_received_ns=time.time_ns(),
        )

    def handle_stop(self, tracer: Tracer, event: HookEvent) -> None:
        episode_data = self.end_episode()
        if not episode_data:
            return

        span_id, start_ns, end_ns, prompt = episode_data
        task_name = truncate(prompt, 50).replace("\n", " ") if prompt else "turn"

        attributes: dict[str, Any] = {
            AL2_TYPE: TYPE_EPISODE,
            AL2_NAME: task_name,
            AL2_EXPERIMENT: "claude-code-session",
        }
        if prompt:
            truncated = truncate(prompt, 200)
            attributes["chat_messages"] = json.dumps([{"role": "user", "content": truncated}])

        send_span(
            tracer,
            name="claude_code.turn",
            attributes=attributes,
            start_time_ns=start_ns,
            end_time_ns=end_ns,
            context=make_context(self._state.trace_id),
            explicit_span_id=span_id,
            trace_id=self._state.trace_id,
        )

        self._state = SessionState(trace_id=self._state.trace_id)

    def handle_tool_use(self, tracer: Tracer, event: HookEvent, is_post: bool) -> None:
        tool_use_id = event.tool_use_id or event.tool_name or "unknown"

        if not is_post:
            self._state.pending_tools[tool_use_id] = time.time_ns()
            return

        start_time_ns = self._state.pending_tools.pop(tool_use_id, None) or time.time_ns()
        end_time_ns = time.time_ns()

        attributes: dict[str, Any] = {
            AL2_TYPE: TYPE_STEP,
            AL2_NAME: f"tool.{event.tool_name}",
            AL2_EXPERIMENT: "claude-code-session",
        }

        think = extract_think_for_tool(event.transcript_path, event.tool_use_id)
        attributes["think"] = truncate(think, THINK_MAX_LENGTH) if think else "N/A"

        if event.tool_input:
            agent_output = {
                "actions": [{"name": event.tool_name, "arguments": event.tool_input}],
                "llm_output": {},
            }
            attributes["agent_output"] = json.dumps(agent_output)

        logging.info("Sending span to OTEL collector.")
        send_span(
            tracer,
            name=f"claude_code.tool.{event.tool_name}",
            attributes=attributes,
            start_time_ns=start_time_ns,
            end_time_ns=end_time_ns,
            context=make_context(self._state.trace_id, self._state.episode_span_id),
            trace_id=self._state.trace_id,
        )

    def handle_session_end(self, tracer: Tracer, event: HookEvent) -> None:
        if self.is_episode_active():
            self.handle_stop(tracer, event)
        self.delete(event.session_id)
