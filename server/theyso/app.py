"""HTTP + WebSocket servers.

Two independent ASGI apps run in the same process:

* **public**  bound to your Tailscale IP: ``/v1/health``, ``/v1/pair``, ``/v1/ws``.
* **admin**   bound to 127.0.0.1 only, guarded by a local token file: used by
  the ``theyso`` CLI on the PC to show QRs, approve phones, revoke, panic.

A phone can never reach the admin API, and nothing on the admin API is useful
without a shell on the PC already.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import secrets
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
from starlette.types import ASGIApp, Receive, Scope, Send

from theyso import PROTOCOL_VERSION, __version__
from theyso import protocol as P
from theyso.config import Config
from theyso.metrics import Metrics
from theyso.security import handshake as hs
from theyso.security.audit import AuditLog
from theyso.security.devices import Device, DeviceRegistry
from theyso.security.keys import ServerIdentity, b64u, b64u_decode
from theyso.security.network import allowed_host_header, origin_allowed
from theyso.security.pairing import PairingError, PairingManager, TicketState, qr_payload
from theyso.security.ratelimit import AuthThrottle, TokenBucket
from theyso.sessions import SessionError, SessionManager

log = logging.getLogger("theyso")

# WebSocket close codes (4000-4999 are application-defined)
CLOSE_AUTH = 4401
CLOSE_REVOKED = 4403
CLOSE_LOCKED = 4429
CLOSE_TOO_BIG = 4413


@dataclass
class State:
    cfg: Config
    home: Path
    identity: ServerIdentity
    devices: DeviceRegistry
    pairing: PairingManager
    sessions: SessionManager
    audit: AuditLog
    metrics: Metrics
    throttle: AuthThrottle
    bind_host: str
    admin_token: str
    server_name: str = field(default_factory=socket.gethostname)
    live: dict[str, set[Connection]] = field(default_factory=dict)

    @property
    def public_url(self) -> str:
        if self.cfg.server.public_url:
            return self.cfg.server.public_url
        host = f"[{self.bind_host}]" if ":" in self.bind_host else self.bind_host
        return f"ws://{host}:{self.cfg.server.port}"


# ── network hygiene middleware (HTTP + WebSocket) ────────────────────────────
class GuardMiddleware:
    def __init__(self, app: ASGIApp, state: State) -> None:
        self.app = app
        self.state = state

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            host_ok = allowed_host_header(headers.get("host"), self.state.bind_host, self.state.cfg.server.port)
            origin_ok = origin_allowed(headers.get("origin"))
            if not (host_ok and origin_ok):
                client = (scope.get("client") or ("?", 0))[0]
                self.state.audit.write("rejected_request", addr=client, host=headers.get("host"),
                                       origin=headers.get("origin"), path=scope.get("path"))
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 4400})
                    return
                response = JSONResponse({"error": "forbidden"}, status_code=403)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


# ── public API ───────────────────────────────────────────────────────────────
class PairRequest(BaseModel):
    pid: str = Field(max_length=64)
    device_pub: str = Field(max_length=128)
    proof: str = Field(max_length=128)
    name: str = Field(max_length=120)
    platform: str = Field("unknown", max_length=40)


class Connection:
    """One authenticated WebSocket. Implements the sessions.Subscriber protocol."""

    def __init__(self, ws: WebSocket, device: Device, state: State) -> None:
        self.ws = ws
        self.device = device
        self.device_id = device.device_id
        self.state = state
        self.bucket = TokenBucket(state.cfg.security.messages_per_minute)
        self._lock = asyncio.Lock()

    async def send_json(self, payload: dict[str, Any]) -> None:
        async with self._lock:
            await self.ws.send_text(json.dumps(payload, ensure_ascii=False, default=str))

    async def close(self, code: int, reason: str = "") -> None:
        with contextlib.suppress(Exception):
            await self.ws.close(code=code, reason=reason)


def create_public_app(state: State) -> FastAPI:
    app = FastAPI(title="theyso", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/v1/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "v": PROTOCOL_VERSION}

    @app.post("/v1/pair")
    async def pair(req: PairRequest, request: Request) -> JSONResponse:
        addr = request.client.host if request.client else "?"
        throttle_key = f"pair:{addr}"
        if state.throttle.is_locked(throttle_key):
            return JSONResponse({"error": P.E_LOCKED}, status_code=429)
        try:
            ticket = state.pairing.present(req.pid, req.device_pub, req.proof, req.name, req.platform, addr)
        except PairingError as exc:
            state.throttle.fail(throttle_key)
            state.audit.write("pair_failed", addr=addr, code=exc.code)
            return JSONResponse({"error": exc.code}, status_code=403)

        state.audit.write("pair_pending", addr=addr, name=ticket.candidate.name if ticket.candidate else None)
        remaining = max(1.0, ticket.expires_at - time.time()) + 60  # human gets an extra minute
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(ticket.decided.wait(), timeout=remaining)

        if ticket.state == TicketState.APPROVED and ticket.device_id:
            device_pub = b64u_decode(req.device_pub)
            sig = state.identity.sign(b"theyso-paired-v1|" + ticket.device_id.encode() + b"|" + device_pub)
            return JSONResponse({
                "status": "approved",
                "device_id": ticket.device_id,
                "server_name": state.server_name,
                "server_fingerprint": state.identity.fingerprint,
                "signature": b64u(sig),
            })
        state.pairing.reject(req.pid)
        return JSONResponse({"error": "rejected"}, status_code=403)

    @app.websocket("/v1/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        addr = ws.client.host if ws.client else "?"
        if state.throttle.is_locked(f"auth:{addr}"):
            await ws.close(code=CLOSE_LOCKED)
            return
        await ws.accept()
        device = await authenticate(ws, state, addr)
        if device is None:
            return
        conn = Connection(ws, device, state)
        state.live.setdefault(device.device_id, set()).add(conn)
        state.devices.touch(device.device_id, addr)
        state.audit.write("connected", device=device.device_id, addr=addr)
        try:
            await conn.send_json(welcome(state))
            await serve_connection(conn, state)
        except WebSocketDisconnect:
            pass
        finally:
            state.sessions.detach_everywhere(conn)
            state.live.get(device.device_id, set()).discard(conn)
            state.audit.write("disconnected", device=device.device_id, addr=addr)

    return app


async def authenticate(ws: WebSocket, state: State, addr: str) -> Device | None:
    timeout = state.cfg.security.auth_timeout_s
    key = f"auth:{addr}"

    async def fail(reason: str) -> None:
        locked = state.throttle.fail(key)
        state.audit.write("auth_failed", addr=addr, reason=reason, locked=locked)
        with contextlib.suppress(Exception):
            await ws.send_text(json.dumps(P.error(P.E_AUTH, "Authentication failed")))
            await ws.close(code=CLOSE_AUTH)

    try:
        hello = P.parse_client(await asyncio.wait_for(ws.receive_text(), timeout))
        if not isinstance(hello, P.AuthHello):
            await fail("first frame was not auth.hello")
            return None
        client_nonce = b64u_decode(hello.client_nonce)
        server_nonce = hs.new_nonce()
        transcript = hs.transcript(hello.device_id, client_nonce, server_nonce, state.identity.public_raw)
        # Always answer with a challenge, even for unknown devices, so device ids
        # cannot be enumerated by watching where the handshake stops.
        await ws.send_text(json.dumps(P.out(
            "auth.challenge",
            server_nonce=b64u(server_nonce),
            signature=b64u(state.identity.sign(hs.server_signed_part(transcript))),
            v=PROTOCOL_VERSION,
        )))
        response = P.parse_client(await asyncio.wait_for(ws.receive_text(), timeout))
        if not isinstance(response, P.AuthResponse):
            await fail("expected auth.response")
            return None
        device = state.devices.get_active(hello.device_id)
        if device is None or not device.verify(b64u_decode(response.signature), hs.client_signed_part(transcript)):
            await fail("bad signature or unknown/revoked device")
            return None
    except (TimeoutError, ValidationError, ValueError, WebSocketDisconnect):
        await fail("handshake error")
        return None

    state.throttle.success(key)
    return device


def welcome(state: State) -> dict[str, Any]:
    cfg = state.cfg
    return P.out(
        "auth.ok",
        server_name=state.server_name,
        server_version=__version__,
        protocol=PROTOCOL_VERSION,
        profiles=[
            {"name": n, "label": p.label or n, "agent": p.agent, "model": p.model,
             "daily_budget_usd": p.daily_budget_usd}
            for n, p in cfg.profiles.items()
        ],
        workspaces=state.sessions.list_workspaces(),
        sessions=[s.info() for s in state.sessions.sessions.values()],
        limits={"max_message_bytes": cfg.server.max_message_bytes,
                "permission_timeout_s": cfg.server.permission_timeout_s},
    )


async def serve_connection(conn: Connection, state: State) -> None:
    max_bytes = state.cfg.server.max_message_bytes
    while True:
        raw = await conn.ws.receive_text()
        if len(raw.encode()) > max_bytes:
            await conn.send_json(P.error(P.E_BAD, "Message too large"))
            await conn.close(CLOSE_TOO_BIG)
            return
        if state.devices.get_active(conn.device_id) is None:
            await conn.close(CLOSE_REVOKED, "device revoked")
            return
        if not conn.bucket.allow():
            await conn.send_json(P.error(P.E_RATE, "Slow down"))
            continue
        try:
            msg = P.parse_client(raw)
        except ValidationError as exc:
            await conn.send_json(P.error(P.E_BAD, f"Invalid message: {exc.errors()[0]['msg']}"))
            continue
        try:
            await dispatch(msg, conn, state)
        except SessionError as exc:
            await conn.send_json(P.error(exc.code, str(exc), ref=msg.id, sid=getattr(msg, "sid", None)))
        except Exception:
            log.exception("Unhandled error while dispatching %s", msg.type)
            await conn.send_json(P.error("internal", "Internal error", ref=msg.id))


async def dispatch(msg: P.ClientMessage, conn: Connection, state: State) -> None:
    sm = state.sessions
    match msg:
        case P.Ping():
            await conn.send_json(P.out("pong", id=msg.id, ts=time.time()))
        case P.SessionList():
            await conn.send_json(P.out("session.list.result", id=msg.id,
                                       sessions=[s.info() for s in sm.sessions.values()],
                                       workspaces=sm.list_workspaces()))
        case P.SessionCreate():
            session = await sm.create(msg.profile, msg.workspace, msg.title, msg.resume_agent_session,
                                      conn.device_id)
            await conn.send_json(P.out("session.created", id=msg.id, session=session.info()))
            await session.attach(conn, 0)
        case P.SessionAttach():
            await sm.get(msg.sid).attach(conn, msg.after_seq)
        case P.SessionDetach():
            sm.get(msg.sid).subscribers.discard(conn)
        case P.SessionClose():
            await sm.close(msg.sid, "closed from phone")
        case P.Prompt():
            await sm.get(msg.sid).prompt(msg.text, conn.device_id)
        case P.Interrupt():
            await sm.get(msg.sid).interrupt(conn.device_id)
        case P.SetModel():
            session = sm.get(msg.sid)
            if session.adapter is None:
                raise SessionError(P.E_AGENT, "Agent not running")
            try:
                await session.adapter.set_model(msg.model)
            except NotImplementedError as exc:
                raise SessionError(P.E_BAD, str(exc)) from exc
            state.audit.write("model_set", sid=msg.sid, model=msg.model, device=conn.device_id)
        case P.PermissionReply():
            sm.get(msg.sid).reply(msg.request_id, msg.decision == "allow", msg.message, msg.confirmed_strong)
        case P.UsageQuery():
            await conn.send_json(P.out("usage.result", id=msg.id, **state.metrics.summary(msg.days)))
        case P.Panic():
            closed = await sm.close_all("panic button")
            state.audit.write("panic", device=conn.device_id, sessions_closed=closed)
            await conn.send_json(P.out("panic.ok", id=msg.id, sessions_closed=closed))
        case P.AuthHello() | P.AuthResponse():
            await conn.send_json(P.error(P.E_BAD, "Already authenticated", ref=msg.id))


# ── admin API (127.0.0.1 only) ───────────────────────────────────────────────
def create_admin_app(state: State) -> FastAPI:
    app = FastAPI(title="theyso-admin", docs_url=None, redoc_url=None, openapi_url=None)

    def check(authorization: str | None) -> None:
        expected = f"Bearer {state.admin_token}"
        if not authorization or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=401)

    @app.middleware("http")
    async def loopback_only(request: Request, call_next: Any) -> Any:
        if not request.client or request.client.host not in {"127.0.0.1", "::1"}:
            return JSONResponse({"error": "forbidden"}, status_code=403)
        if request.headers.get("origin") is not None:  # no browser may ever call the admin API
            return JSONResponse({"error": "forbidden"}, status_code=403)
        return await call_next(request)

    @app.post("/admin/pair/start")
    async def pair_start(authorization: str | None = Header(None)) -> dict[str, Any]:
        check(authorization)
        ticket = state.pairing.create()
        state.audit.write("pair_started", pid=ticket.pid)
        return {
            "pid": ticket.pid,
            "expires_at": ticket.expires_at,
            "url": state.public_url,
            "server_fingerprint": state.identity.fingerprint,
            "qr": qr_payload(state.public_url, ticket, state.identity.public_b64, state.server_name),
        }

    @app.get("/admin/pair/{pid}/wait")
    async def pair_wait(pid: str, authorization: str | None = Header(None)) -> dict[str, Any]:
        check(authorization)
        ticket = state.pairing.get(pid)
        if ticket is None:
            raise HTTPException(404)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(ticket.candidate_arrived.wait(), timeout=25)
        ticket = state.pairing.get(pid)
        if ticket is None:
            raise HTTPException(404)
        cand = ticket.candidate
        return {
            "state": ticket.state.value,
            "candidate": None if cand is None else {
                "name": cand.name, "platform": cand.platform, "sas": cand.sas,
                "fingerprint": cand.device_fingerprint, "addr": cand.remote_addr,
            },
        }

    @app.post("/admin/pair/{pid}/approve")
    async def pair_approve(pid: str, authorization: str | None = Header(None)) -> dict[str, Any]:
        check(authorization)
        ticket = state.pairing.get(pid)
        if ticket is None or ticket.state != TicketState.PENDING or ticket.candidate is None:
            raise HTTPException(409, "Nothing to approve")
        try:
            device = state.devices.add(ticket.candidate.name, ticket.candidate.platform,
                                       ticket.candidate.device_pub, state.cfg.security.max_devices)
        except ValueError as exc:
            state.pairing.reject(pid)
            raise HTTPException(409, str(exc)) from exc
        state.pairing.approve(pid, device.device_id)
        state.audit.write("paired", device=device.device_id, name=device.name, fingerprint=device.fingerprint)
        return {"device_id": device.device_id, "name": device.name, "fingerprint": device.fingerprint}

    @app.post("/admin/pair/{pid}/reject")
    async def pair_reject(pid: str, authorization: str | None = Header(None)) -> dict[str, Any]:
        check(authorization)
        state.pairing.reject(pid)
        state.audit.write("pair_rejected", pid=pid)
        return {"ok": True}

    @app.get("/admin/devices")
    async def devices(authorization: str | None = Header(None)) -> list[dict[str, Any]]:
        check(authorization)
        return [{**d.__dict__, "fingerprint": d.fingerprint, "online": bool(state.live.get(d.device_id))}
                for d in state.devices.all()]

    async def kick(device_id: str) -> None:
        for conn in list(state.live.get(device_id, set())):
            await conn.close(CLOSE_REVOKED, "device revoked")

    @app.post("/admin/devices/{device_id}/revoke")
    async def revoke(device_id: str, authorization: str | None = Header(None)) -> dict[str, Any]:
        check(authorization)
        ok = state.devices.revoke(device_id)
        await kick(device_id)
        state.audit.write("revoked", device=device_id, ok=ok)
        return {"revoked": ok}

    @app.post("/admin/devices/revoke-all")
    async def revoke_all(authorization: str | None = Header(None)) -> dict[str, Any]:
        check(authorization)
        n = state.devices.revoke_all()
        for device_id in list(state.live):
            await kick(device_id)
        state.audit.write("revoked_all", count=n)
        return {"revoked": n}

    @app.get("/admin/sessions")
    async def sessions(authorization: str | None = Header(None)) -> list[dict[str, Any]]:
        check(authorization)
        return [s.info() for s in state.sessions.sessions.values()]

    @app.post("/admin/panic")
    async def panic(authorization: str | None = Header(None)) -> dict[str, Any]:
        check(authorization)
        n = await state.sessions.close_all("panic from PC")
        state.audit.write("panic", device="local", sessions_closed=n)
        return {"sessions_closed": n}

    @app.get("/admin/audit")
    async def audit(n: int = 50, authorization: str | None = Header(None)) -> list[dict[str, Any]]:
        check(authorization)
        return state.audit.tail(min(max(n, 1), 1000))

    return app


def new_admin_token() -> str:
    return secrets.token_urlsafe(32)
