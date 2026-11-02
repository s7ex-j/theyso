"""Sessions: one running agent + its event history + the phones watching it.

Events are numbered (``seq``) and kept in a ring buffer, so when the phone
loses signal in the elevator it re-attaches with ``after_seq`` and gets exactly
what it missed — no duplicated or lost messages.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from theyso.agents import AgentAdapter, AgentContext, build_adapter
from theyso.agents.base import AgentEvent, PermissionOutcome, TurnUsage
from theyso.config import Config, Profile
from theyso.metrics import Metrics
from theyso.power import KeepAwake
from theyso.security.audit import AuditLog
from theyso.security.keys import b64u
from theyso.security.policy import Decision, Policy
from theyso.security.redact import redact

log = logging.getLogger(__name__)


class Subscriber(Protocol):
    device_id: str

    async def send_json(self, payload: dict[str, Any]) -> None: ...


class SessionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class PendingPermission:
    request_id: str
    tool: str
    tool_input: dict[str, Any]
    decision: Decision
    created: float
    future: asyncio.Future[tuple[bool, str | None, str]] = field(
        default_factory=lambda: asyncio.get_running_loop().create_future()
    )

    def frame(self, sid: str) -> dict[str, Any]:
        return {
            "type": "permission.request",
            "sid": sid,
            "request_id": self.request_id,
            "tool": self.tool,
            "input": redact(self.tool_input)[0],
            "risk": self.decision.risk,
            "reason": self.decision.reason,
            "requires_strong_auth": self.decision.risk == "high",
            "created": self.created,
        }


class Session:
    def __init__(
        self,
        sid: str,
        title: str,
        profile_name: str,
        profile: Profile,
        workspace: Path,
        cfg: Config,
        policy: Policy,
        metrics: Metrics,
        audit: AuditLog,
    ) -> None:
        self.sid = sid
        self.title = title
        self.profile_name = profile_name
        self.profile = profile
        self.workspace = workspace
        self.cfg = cfg
        self.policy = policy
        self.metrics = metrics
        self.audit = audit
        self.created = time.time()
        self.last_activity = self.created
        self.state = "starting"
        self.seq = 0
        self.buffer: deque[dict[str, Any]] = deque(maxlen=cfg.server.event_buffer)
        self.subscribers: set[Subscriber] = set()
        self.pending: dict[str, PendingPermission] = {}
        self.adapter: AgentAdapter | None = None
        self._send_lock = asyncio.Lock()

    # ── lifecycle ────────────────────────────────────────────────────────────
    async def start(self, resume: str | None) -> None:
        ctx = AgentContext(
            workspace=self.workspace,
            env=self.profile.resolved_env(),
            model=self.profile.model,
            fallback_model=self.profile.fallback_model,
            permission_mode=self.cfg.policy.default_permission_mode,
            emit=self.emit,
            ask=self.ask,
            deny_check=self.deny_check,
            resume=resume,
            stream_partial=self.cfg.server.stream_partial,
        )
        self.adapter = build_adapter(self.profile.agent, ctx)
        self.adapter.on_usage = self._on_usage
        await self.adapter.start()
        self.state = "idle"

    async def close(self, reason: str = "closed") -> None:
        for pending in list(self.pending.values()):
            if not pending.future.done():
                pending.future.set_result((False, f"Session {reason}", "system"))
        if self.adapter:
            await self.adapter.close()
        self.state = "closed"
        await self._broadcast({"type": "session.closed", "sid": self.sid, "reason": reason})

    def info(self) -> dict[str, Any]:
        return {
            "sid": self.sid,
            "title": self.title,
            "profile": self.profile_name,
            "agent": self.profile.agent,
            "model": self.profile.model,
            "workspace": str(self.workspace),
            "state": self.state,
            "created": self.created,
            "last_activity": self.last_activity,
            "last_seq": self.seq,
            "pending_permissions": len(self.pending),
            "agent_session_id": self.adapter.agent_session_id if self.adapter else None,
        }

    # ── events out ───────────────────────────────────────────────────────────
    async def emit(self, event: AgentEvent) -> None:
        data = event.data
        if self.cfg.security.redact_secrets:
            data, n = redact(data)
            if n:
                data = {**data, "redactions": n}
        if event.kind == "status":
            self.state = data.get("state", self.state)
        self.last_activity = time.time()
        if event.kind == "partial":
            # Ephemeral: not numbered, not buffered, never replayed — the final
            # "text" event replaces it. Keeps the replay buffer for real history.
            await self._broadcast({"type": "event", "kind": "partial", "sid": self.sid, "data": data})
            return
        await self._publish({"type": "event", "kind": event.kind, "data": data})

    async def _publish(self, frame: dict[str, Any]) -> None:
        self.seq += 1
        frame = {**frame, "sid": self.sid, "seq": self.seq, "ts": round(time.time(), 3)}
        self.buffer.append(frame)
        await self._broadcast(frame)

    async def _broadcast(self, frame: dict[str, Any]) -> None:
        dead = []
        for sub in list(self.subscribers):
            try:
                await sub.send_json(frame)
            except Exception:
                dead.append(sub)
        for sub in dead:
            self.subscribers.discard(sub)

    async def attach(self, sub: Subscriber, after_seq: int) -> None:
        self.subscribers.add(sub)
        await sub.send_json({"type": "session.attached", "sid": self.sid, "session": self.info()})
        oldest = self.buffer[0]["seq"] if self.buffer else self.seq + 1
        if after_seq + 1 < oldest:
            await sub.send_json({"type": "notice", "sid": self.sid,
                                 "text": "Some older events are no longer in the buffer."})
        for frame in list(self.buffer):
            if frame["seq"] > after_seq:
                await sub.send_json(frame)
        for pending in self.pending.values():  # always re-send open questions
            await sub.send_json(pending.frame(self.sid))

    # ── user input ───────────────────────────────────────────────────────────
    def _agent(self) -> AgentAdapter:
        if self.adapter is None:
            raise SessionError("agent_error", "Agent is not running")
        return self.adapter

    async def prompt(self, text: str, device_id: str) -> None:
        adapter = self._agent()
        budget = self.profile.daily_budget_usd
        if budget is not None and self.metrics.spent_today(self.profile_name) >= budget:
            raise SessionError("budget_exceeded", f"Daily budget of ${budget:.2f} reached for this profile")
        self.audit.write("prompt", sid=self.sid, device=device_id, **self.audit.prompt_field(text))
        await self._publish({"type": "event", "kind": "user", "data": {"text": text, "device_id": device_id}})
        await adapter.send(text)

    async def interrupt(self, device_id: str) -> None:
        adapter = self._agent()
        self.audit.write("interrupt", sid=self.sid, device=device_id)
        for pending in list(self.pending.values()):
            if not pending.future.done():
                pending.future.set_result((False, "Interrupted by user", "phone"))
        await adapter.interrupt()

    # ── permissions ──────────────────────────────────────────────────────────
    def deny_check(self, tool: str, tool_input: dict[str, Any]) -> str | None:
        decision = self.policy.evaluate(tool, tool_input, self.workspace)
        if decision.action == "deny":
            self.audit.write("tool_denied_by_policy", sid=self.sid, tool=tool, reason=decision.reason)
            self.metrics.record_tool(self.sid, self.profile_name, tool, decision.risk, "deny", "policy", 0)
            return decision.reason
        return None

    async def ask(self, tool: str, tool_input: dict[str, Any], tool_use_id: str | None) -> PermissionOutcome:
        decision = self.policy.evaluate(tool, tool_input, self.workspace)
        if decision.action == "deny":
            return PermissionOutcome(False, f"Blocked by Theyso policy: {decision.reason}")
        if decision.action == "allow":
            self.metrics.record_tool(self.sid, self.profile_name, tool, decision.risk, "allow", "policy", 0)
            return PermissionOutcome(True)

        request_id = "perm_" + b64u(secrets.token_bytes(6))
        pending = PendingPermission(request_id, tool, tool_input, decision, time.time())
        self.pending[request_id] = pending
        previous_state, self.state = self.state, "waiting_permission"
        await self._broadcast(pending.frame(self.sid))
        try:
            allow, message, decided_by = await asyncio.wait_for(
                pending.future, timeout=self.cfg.server.permission_timeout_s
            )
        except TimeoutError:
            allow, message, decided_by = False, "No answer from the phone in time", "timeout"
        finally:
            self.pending.pop(request_id, None)
            if self.state == "waiting_permission" and not self.pending:
                self.state = previous_state if previous_state != "waiting_permission" else "running"

        latency = int((time.time() - pending.created) * 1000)
        self.metrics.record_tool(self.sid, self.profile_name, tool, decision.risk,
                                 "allow" if allow else "deny", decided_by, latency)
        self.audit.write("permission", sid=self.sid, tool=tool, risk=decision.risk,
                         allow=allow, by=decided_by, latency_ms=latency)
        await self._publish({"type": "event", "kind": "permission_resolved",
                             "data": {"request_id": request_id, "allow": allow, "by": decided_by}})
        return PermissionOutcome(allow, message)

    def reply(self, request_id: str, allow: bool, message: str | None, confirmed_strong: bool) -> None:
        pending = self.pending.get(request_id)
        if pending is None or pending.future.done():
            raise SessionError("not_found", "That permission request is no longer open")
        if allow and pending.decision.risk == "high" and not confirmed_strong:
            raise SessionError("forbidden", "High-risk actions require biometric confirmation in the app")
        pending.future.set_result((allow, message, "phone"))

    async def _on_usage(self, turn: TurnUsage) -> None:
        agent = self.profile.agent
        self.metrics.record_turn(self.sid, agent, self.profile_name, self.profile, turn)


class SessionManager:
    def __init__(self, cfg: Config, policy: Policy, metrics: Metrics, audit: AuditLog,
                 keep_awake: KeepAwake | None = None) -> None:
        self.cfg = cfg
        self.policy = policy
        self.metrics = metrics
        self.audit = audit
        self.keep_awake = keep_awake
        self.sessions: dict[str, Session] = {}
        self._reaper: asyncio.Task[None] | None = None

    def start_reaper(self) -> None:
        self._reaper = asyncio.create_task(self._reap_idle())

    def validate_workspace(self, raw: str) -> Path:
        allowed = self.cfg.workspaces.resolved()
        if not allowed:
            raise SessionError("forbidden", "No workspaces configured. Add [workspaces].allowed in config.toml")
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = allowed[0] / path
        path = path.resolve()  # resolves symlinks: no escaping via a link
        if not any(path == a or path.is_relative_to(a) for a in allowed):
            raise SessionError("forbidden", "Workspace is outside the allowed folders")
        if not path.is_dir():
            raise SessionError("not_found", "Workspace folder does not exist")
        return path

    def list_workspaces(self) -> list[dict[str, Any]]:
        out = []
        for root in self.cfg.workspaces.resolved():
            if not root.is_dir():
                continue
            children = sorted(p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))
            out.append({"root": str(root), "projects": children[:200]})
        return out

    async def create(self, profile_name: str, workspace: str, title: str | None,
                     resume: str | None, device_id: str) -> Session:
        profile = self.cfg.profiles.get(profile_name)
        if profile is None:
            raise SessionError("not_found", f"Unknown profile '{profile_name}'")
        if len(self.sessions) >= self.cfg.server.max_sessions:
            raise SessionError("forbidden",
                               f"Session limit reached ({self.cfg.server.max_sessions}). Close one first.")
        path = self.validate_workspace(workspace)
        sid = "s_" + b64u(secrets.token_bytes(9))
        session = Session(sid, title or path.name, profile_name, profile, path,
                          self.cfg, self.policy, self.metrics, self.audit)
        self.sessions[sid] = session
        try:
            await session.start(resume)
        except Exception as exc:
            self.sessions.pop(sid, None)
            raise SessionError("agent_error", f"Could not start {profile.agent}: {exc}") from exc
        self.audit.write("session_created", sid=sid, device=device_id, profile=profile_name, workspace=str(path))
        self._power()
        return session

    def get(self, sid: str) -> Session:
        session = self.sessions.get(sid)
        if session is None:
            raise SessionError("not_found", "Unknown session")
        return session

    async def close(self, sid: str, reason: str = "closed") -> None:
        session = self.sessions.pop(sid, None)
        if session:
            await session.close(reason)
            self.audit.write("session_closed", sid=sid, reason=reason)
        self._power()

    def _power(self) -> None:
        if self.keep_awake is not None:
            self.keep_awake.update(len(self.sessions))

    async def close_all(self, reason: str) -> int:
        sids = list(self.sessions)
        for sid in sids:
            await self.close(sid, reason)
        return len(sids)

    def detach_everywhere(self, sub: Subscriber) -> None:
        for session in self.sessions.values():
            session.subscribers.discard(sub)

    async def _reap_idle(self) -> None:
        while True:
            await asyncio.sleep(60)
            self._power()  # react to plugging / unplugging the charger
            limit = self.cfg.server.idle_session_timeout_s
            now = time.time()
            for sid, session in list(self.sessions.items()):
                if session.state == "idle" and not session.subscribers and now - session.last_activity > limit:
                    with contextlib.suppress(Exception):
                        await self.close(sid, "idle timeout")
