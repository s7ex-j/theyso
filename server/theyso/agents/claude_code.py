"""Claude Code adapter, built on the Claude Agent SDK.

Why not a pseudo-terminal (node-pty / pexpect)? Claude Code's terminal UI
redraws constantly (spinners, boxes, colors, menus). Scraping it is fragile and
breaks on every UI update. The Agent SDK drives the same `claude` binary in its
structured streaming mode and hands us typed messages instead.

It works with ANY Anthropic-compatible endpoint: the profile's env
(ANTHROPIC_BASE_URL, ANTHROPIC_AUTH_TOKEN, …) is passed straight to the CLI,
which is exactly how routers such as 9Router, LiteLLM or OpenRouter are used.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from typing import Any

from theyso.agents.base import AgentAdapter, AgentEvent, TurnUsage, clip, safe_prefix

PARTIAL_FLUSH_S = 0.15  # at most ~7 partial updates per second: smooth, but cheap on battery

log = logging.getLogger(__name__)


class ClaudeCodeAdapter(AgentAdapter):
    name = "claude-code"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._client: Any = None
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._model: str | None = self.ctx.model
        self._partial: dict[int, str] = {}
        self._stream_n = 0
        self._last_flush = 0.0

    async def start(self) -> None:
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, HookMatcher

        async def can_use_tool(tool_name: str, tool_input: dict[str, Any], context: Any) -> Any:
            from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

            outcome = await self.ctx.ask(tool_name, tool_input, getattr(context, "tool_use_id", None))
            if outcome.allow:
                return PermissionResultAllow(updated_input=outcome.updated_input or tool_input)
            return PermissionResultDeny(message=outcome.message or "Denied from Theyso", interrupt=False)

        async def pre_tool_use(input_data: Any, tool_use_id: str | None, context: Any) -> Any:
            # Runs for EVERY tool call, including ones the CLI would auto-approve.
            reason = self.ctx.deny_check(input_data["tool_name"], input_data.get("tool_input", {}))
            if reason:
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": f"Blocked by Theyso policy: {reason}",
                    }
                }
            return {}

        options = ClaudeAgentOptions(
            cwd=str(self.ctx.workspace),
            env=self.ctx.env,
            model=self.ctx.model,
            fallback_model=self.ctx.fallback_model,
            permission_mode=self.ctx.permission_mode,
            can_use_tool=can_use_tool,
            hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[pre_tool_use])]},
            resume=self.ctx.resume,
            include_partial_messages=self.ctx.stream_partial,
            enable_file_checkpointing=True,
            # Load the user's normal CLAUDE.md / settings so the session behaves
            # exactly like typing `claude` in that folder.
            setting_sources=["user", "project", "local"],
        )
        self._client = ClaudeSDKClient(options=options)
        await self._client.connect()
        self._worker = asyncio.create_task(self._run(), name="claude-code-worker")

    async def send(self, text: str) -> None:
        await self._queue.put(text)

    async def interrupt(self) -> None:
        if self._client is not None:
            with contextlib.suppress(Exception):
                await self._client.interrupt()

    async def set_model(self, model: str | None) -> None:
        await self._client.set_model(model)
        self._model = model
        await self.ctx.emit(AgentEvent("notice", {"text": f"Model set to {model or 'default'}"}))

    async def close(self) -> None:
        if self._worker:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._worker
        if self._client is not None:
            with contextlib.suppress(Exception):
                await self._client.disconnect()

    # ── internals ────────────────────────────────────────────────────────────
    async def _run(self) -> None:
        while True:
            text = await self._queue.get()
            await self.ctx.emit(AgentEvent("status", {"state": "running"}))
            try:
                await self._client.query(text)
                async for message in self._client.receive_response():
                    await self._translate(message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # surface agent crashes to the phone instead of dying silently
                log.exception("Claude Code turn failed")
                await self.ctx.emit(AgentEvent("error", {"text": f"{type(exc).__name__}: {exc}"}))
            finally:
                await self.ctx.emit(AgentEvent("status", {"state": "idle"}))

    async def _flush_partial(self, index: int, final: bool = False) -> None:
        text = self._partial.get(index, "")
        shown = text if final else safe_prefix(text)
        if shown:
            await self.ctx.emit(AgentEvent("partial", {"stream_id": f"{self._stream_n}:{index}", "text": shown}))
        self._last_flush = time.monotonic()

    async def _on_stream_event(self, event: dict[str, Any]) -> None:
        etype = event.get("type")
        if etype == "message_start":
            self._stream_n += 1
            self._partial = {}
        elif etype == "content_block_delta":
            delta = event.get("delta") or {}
            if delta.get("type") == "text_delta":
                index = int(event.get("index", 0))
                self._partial[index] = self._partial.get(index, "") + str(delta.get("text", ""))
                if time.monotonic() - self._last_flush >= PARTIAL_FLUSH_S:
                    await self._flush_partial(index)

    async def _translate(self, message: Any) -> None:
        from claude_agent_sdk import (
            AssistantMessage,
            ResultMessage,
            StreamEvent,
            SystemMessage,
            TextBlock,
            ThinkingBlock,
            ToolResultBlock,
            ToolUseBlock,
            UserMessage,
        )

        if isinstance(message, StreamEvent):
            if message.parent_tool_use_id is None:  # ignore sub-agent chatter
                await self._on_stream_event(message.event)
        elif isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    await self.ctx.emit(AgentEvent("text", {"text": block.text, "model": message.model}))
                elif isinstance(block, ThinkingBlock):
                    await self.ctx.emit(AgentEvent("thinking", {"text": block.thinking}))
                elif isinstance(block, ToolUseBlock):
                    await self.ctx.emit(
                        AgentEvent("tool_use", {"tool_use_id": block.id, "tool": block.name, "input": block.input})
                    )
        elif isinstance(message, UserMessage) and isinstance(message.content, list):
            for block in message.content:
                if isinstance(block, ToolResultBlock):
                    content = block.content
                    text = content if isinstance(content, str) else json.dumps(content, default=str)
                    clipped, truncated = clip(text or "")
                    await self.ctx.emit(
                        AgentEvent(
                            "tool_result",
                            {
                                "tool_use_id": block.tool_use_id,
                                "output": clipped,
                                "is_error": bool(block.is_error),
                                "truncated": truncated,
                            },
                        )
                    )
        elif isinstance(message, SystemMessage):
            if message.subtype == "init":
                self.agent_session_id = message.data.get("session_id", self.agent_session_id)
                self._model = message.data.get("model", self._model)
                await self.ctx.emit(
                    AgentEvent(
                        "notice",
                        {"text": "Session ready", "model": self._model, "agent_session_id": self.agent_session_id},
                    )
                )
        elif isinstance(message, ResultMessage):
            self.agent_session_id = message.session_id or self.agent_session_id
            usage = message.usage or {}
            turn = TurnUsage(
                model=self._model,
                input_tokens=int(usage.get("input_tokens", 0) or 0),
                output_tokens=int(usage.get("output_tokens", 0) or 0),
                cache_read_tokens=int(usage.get("cache_read_input_tokens", 0) or 0),
                cache_write_tokens=int(usage.get("cache_creation_input_tokens", 0) or 0),
                cost_usd=message.total_cost_usd,
                duration_ms=message.duration_ms,
                num_turns=message.num_turns,
            )
            if self.on_usage:
                await self.on_usage(turn)
            await self.ctx.emit(
                AgentEvent(
                    "result",
                    {
                        "ok": not message.is_error,
                        "subtype": message.subtype,
                        "model": turn.model,
                        "input_tokens": turn.input_tokens,
                        "output_tokens": turn.output_tokens,
                        "cost_usd": turn.cost_usd,
                        "duration_ms": turn.duration_ms,
                    },
                )
            )
