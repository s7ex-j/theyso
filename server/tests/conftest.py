from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from theyso.agents.base import AgentAdapter, AgentEvent, TurnUsage
from theyso.app import State
from theyso.config import Config
from theyso.metrics import Metrics
from theyso.security.audit import AuditLog
from theyso.security.devices import DeviceRegistry
from theyso.security.keys import ServerIdentity
from theyso.security.pairing import PairingManager
from theyso.security.policy import Policy
from theyso.security.ratelimit import AuthThrottle
from theyso.sessions import SessionManager


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class FakeAdapter(AgentAdapter):
    """Echo agent. A prompt starting with 'tool:' asks permission for Bash."""

    name = "fake"

    async def start(self) -> None:
        self.agent_session_id = "fake-session"

    async def send(self, text: str) -> None:
        asyncio.create_task(self._turn(text))

    async def _turn(self, text: str) -> None:
        await self.ctx.emit(AgentEvent("status", {"state": "running"}))
        if text.startswith("tool:"):
            command = text[5:]
            reason = self.ctx.deny_check("Bash", {"command": command})
            if reason:
                await self.ctx.emit(AgentEvent("text", {"text": f"blocked: {reason}"}))
            else:
                outcome = await self.ctx.ask("Bash", {"command": command}, "tu_1")
                await self.ctx.emit(AgentEvent("text", {"text": f"allowed={outcome.allow}"}))
        else:
            await self.ctx.emit(AgentEvent("text", {"text": f"echo: {text}"}))
        if self.on_usage:
            await self.on_usage(TurnUsage(model="fake-model", input_tokens=10, output_tokens=5, cost_usd=0.01))
        await self.ctx.emit(AgentEvent("status", {"state": "idle"}))

    async def interrupt(self) -> None:
        pass

    async def close(self) -> None:
        pass


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "projects" / "demo"
    ws.mkdir(parents=True)
    return ws


@pytest.fixture
def cfg(workspace: Path) -> Config:
    return Config.model_validate({
        "server": {"permission_timeout_s": 10},
        "workspaces": {"allowed": [str(workspace.parent)]},
        "policy": {
            "always_deny_patterns": [r"rm\s+-rf\s+(/|~)(\s|$)"],
            "high_risk_patterns": [r"git\s+push\s+.*--force"],
        },
        "profiles": {"fake": {"agent": "claude-code", "label": "Fake"}},
    })


@pytest.fixture
def state(tmp_path: Path, cfg: Config, monkeypatch: pytest.MonkeyPatch) -> State:
    monkeypatch.setattr("theyso.sessions.build_adapter", lambda agent, ctx: FakeAdapter(ctx))
    home = tmp_path / "home"
    identity = ServerIdentity.load_or_create(home / "server_key.pem")
    audit = AuditLog(home / "audit.jsonl")
    metrics = Metrics(home / "usage.sqlite")
    return State(
        cfg=cfg, home=home, identity=identity,
        devices=DeviceRegistry(home / "devices.json"),
        pairing=PairingManager(120, 3, identity.public_raw),
        sessions=SessionManager(cfg, Policy(cfg.policy), metrics, audit),
        audit=audit, metrics=metrics, throttle=AuthThrottle(5, 60),
        bind_host="testserver", admin_token="admin-test-token",
    )


class PhoneSim:
    """What the Flutter app does, in Python. Doubles as executable documentation."""

    def __init__(self) -> None:
        self.key = Ed25519PrivateKey.generate()
        self.pub = self.key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.device_id: str | None = None
        self.server_pub: bytes | None = None

    def scan(self, qr: str) -> dict[str, Any]:
        payload = json.loads(b64d(qr.split("d=", 1)[1]))
        self.server_pub = b64d(payload["spk"])
        return payload

    def pair_body(self, payload: dict[str, Any], name: str = "Test phone") -> dict[str, Any]:
        secret = b64d(payload["sec"])
        proof = hmac.new(secret, b"theyso-pair-v1|" + payload["pid"].encode() + b"|" + self.pub,
                         hashlib.sha256).digest()
        return {"pid": payload["pid"], "device_pub": b64u(self.pub), "proof": b64u(proof),
                "name": name, "platform": "android"}

    def handshake(self, ws: Any) -> dict[str, Any]:
        import os

        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        cn = os.urandom(32)
        ws.send_text(json.dumps({"type": "auth.hello", "device_id": self.device_id, "client_nonce": b64u(cn)}))
        ch = json.loads(ws.receive_text())
        assert ch["type"] == "auth.challenge"
        sn = b64d(ch["server_nonce"])
        t = b"|".join([b"theyso-auth-v1", self.device_id.encode(), cn, sn, self.server_pub])
        Ed25519PublicKey.from_public_bytes(self.server_pub).verify(b64d(ch["signature"]), b"server|" + t)
        ws.send_text(json.dumps({"type": "auth.response", "signature": b64u(self.key.sign(b"client|" + t))}))
        return json.loads(ws.receive_text())
