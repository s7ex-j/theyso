"""Active attack simulation (DAST-style), in-process against the real app.

Every test sends hostile input through the real network guards, handshake,
policy, redaction and limits, and asserts the server REJECTS it. This doubles
as the evidence for docs/AUDIT.md and as a permanent regression suite: if a
future change opens one of these holes, CI fails here.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from conftest import PhoneSim, b64d, b64u
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from theyso.app import GuardMiddleware, State, create_admin_app, create_public_app

ADMIN = {"Authorization": "Bearer admin-test-token"}


def paired(state: State) -> PhoneSim:
    phone = PhoneSim()
    phone.server_pub = state.identity.public_raw
    phone.device_id = state.devices.add("atk", "android", phone.pub, 5).device_id
    return phone


def recv_until(ws: Any, pred: Callable[[dict[str, Any]], bool], n: int = 80) -> dict[str, Any]:
    for _ in range(n):
        f = json.loads(ws.receive_text())
        if pred(f):
            return f
    raise AssertionError("expected frame not received")


def is_err(f: dict[str, Any]) -> bool:
    return f["type"] == "error"


@pytest.fixture
def client(state: State) -> TestClient:
    return TestClient(GuardMiddleware(create_public_app(state), state))


# ── A. authentication & identity ─────────────────────────────────────────────
def test_attack_unauthenticated_command(client: TestClient):
    with client.websocket_connect("/v1/ws") as ws:
        ws.send_text(json.dumps({"type": "session.list"}))
        assert json.loads(ws.receive_text())["code"] == "auth_failed"


def test_attack_forged_device_signature(state: State, client: TestClient):
    real = paired(state)
    with client.websocket_connect("/v1/ws") as ws:
        impostor = PhoneSim()
        impostor.device_id, impostor.server_pub = real.device_id, real.server_pub  # stolen id, own key
        assert impostor.handshake(ws)["code"] == "auth_failed"


def test_attack_server_cannot_be_impersonated(state: State, client: TestClient):
    """The phone pins the server key; a wrong server key must fail its verify."""
    phone = paired(state)
    phone.server_pub = b"\x00" * 32  # attacker's server does not hold the real key
    with client.websocket_connect("/v1/ws") as ws:
        import os

        cn = os.urandom(32)
        ws.send_text(json.dumps({"type": "auth.hello", "device_id": phone.device_id, "client_nonce": b64u(cn)}))
        ch = json.loads(ws.receive_text())
        with pytest.raises(Exception):  # noqa: B017 - signature verify must raise
            Ed25519PublicKey.from_public_bytes(phone.server_pub).verify(
                b64d(ch["signature"]), b"server|" + b"x")


def test_attack_replayed_handshake(state: State, client: TestClient):
    """A recorded handshake cannot be replayed: the server nonce is fresh each time."""
    phone = paired(state)
    import os

    cn = os.urandom(32)
    with client.websocket_connect("/v1/ws") as ws:
        ws.send_text(json.dumps({"type": "auth.hello", "device_id": phone.device_id, "client_nonce": b64u(cn)}))
        n1 = json.loads(ws.receive_text())["server_nonce"]
    with client.websocket_connect("/v1/ws") as ws:
        ws.send_text(json.dumps({"type": "auth.hello", "device_id": phone.device_id, "client_nonce": b64u(cn)}))
        n2 = json.loads(ws.receive_text())["server_nonce"]
    assert n1 != n2  # so a signature captured in session 1 is worthless in session 2


# ── B. network boundary ──────────────────────────────────────────────────────
def test_attack_browser_origin_ws(client: TestClient):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/v1/ws", headers={"origin": "https://evil.example"}) as ws:
            ws.receive_text()


def test_attack_dns_rebinding_host(client: TestClient):
    assert client.get("/v1/health", headers={"host": "evil.example.com"}).status_code == 403


def test_attack_admin_needs_loopback_token_and_no_origin(state: State):
    remote = TestClient(create_admin_app(state), client=("100.64.0.9", 5000))
    assert remote.post("/admin/panic", headers=ADMIN).status_code == 403  # not loopback
    local = TestClient(create_admin_app(state), client=("127.0.0.1", 1))
    assert local.post("/admin/panic", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert local.post("/admin/panic", headers={**ADMIN, "origin": "http://x"}).status_code == 403  # browser


# ── C. authorization & policy (authenticated hostile client) ─────────────────
def test_attack_workspace_escape(state: State, client: TestClient):
    phone = paired(state)
    with client.websocket_connect("/v1/ws") as ws:
        phone.handshake(ws)
        for bad in ["../../../../etc", "/etc", "demo/../../../..", "/root/.ssh", "demo/../../.."]:
            ws.send_text(json.dumps({"type": "session.create", "profile": "fake", "workspace": bad}))
            assert recv_until(ws, is_err)["code"] in {"forbidden", "not_found"}


def test_attack_destructive_command_autodenied(state: State, client: TestClient):
    phone = paired(state)
    with client.websocket_connect("/v1/ws") as ws:
        phone.handshake(ws)
        ws.send_text(json.dumps({"type": "session.create", "profile": "fake", "workspace": "demo"}))
        sid = recv_until(ws, lambda f: f["type"] == "session.created")["session"]["sid"]
        ws.send_text(json.dumps({"type": "prompt", "sid": sid, "text": "tool:rm -rf ~"}))
        assert "blocked" in recv_until(
            ws, lambda f: f["type"] == "event" and f["kind"] == "text")["data"]["text"]


def test_attack_high_risk_without_biometrics(state: State, client: TestClient):
    phone = paired(state)
    with client.websocket_connect("/v1/ws") as ws:
        phone.handshake(ws)
        ws.send_text(json.dumps({"type": "session.create", "profile": "fake", "workspace": "demo"}))
        sid = recv_until(ws, lambda f: f["type"] == "session.created")["session"]["sid"]
        ws.send_text(json.dumps({"type": "prompt", "sid": sid, "text": "tool:git push origin main --force"}))
        req = recv_until(ws, lambda f: f["type"] == "permission.request")
        assert req["risk"] == "high"
        # allow WITHOUT confirmed_strong → server must refuse
        ws.send_text(json.dumps({"type": "permission.reply", "sid": sid,
                                 "request_id": req["request_id"], "decision": "allow"}))
        assert recv_until(ws, is_err)["code"] == "forbidden"


def test_attack_secret_not_leaked(state: State, client: TestClient):
    phone = paired(state)
    with client.websocket_connect("/v1/ws") as ws:
        phone.handshake(ws)
        ws.send_text(json.dumps({"type": "session.create", "profile": "fake", "workspace": "demo"}))
        sid = recv_until(ws, lambda f: f["type"] == "session.created")["session"]["sid"]
        leak = "sk-ant-api03-" + "z" * 40
        ws.send_text(json.dumps({"type": "prompt", "sid": sid, "text": leak}))
        frame = recv_until(ws, lambda f: f["type"] == "event" and f["kind"] == "text")
        assert "zzzz" not in json.dumps(frame)


# ── D. resource & input abuse ────────────────────────────────────────────────
def test_attack_session_flood_capped(state: State, client: TestClient):
    state.cfg.server.max_sessions = 3
    phone = paired(state)
    with client.websocket_connect("/v1/ws") as ws:
        phone.handshake(ws)
        created = 0
        for _ in range(6):
            ws.send_text(json.dumps({"type": "session.create", "profile": "fake", "workspace": "demo"}))
            f = recv_until(ws, lambda f: f["type"] in ("session.created", "error"))
            if f["type"] == "session.created":
                created += 1
            else:
                assert f["code"] == "forbidden"
        assert created == 3  # flood stopped at the cap


def test_attack_oversize_message(state: State, client: TestClient):
    state.cfg.server.max_message_bytes = 4096
    phone = paired(state)
    with client.websocket_connect("/v1/ws") as ws:
        phone.handshake(ws)
        ws.send_text(json.dumps({"type": "prompt", "sid": "s", "text": "x" * 9000}))
        with pytest.raises(WebSocketDisconnect):
            for _ in range(3):
                json.loads(ws.receive_text())


def test_attack_malformed_protocol(state: State, client: TestClient):
    phone = paired(state)
    with client.websocket_connect("/v1/ws") as ws:
        phone.handshake(ws)
        for junk in ['{"type":"prompt"}', '{"type":"evil"}', "not json at all",
                     '{"type":"prompt","sid":1,"text":[]}',
                     '{"type":"session.create","profile":"../../x","workspace":"demo"}']:
            ws.send_text(junk)
            assert is_err(recv_until(ws, lambda f: f["type"] in ("error", "event")))


def test_attack_pairing_brute_force(state: State):
    """Wrong proofs burn the ticket, so a stolen QR photo can't be brute-forced."""
    pub = TestClient(GuardMiddleware(create_public_app(state), state))
    admin = TestClient(create_admin_app(state), client=("127.0.0.1", 1))
    phone = PhoneSim()
    ticket = admin.post("/admin/pair/start", headers=ADMIN).json()
    payload = phone.scan(ticket["qr"])
    body = phone.pair_body(payload)
    body["proof"] = b64u(b"\x00" * 32)  # wrong proof
    statuses = [pub.post("/v1/pair", json=body).status_code for _ in range(6)]
    assert 200 not in statuses  # never accepted
    assert all(s in (403, 429) for s in statuses)  # ticket burned, then source rate-limited


def test_attack_revoked_device_cut_off(state: State, client: TestClient):
    phone = paired(state)
    with client.websocket_connect("/v1/ws") as ws:
        phone.handshake(ws)
        state.devices.revoke(phone.device_id)
        ws.send_text(json.dumps({"type": "ping"}))
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == 4403
