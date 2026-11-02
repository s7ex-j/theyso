"""Agent adapter interface.

An adapter turns one coding agent (Claude Code, OpenCode, …) into a stream of
*normalized* events the phone understands, and exposes the same small set of
controls for all of them. Adding a new agent = one new file implementing this.
"""

from __future__ import annotations

import abc
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

EventKind = Literal[
    "partial",  # reply still being written (ephemeral: not numbered, not replayed)
    "text",  # assistant prose (markdown)
    "thinking",  # reasoning summary, collapsed by default in the app
    "tool_use",  # agent wants / started to use a tool
    "tool_result",  # tool output (possibly truncated)
    "status",  # idle | running | waiting_permission | error
    "result",  # end of a turn: usage + cost
    "notice",  # informational (model switched, compacting, rate limit…)
    "error",
]


@dataclass
class AgentEvent:
    kind: EventKind
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class PermissionOutcome:
    allow: bool
    message: str | None = None
    updated_input: dict[str, Any] | None = None


@dataclass
class TurnUsage:
    model: str | None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float | None = None  # as reported by the agent; None if unknown
    duration_ms: int | None = None
    num_turns: int | None = None


EmitFn = Callable[[AgentEvent], Awaitable[None]]
AskFn = Callable[[str, dict[str, Any], str | None], Awaitable[PermissionOutcome]]
"""ask(tool_name, tool_input, tool_use_id) → outcome. Implemented by the session,
which applies the policy and, if needed, waits for the phone's answer."""
DenyCheckFn = Callable[[str, dict[str, Any]], str | None]
"""deny_check(tool_name, tool_input) → reason string if the call must be blocked."""


@dataclass
class AgentContext:
    workspace: Path
    env: dict[str, str]
    model: str | None
    fallback_model: str | None
    permission_mode: Literal["default", "acceptEdits", "plan"]
    emit: EmitFn
    ask: AskFn
    deny_check: DenyCheckFn
    resume: str | None = None
    stream_partial: bool = False


class AgentAdapter(abc.ABC):
    name: str = "base"

    def __init__(self, ctx: AgentContext) -> None:
        self.ctx = ctx
        self.agent_session_id: str | None = None
        self.on_usage: Callable[[TurnUsage], Awaitable[None]] | None = None

    @abc.abstractmethod
    async def start(self) -> None: ...

    @abc.abstractmethod
    async def send(self, text: str) -> None:
        """Queue a user message. Must return quickly; output arrives via emit()."""

    @abc.abstractmethod
    async def interrupt(self) -> None: ...

    async def set_model(self, model: str | None) -> None:
        raise NotImplementedError(f"{self.name} cannot switch model mid-session")

    @abc.abstractmethod
    async def close(self) -> None: ...


TOOL_RESULT_MAX_CHARS = 20_000


def safe_prefix(text: str) -> str:
    """Text up to the last whitespace. A half-written word (maybe half a secret,
    too short for the redaction patterns to recognise) is never sent early."""
    cut = max(text.rfind(" "), text.rfind("\n"), text.rfind("\t"))
    return text[: cut + 1] if cut >= 0 else ""


def clip(text: str, limit: int = TOOL_RESULT_MAX_CHARS) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    head = text[: limit // 2]
    tail = text[-limit // 4 :]
    return f"{head}\n\n… [{len(text) - len(head) - len(tail)} chars omitted] …\n\n{tail}", True
