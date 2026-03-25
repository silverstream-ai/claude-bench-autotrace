from datetime import UTC, datetime
import json
import logging
from pathlib import Path
import time
from typing import Any, Self
from uuid import UUID, uuid4

from opentelemetry.trace import Tracer
from pydantic import TypeAdapter


from cc_tracer_lib.deep_dive import build_deep_dive_url
from cc_tracer_lib.models import (
    AL2_EXPERIMENT,
    AL2_NAME,
    AL2_TYPE,
    THINK_MAX_LENGTH,
    TYPE_EPISODE,
    TYPE_STEP,
    TYPE_TRACE,
    ChatMessage,
    EpisodeState,
    HookEvent,
    MessageRole,
    PromptState,
    SessionState,
    StepParent,
    SubagentStart,
    SubagentState,
    SubagentStop,
    ToolState,
    TranscriptState,
)
from cc_tracer_lib.spans import make_context, send_span
from cc_tracer_lib.transcript import (
    extract_think_for_tool,
    search_agent_parent_in_subagent_transcript,
    search_agent_parent_in_transcript,
    search_tool_parent_in_subagent_transcript,
    search_tool_parent_in_transcript,
    truncate,
    update_transcript,
)
from notifications import send_start_notification

logger = logging.getLogger(__name__)


