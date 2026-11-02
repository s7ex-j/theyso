"""OpenCode adapter (EXPERIMENTAL).

OpenCode ships a headless HTTP server (`opencode serve`) with an OpenAPI 3.1
spec and a Server-Sent-Events stream, so no terminal scraping is needed here
either. We start a private `opencode serve` per session:

* bound to 127.0.0.1 on a random port (never reachable from the tailnet),
* protected with a random one-time password (OPENCODE_SERVER_PASSWORD),
* with permissions forced to "ask" for edit / bash / webfetch, so every
  side-effect goes through Theyso's policy and the phone.

The endpoint paths below follow the published server docs; OpenCode evolves
quickly, so they live in one place. Check `http://127.0.0.1:<port>/doc` of your
installed version if something changes, and please open a PR.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import secrets
import shutil
import socket
from typing import Any

import httpx

from theyso.agents.base import AgentAdapter, AgentEvent, TurnUsage, clip

log = logging.getLogger(__name__)

EP_SESSION = "/session"
EP_PROMPT = "/session/{sid}/prompt_async"
EP_ABORT = "/session/{sid}/abort"
EP_EVENTS = "/event"
EP_PERMISSION = "/session/{sid}/permissions/{pid}"

FORCED_PERMISSIONS = {"permission": {"edit": "ask", "bash": "ask", "webfetch": "ask"}}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class OpenCodeAdapter(AgentAdapter):
    name = "opencode"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._proc: asyncio.subprocess.Process | None = None
        self._http: httpx.AsyncClient | None = None
        self._sid: str | None = None
        self._events_task: asyncio.Task[None] | None = None
        self._model: str | None = self.ctx.model

    async def start(self) -> None:
        binary = shutil.which("opencode")
        if not binary:
            raise RuntimeError("`opencode` not found in PATH. Install it from https://opencode.ai")
        port = _free_port()
        password = secrets.token_urlsafe(24)
        env = {
            **os.environ,
            **self.ctx.env,
            "OPENCODE_SERVER_PASSWORD": password,
            "OPENCODE_CONFIG_CONTENT": json.dumps(FORCED_PERMISSIONS),
        }
        self._proc = await asyncio.create_subprocess_exec(
            binary, "serve", "--hostname", "127.0.0.1", "--port", str(port),
            cwd=str(self.ctx.workspace), env=env,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        self._http = httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}", auth=("opencode", password), timeout=30
        )
        await self._wait_ready()
        if self.ctx.resume:
            self._sid = self.ctx.resume
        else:
            resp = await self._http.post(EP_SESSION, json={"title": "Theyso"})
            resp.raise_for_status()
            self._sid = resp.json()["id"]
        self.agent_session_id = self._sid
        self._events_task = asyncio.create_task(self._consume_events(), name="opencode-events")
        await self.ctx.emit(AgentEvent("notice", {"text": "OpenCode session ready", "agent_session_id": self._sid}))

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            raise RuntimeError("OpenCode adapter not started")
        return self._http

    def _session_id(self) -> str:
        if self._sid is None:
            raise RuntimeError("OpenCode session not created")
        return self._sid

    async def _wait_ready(self) -> None:
        http = self._client()
        for _ in range(60):
            if self._proc and self._proc.returncode is not None:
                raise RuntimeError("opencode serve exited during startup")
            with contextlib.suppress(httpx.HTTPError):
                if (await http.get("/doc")).status_code < 500:
                    return
            await asyncio.sleep(0.25)
        raise RuntimeError("opencode serve did not become ready in 15 s")

    async def send(self, text: str) -> None:
        http, sid = self._client(), self._session_id()
        body: dict[str, Any] = {"parts": [{"type": "text", "text": text}]}
        if self._model and "/" in self._model:
            provider, model = self._model.split("/", 1)
            body["model"] = {"providerID": provider, "modelID": model}
        await self.ctx.emit(AgentEvent("status", {"state": "running"}))
        resp = await http.post(EP_PROMPT.format(sid=sid), json=body)
        resp.raise_for_status()

    async def interrupt(self) -> None:
        if self._http and self._sid:
            with contextlib.suppress(httpx.HTTPError):
                await self._http.post(EP_ABORT.format(sid=self._sid))

    async def set_model(self, model: str | None) -> None:
        # OpenCode takes the model per prompt as "provider/model".
        self._model = model
        await self.ctx.emit(AgentEvent("notice", {"text": f"Model set to {model or 'default'}"}))

    async def close(self) -> None:
        if self._events_task:
            self._events_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._events_task
        if self._http:
            await self._http.aclose()
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), 5)
            except TimeoutError:
                self._proc.kill()

    # ── SSE events ───────────────────────────────────────────────────────────
    async def _consume_events(self) -> None:
        async with self._client().stream("GET", EP_EVENTS, timeout=None) as resp:
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    event = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                try:
                    await self._handle(event)
                except Exception:
                    log.exception("Failed to handle OpenCode event")

    async def _handle(self, event: dict[str, Any]) -> None:
        etype = event.get("type", "")
        props = event.get("properties", {}) or {}
        if props.get("sessionID", props.get("part", {}).get("sessionID", self._sid)) != self._sid:
            return

        if etype == "message.part.updated":
            part = props.get("part", {})
            ptype = part.get("type")
            if ptype == "text":
                await self.ctx.emit(AgentEvent("text", {"text": part.get("text", ""), "part_id": part.get("id")}))
            elif ptype == "reasoning":
                await self.ctx.emit(AgentEvent("thinking", {"text": part.get("text", ""), "part_id": part.get("id")}))
            elif ptype == "tool":
                state = part.get("state", {}) or {}
                status = state.get("status")
                if status in ("pending", "running"):
                    await self.ctx.emit(AgentEvent("tool_use", {
                        "tool_use_id": part.get("callID") or part.get("id"),
                        "tool": part.get("tool"), "input": state.get("input", {}),
                    }))
                elif status in ("completed", "error"):
                    out, truncated = clip(str(state.get("output") or state.get("error") or ""))
                    await self.ctx.emit(AgentEvent("tool_result", {
                        "tool_use_id": part.get("callID") or part.get("id"),
                        "output": out, "is_error": status == "error", "truncated": truncated,
                    }))

        elif etype in ("permission.updated", "permission.asked"):
            asyncio.create_task(self._answer_permission(props))

        elif etype == "message.updated":
            info = props.get("info", {})
            if info.get("role") == "assistant" and info.get("time", {}).get("completed"):
                tokens = info.get("tokens", {}) or {}
                cache = tokens.get("cache", {}) or {}
                turn = TurnUsage(
                    model=f"{info.get('providerID', '')}/{info.get('modelID', '')}".strip("/") or self._model,
                    input_tokens=int(tokens.get("input", 0) or 0),
                    output_tokens=int(tokens.get("output", 0) or 0),
                    cache_read_tokens=int(cache.get("read", 0) or 0),
                    cache_write_tokens=int(cache.get("write", 0) or 0),
                    cost_usd=info.get("cost"),
                )
                if self.on_usage:
                    await self.on_usage(turn)
                await self.ctx.emit(AgentEvent("result", {
                    "ok": not info.get("error"), "model": turn.model,
                    "input_tokens": turn.input_tokens, "output_tokens": turn.output_tokens,
                    "cost_usd": turn.cost_usd,
                }))

        elif etype == "session.idle":
            await self.ctx.emit(AgentEvent("status", {"state": "idle"}))

        elif etype == "session.error":
            await self.ctx.emit(AgentEvent("error", {"text": json.dumps(props.get("error", props))[:2000]}))

    async def _answer_permission(self, props: dict[str, Any]) -> None:
        http = self._client()
        perm_id = props.get("id")
        tool = str(props.get("type") or props.get("permission") or "tool")
        tool_input = {"title": props.get("title"), "pattern": props.get("pattern"), **(props.get("metadata") or {})}
        reason = self.ctx.deny_check(tool, tool_input)
        if reason:
            allow = False
        else:
            outcome = await self.ctx.ask(tool, tool_input, props.get("callID"))
            allow = outcome.allow
        with contextlib.suppress(httpx.HTTPError):
            await http.post(
                EP_PERMISSION.format(sid=self._sid, pid=perm_id),
                json={"response": "once" if allow else "reject"},
            )