class SessionStateManager:
    def __init__(self, state: SessionState):
        self._state = state

    @classmethod
    def start_session(cls, notify: bool) -> Self:
        state = SessionState(
            trace_id=uuid4(),
            session_start_time=datetime.now(tz=UTC),
            transcript_state=TranscriptState(agent_parents={}, tool_parents={}, chat_messages=[]),
            chat_history=[],
            queued_chat_history=[],
            episode=None,
            start_time_ns=time.time_ns(),
            prompt=None,
            pending_tools={},
            subagents={},
            session_span_id=uuid4(),
        )
        if notify:
            send_start_notification()
        return cls(state)

    @classmethod
    def from_session_id(cls, session_id: str, notify_new_session: bool) -> Self:
        state = SessionState.from_session_id(session_id)
        if state is None:
            return cls.start_session(notify_new_session)
        return cls(state)

    def save(self, session_id: str) -> None:
        self._state.save(session_id)

    def delete(self, session_id: str) -> None:
        SessionState.delete(session_id)

    def ensure_episode_started(self) -> None:
        if self._state.episode is not None:
            return

        self._state.episode = EpisodeState(
            span_id=uuid4(),
            start_ns=time.time_ns(),
            prompt=None,
        )
        logger.info("Starting episode, trace id: %s, span id: %s", self._state.trace_id, self._state.episode.span_id)

    def update_episode_prompt(self, prompt: str) -> None:
        if not self.has_prompt():
            self.update_prompt(prompt)
        if self._state.episode is None:
            logger.warning("[BUG] update_episode_prompt() called without an active episode")
            return
        self._state.episode.prompt = PromptState(
            text=prompt,
            metadata_id=str(uuid4()),
            received_ns=time.time_ns(),
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

    def get_trace_id(self) -> UUID:
        return self._state.trace_id

    def has_prompt(self) -> bool:
        return self._state.prompt is not None

    def update_prompt(self, prompt: str) -> None:
        self._state.prompt = PromptState(
            text=prompt,
            metadata_id=str(uuid4()),
            received_ns=time.time_ns(),
        )

    def _send_chat_span(
        self,
        tracer: Tracer,
        chat_message: ChatMessage,
        chat_history: list[ChatMessage],
        parent_span_id: UUID,
    ) -> None:
        attributes: dict[str, Any] = {
            AL2_TYPE: TYPE_STEP,
            AL2_NAME: "chat",
            AL2_EXPERIMENT: "claude-code-session",
            "agent_output": json.dumps(
                {
                    "actions": [{"name": "Chat", "arguments": chat_message.model_dump()}],
                    "llm_output": {},
                }
            ),
        }
        attributes["chat_messages_json"] = TypeAdapter(list[ChatMessage]).dump_json(chat_history).decode("utf-8")
        timestamp_ns = int(chat_message.timestamp * 1.0e09)

        send_span(
            tracer,
            name="claude_code.chat",
            attributes=attributes,
            start_time_ns=timestamp_ns,
            end_time_ns=timestamp_ns + 1,
            context=make_context(self._state.trace_id, parent_span_id),
            trace_id=self._state.trace_id,
        )

    def _insert_chat_message_sorted(self, chat_history: list[ChatMessage], chat_message: ChatMessage) -> None:
        i = 0
        while i < len(chat_history) and chat_history[i].timestamp <= chat_message.timestamp:
            i += 1
        chat_history.insert(i, chat_message)

    def _check_transcript_for_new_chats(
        self,
        tracer: Tracer,
        transcript_state: TranscriptState,
        chat_history: list[ChatMessage],
        parent_span_id: UUID,
        allowed_roles: set[MessageRole],
    ) -> None:
        transcript_chat = transcript_state.chat_messages
        logger.debug("Extracted %d chat messages from transcript.", len(transcript_chat))

        seen = {(m.message, m.timestamp) for m in chat_history if m.role in allowed_roles}
        new_chat: list[ChatMessage] = []
        for m in transcript_chat:
            if m.role not in allowed_roles:
                continue
            k = (m.message, m.timestamp)
            if k in seen:
                continue
            seen.add(k)
            new_chat.append(m)
        new_chat.sort(key=lambda m: m.timestamp)

        if len(new_chat) > 0:
            new_chat_spans = [m for m in new_chat if m.role is MessageRole.ASSISTANT]
            logger.debug(
                "Found %d new chat messages in transcript, creating spans for those",
                len(new_chat_spans),
            )
            for n in new_chat:
                if n.role is MessageRole.ASSISTANT:
                    self._send_chat_span(
                        tracer,
                        n,
                        chat_history,
                        parent_span_id,
                    )
                self._insert_chat_message_sorted(chat_history, n)

    def _send_interrupt_span(
        self,
        tracer: Tracer,
        chat_message: ChatMessage,
        parent_span_id: UUID,
    ) -> None:
        attributes: dict[str, Any] = {
            AL2_TYPE: TYPE_STEP,
            AL2_NAME: "interrupt",
            AL2_EXPERIMENT: "claude-code-session",
            "prompt": chat_message.message,
        }
        timestamp_ns = int(chat_message.timestamp * 1.0e09)
        send_span(
            tracer,
            name="claude_code.interrupt",
            attributes=attributes,
            start_time_ns=timestamp_ns,
            end_time_ns=timestamp_ns + 1,
            context=make_context(self._state.trace_id, parent_span_id),
            trace_id=self._state.trace_id,
        )

    def _check_transcript_for_new_queued(
        self,
        tracer: Tracer,
        transcript_state: TranscriptState,
        queued_chat_history: list[ChatMessage],
        current_episode: EpisodeState,
    ) -> None:
        seen = {(m.message, m.timestamp) for m in queued_chat_history}
        new_queued: list[ChatMessage] = []
        for m in transcript_state.queued_messages:
            k = (m.message, m.timestamp)
            if k in seen:
                continue
            seen.add(k)
            new_queued.append(m)
        new_queued.sort(key=lambda m: m.timestamp)
        for m in new_queued:
            self._send_interrupt_span(tracer, m, current_episode.span_id)
            if current_episode is not None:
                current_episode.queued_messages.append(m)
            queued_chat_history.append(m)

    def handle_notification(self, tracer: Tracer, event: HookEvent) -> None:
        if self._state.episode is None:
            logger.warning("Notification received without an active episode")
            return

        update_transcript(self._state.transcript_state, Path(event.transcript_path))
        self._check_transcript_for_new_chats(
            tracer,
            self._state.transcript_state,
            self._state.chat_history,
            self._state.episode.span_id,
            {MessageRole.ASSISTANT},
        )
        self._check_transcript_for_new_queued(
            tracer,
            self._state.transcript_state,
            self._state.queued_chat_history,
            self._state.episode,
        )

    def handle_prompt_submit(self, prompt: str) -> None:
        self.ensure_episode_started()
        self.update_episode_prompt(prompt)
        self.add_chat_message(prompt, MessageRole.USER)

    def handle_stop(
        self,
        tracer: Tracer,
        event: HookEvent,
        collector_base_url: str | None = None,
        tracker_id: UUID | None = None,
    ) -> str | None:
        update_transcript(self._state.transcript_state, Path(event.transcript_path))
        parent_span_id = self._state.episode.span_id if self._state.episode is not None else self._state.session_span_id
        self._check_transcript_for_new_chats(
            tracer,
            self._state.transcript_state,
            self._state.chat_history,
            parent_span_id,
            {MessageRole.ASSISTANT},
        )
        if self._state.episode is not None:
            self._check_transcript_for_new_queued(
                tracer,
                self._state.transcript_state,
                self._state.queued_chat_history,
                self._state.episode,
            )

        episode_data = self.end_episode()
        system_message = None
        if collector_base_url is not None and tracker_id is not None:
            deep_dive_url = build_deep_dive_url(collector_base_url, tracker_id, self._state.trace_id)
            system_message = f"Review your session on bench: \n{deep_dive_url}"

        if episode_data is None:
            return system_message

        task_name = (
            truncate(episode_data.prompt.text, 50).replace("\n", " ") if episode_data.prompt is not None else "turn"
        )

        attributes: dict[str, Any] = {
            AL2_TYPE: TYPE_EPISODE,
            AL2_NAME: task_name,
            AL2_EXPERIMENT: "claude-code-session",
        }
        attributes["prompt"] = episode_data.prompt.text if episode_data.prompt is not None else None
        attributes["chat_messages_json"] = (
            TypeAdapter(list[ChatMessage]).dump_json(self._state.chat_history).decode("utf-8")
        )
        attributes["interrupts_json"] = (
            TypeAdapter(list[str])
            .dump_json([m.message for m in sorted(episode_data.queued_messages, key=lambda x: x.timestamp)])
            .decode("utf-8")
        )

        send_span(
            tracer,
            name="claude_code.turn",
            attributes=attributes,
            start_time_ns=episode_data.start_ns,
            end_time_ns=time.time_ns(),
            context=make_context(self._state.trace_id, self._state.session_span_id),
            trace_id=self._state.trace_id,
            explicit_span_id=episode_data.span_id,
        )

        self._state.episode = None
        return system_message

    def handle_subagent_start(self, event: SubagentStart) -> None:
        self.ensure_episode_started()

        if event.agent_id in self._state.subagents:
            logger.warning("Ignoring subagent start: agent `%s` is already known.", event.agent_id)
            return

        self._state.subagents[event.agent_id] = SubagentState(
            agent_id=event.agent_id,
            span_id=uuid4(),
            agent_type=event.agent_type,
            start_time_ns=time.time_ns(),
            transcript_state=TranscriptState(agent_parents={}, tool_parents={}, chat_messages=[]),
            chat_history=[],
        )

    def _get_parent_span_id_from_step_parent(self, item_id: str, step_parent: StepParent) -> UUID | None:
        if step_parent.type == "agent":
            # This tool's parent is an agent
            agent_id = step_parent.agent_id
            subagent_state = self._state.subagents.get(agent_id)
            if subagent_state is None:
                logger.debug("Parent of `%s` is unknown agent %s", item_id, agent_id)
                return None
            parent_span = subagent_state.span_id
            logger.debug("Parent of `%s` is agent %s (span: %s)", item_id, agent_id, parent_span)
            return parent_span

        parent_tool_state = self._state.pending_tools.get(step_parent.tool_use_id)
        if parent_tool_state is None:
            logger.debug("Parent of `%s` is unknown tool %s", item_id, step_parent.tool_use_id)
            return None
        parent_span = parent_tool_state.span_id
        logger.debug(
            "Parent of `%s` is tool %s (span: %s)",
            item_id,
            step_parent.tool_use_id,
            parent_span,
        )
        return parent_span

    def handle_subagent_stop(self, tracer: Tracer, event: SubagentStop) -> None:
        try:
            agent = self._state.subagents.pop(event.agent_id)
        except KeyError:
            logger.warning("Ignoring subagent stop: agent `%s` is not known.", event.agent_id)
            return

        update_transcript(agent.transcript_state, Path(event.agent_transcript_path))
        self._check_transcript_for_new_chats(
            tracer,
            agent.transcript_state,
            agent.chat_history,
            agent.span_id,
            {MessageRole.USER, MessageRole.ASSISTANT},
        )
        first_user_chat = next(
            (m for m in agent.chat_history if m.role is MessageRole.USER),
            None,
        )

        start_time_ns = agent.start_time_ns
        end_time_ns = time.time_ns()

        attributes: dict[str, Any] = {
            AL2_TYPE: TYPE_STEP,
            AL2_NAME: f"subagent.{agent.agent_type}",
            AL2_EXPERIMENT: "claude-code-session",
        }
        attributes["agent_id"] = event.agent_id
        if first_user_chat is not None:
            attributes["prompt"] = first_user_chat.message

        parent_span = self._state.session_span_id
        if self._state.episode is not None:
            parent_span = self._state.episode.span_id

        step_parent = self._guess_parent_for_agent(event.agent_id, event.transcript_path)

        # If we found a parent from transcript analysis, use it
        if step_parent is not None:
            attempt = self._get_parent_span_id_from_step_parent(agent.agent_id, step_parent)
            if attempt is not None:
                # If failed, just leave the episode span as a parent (shrugs)
                parent_span = attempt

        logger.debug("Sending span to OTEL collector.")
        send_span(
            tracer,
            name=f"claude_code.subagent.{agent.agent_type}",
            attributes=attributes,
            start_time_ns=start_time_ns,
            end_time_ns=end_time_ns,
            context=make_context(self._state.trace_id, parent_span),
            trace_id=self._state.trace_id,
            explicit_span_id=agent.span_id,
        )

    def handle_tool_selected(self, event: HookEvent) -> None:
        self.ensure_episode_started()
        if event.tool_use_id is not None:
            tool_use_id = event.tool_use_id
        elif event.tool_name is not None:
            tool_use_id = event.tool_name
        else:
            tool_use_id = "unknown"

        self._state.pending_tools[tool_use_id] = ToolState(span_id=uuid4(), start_time_ns=time.time_ns())

    def _guess_parent_for_tool(self, tool_use_id: str, transcript_path: str) -> StepParent | None:
        """
        Searches for a parent entity for the given tool.

        Strategy:
        1. Check main transcript cache
        2. Check all subagent transcript caches
        3. Scan main transcript for parent relationships
        4. Scan subagent transcripts to find which one contains this tool_use_id
        """
        # Check if cached in main transcript state (fast path)
        t = self._state.transcript_state
        if tool_use_id in t.tool_parents:
            return t.tool_parents[tool_use_id]

        # Check if cached in any subagent state (fast path)
        for subagent in self._state.subagents.values():
            if tool_use_id in subagent.transcript_state.tool_parents:
                return subagent.transcript_state.tool_parents[tool_use_id]

        # Not cached, need to scan transcripts
        # First scan main transcript for agent parent relationships
        result = search_tool_parent_in_transcript(transcript_path, t, tool_use_id)
        if result is not None:
            return result

        # Scan subagent transcripts if their states exist
        for subagent in self._state.subagents.values():
            agent_state = subagent.transcript_state
            subagent_transcript_path = subagent.get_transcript_path(transcript_path)

            result = search_tool_parent_in_subagent_transcript(subagent_transcript_path, agent_state, tool_use_id)
            if result is not None:
                return result

        return None

    def _guess_parent_for_agent(self, agent_id: str, transcript_path: str) -> StepParent | None:
        """
        Searches for a parent entity for the given agent.

        Strategy:
        1. Check main transcript cache
        2. Check all subagent transcript caches
        3. Scan main transcript for parent relationships
        4. Scan subagent transcripts to find which one contains this agent_id
        """
        # Check if cached in main transcript state (fast path)
        t = self._state.transcript_state
        if agent_id in t.agent_parents:
            return t.agent_parents[agent_id]

        # Check if cached in any subagent state (fast path)
        for subagent in self._state.subagents.values():
            if agent_id in subagent.transcript_state.agent_parents:
                return subagent.transcript_state.agent_parents[agent_id]

        # Not cached, need to scan transcripts
        # First scan main transcript for agent parent relationships
        result = search_agent_parent_in_transcript(transcript_path, t, agent_id)
        if result is not None:
            return result

        # Scan subagent transcripts if their states exist
        for subagent in self._state.subagents.values():
            agent_state = subagent.transcript_state
            subagent_transcript_path = subagent.get_transcript_path(transcript_path)

            result = search_agent_parent_in_subagent_transcript(subagent_transcript_path, agent_state, agent_id)
            if result is not None:
                return result

        return None

    def handle_tool_use(self, tracer: Tracer, event: HookEvent) -> None:
        if event.tool_use_id is None:
            logger.warning("Dropping invalid tool use event with no tool ID.")
            return
        tool_use_id = event.tool_use_id

        tool_state = self._state.pending_tools.pop(tool_use_id, None)
        if tool_state is None:
            logger.warning("Ignoring tool stop: tool `%s` is not known.", tool_use_id)
            return
        start_time_ns = tool_state.start_time_ns
        end_time_ns = time.time_ns()

        attributes: dict[str, Any] = {
            AL2_TYPE: TYPE_STEP,
            AL2_NAME: f"tool.{event.tool_name}",
            AL2_EXPERIMENT: "claude-code-session",
        }

        if event.tool_input:
            agent_output = {
                "actions": [{"name": event.tool_name, "arguments": event.tool_input}],
                "llm_output": {},
            }
            attributes["agent_output"] = json.dumps(agent_output)

        parent_span = self._state.session_span_id
        if self._state.episode is not None:
            parent_span = self._state.episode.span_id

        step_parent = self._guess_parent_for_tool(tool_use_id, event.transcript_path)
        chat_messages_for_tool = self._state.chat_history
        think_transcript_path = Path(event.transcript_path)

        if step_parent is not None and step_parent.type == "agent":
            subagent = self._state.subagents.get(step_parent.agent_id)
            if subagent is not None:
                subagent_transcript_path = subagent.get_transcript_path(event.transcript_path)
                update_transcript(subagent.transcript_state, subagent_transcript_path)
                chat_messages_for_tool = subagent.transcript_state.chat_messages
                think_transcript_path = subagent_transcript_path

        attributes["chat_messages_json"] = (
            TypeAdapter(list[ChatMessage]).dump_json(chat_messages_for_tool).decode("utf-8")
        )
        think = extract_think_for_tool(think_transcript_path, event.tool_use_id)
        attributes["think"] = truncate(think, THINK_MAX_LENGTH) if think else "N/A"

        # If we found a parent from transcript analysis, use it
        if step_parent is not None:
            attempt = self._get_parent_span_id_from_step_parent(tool_use_id, step_parent)
            if attempt is not None:
                # If failed, just leave the episode span as a parent (shrugs)
                parent_span = attempt

        logger.debug("Sending span to OTEL collector.")
        send_span(
            tracer,
            name=f"claude_code.tool.{event.tool_name}",
            attributes=attributes,
            start_time_ns=start_time_ns,
            end_time_ns=end_time_ns,
            context=make_context(self._state.trace_id, parent_span),
            trace_id=self._state.trace_id,
            explicit_span_id=tool_state.span_id,
        )

    def handle_session_end(self, tracer: Tracer, event: HookEvent) -> None:
        if self._state.episode is not None:
            self.handle_stop(tracer, event)
        self.delete(event.session_id)
        attributes: dict[str, Any] = {
            AL2_TYPE: TYPE_TRACE,
            AL2_NAME: "session",
            AL2_EXPERIMENT: "claude-code-session",
        }
        if self._state.prompt is not None:
            attributes["prompt"] = self._state.prompt.text

        send_span(
            tracer,
            name="claude_code.session",
            attributes=attributes,
            start_time_ns=self._state.start_time_ns,
            end_time_ns=time.time_ns(),
            context=make_context(self._state.trace_id, None),
            trace_id=self._state.trace_id,
            explicit_span_id=self._state.session_span_id,
        )
