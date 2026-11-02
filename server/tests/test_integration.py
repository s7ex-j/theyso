"""End-to-end: QR pairing over HTTP, then authenticated WebSocket sessions."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from conftest import PhoneSim, b64d
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from theyso.app import GuardMiddleware, State, create_admin_app, create_public_app
from theyso.security.pairing import compute_sas

ADMIN = {"Authorization": "Bearer admin-test-token"}


# ── pairing ──────────────────────────────────────────────────────────────────
async def test_qr_pairing_flow(state: State):
    public = httpx.AsyncClient(transport=httpx.ASGITransport(GuardMiddleware(create_public_app(state), state)),
                               base_url="http://testserver")
    admin = httpx.AsyncClient(transport=httpx.ASGITransport(create_admin_app(state), client=("127.0.0.1", 5000)),
                              base_url="http://127.0.0.1")
    phone = PhoneSim()

    ticket = (await admin.post("/admin/pair/start", headers=ADMIN)).json()
    payload = phone.scan(ticket["qr"])
    assert payload["spk"] == state.identity.public_b64 and "sec" in payload

    pair_task = asyncio.create_task(public.post("/v1/pair", json=phone.pair_body(payload)))
    waited = (await admin.get(f"/admin/pair/{ticket['pid']}/wait", headers=ADMIN)).json()
    assert waited["state"] == "pending"
    # Phone computes the same 6-digit code on its own screen
    assert waited["candidate"]["sas"] == compute_sas(b64d(payload["sec"]), phone.pub, phone.server_pub)

    approved = (await admin.post(f"/admin/pair/{ticket['pid']}/approve", headers=ADMIN)).json()
    resp = (await pair_task).json()
    assert resp["status"] == "approved" and resp["device_id"] == approved["device_id"]
    Ed25519PublicKey.from_public_bytes(phone.server_pub).verify(
        b64d(resp["signature"]), b"theyso-paired-v1|" + resp["device_id"].encode() + b"|" + phone.pub)

    # The QR is single-use
    again = await public.post("/v1/pair", json=phone.pair_body(payload, "second"))
    assert again.status_code == 403


async def test_admin_requires_token_and_loopback(state: State):
    admin_remote = httpx.AsyncClient(
        transport=httpx.ASGITransport(create_admin_app(state), client=("100.64.0.9", 5000)),
        base_url="http://127.0.0.1")
    assert (await admin_remote.post("/admin/pair/start", headers=ADMIN)).status_code == 403
    admin = httpx.AsyncClient(transport=httpx.ASGITransport(create_admin_app(state), client=("127.0.0.1", 1)),
                              base_url="http://127.0.0.1")
    assert (await admin.post("/admin/pair/start", headers={"Authorization": "Bearer nope"})).status_code == 401


# ── websocket ────────────────────────────────────────────────────────────────
def paired_phone(state: State) -> PhoneSim:
    phone = PhoneSim()
    phone.server_pub = state.identity.public_raw
    phone.device_id = state.devices.add("Test phone", "android", phone.pub, 5).device_id
    return phone


def recv_until(ws: Any, pred: Callable[[dict[str, Any]], bool], limit: int = 50) -> dict[str, Any]:
    for _ in range(limit):
        frame = json.loads(ws.receive_text())
        if pred(frame):
            return frame
    raise AssertionError("expected frame not received")


def text_event(contains: str) -> Callable[[dict[str, Any]], bool]:
    return lambda f: f.get("type") == "event" and f.get("kind") == "text" and contains in f["data"]["text"]


def test_full_session(state: State):
    phone = paired_phone(state)
    app = GuardMiddleware(create_public_app(state), state)
    with TestClient(app) as client, client.websocket_connect("/v1/ws") as ws:
        ok = phone.handshake(ws)
        assert ok["type"] == "auth.ok" and ok["profiles"][0]["name"] == "fake"
        assert ok["workspaces"][0]["projects"] == ["demo"]

        ws.send_text(json.dumps({"type": "session.create", "profile": "fake", "workspace": "demo"}))
        sid = recv_until(ws, lambda f: f["type"] == "session.created")["session"]["sid"]

        ws.send_text(json.dumps({"type": "prompt", "sid": sid, "text": "hola"}))
        recv_until(ws, text_event("echo: hola"))

        # high-risk command → needs biometric confirmation
        ws.send_text(json.dumps({"type": "prompt", "sid": sid, "text": "tool:git push origin main --force"}))
        req = recv_until(ws, lambda f: f["type"] == "permission.request")
        assert req["risk"] == "high" and req["requires_strong_auth"]
        ws.send_text(json.dumps({"type": "permission.reply", "sid": sid, "request_id": req["request_id"],
                                 "decision": "allow"}))
        err = recv_until(ws, lambda f: f["type"] == "error")
        assert err["code"] == "forbidden" and err["sid"] == sid  # routed to the right chat
        ws.send_text(json.dumps({"type": "permission.reply", "sid": sid, "request_id": req["request_id"],
                                 "decision": "allow", "confirmed_strong": True}))
        recv_until(ws, text_event("allowed=True"))

        # always-deny never even reaches the phone
        ws.send_text(json.dumps({"type": "prompt", "sid": sid, "text": "tool:rm -rf ~"}))
        recv_until(ws, text_event("blocked"))

        # secrets are masked on the way out
        ws.send_text(json.dumps({"type": "prompt", "sid": sid, "text": "token ghp_" + "x" * 36}))
        frame = recv_until(ws, text_event("echo: token"))
        assert "xxxx" not in frame["data"]["text"] and frame["data"]["redactions"] == 1

        ws.send_text(json.dumps({"type": "usage.query", "days": 7}))
        usage = recv_until(ws, lambda f: f["type"] == "usage.result")
        assert usage["by_model"][0]["turns"] == 4
        last_seq = frame["seq"]

    # Reconnect and replay only what was missed
    with TestClient(app) as client, client.websocket_connect("/v1/ws") as ws:
        phone.handshake(ws)
        ws.send_text(json.dumps({"type": "session.attach", "sid": sid, "after_seq": last_seq - 1}))
        recv_until(ws, lambda f: f["type"] == "session.attached")
        replay = json.loads(ws.receive_text())
        assert replay["seq"] == last_seq


def test_bad_signature_and_unknown_device(state: State):
    phone = paired_phone(state)
    impostor = PhoneSim()
    impostor.device_id, impostor.server_pub = phone.device_id, phone.server_pub  # stolen id, wrong key
    app = GuardMiddleware(create_public_app(state), state)
    with TestClient(app) as client, client.websocket_connect("/v1/ws") as ws:
        reply = impostor.handshake(ws)
        assert reply["type"] == "error" and reply["code"] == "auth_failed"
    ghost = PhoneSim()
    ghost.device_id, ghost.server_pub = "dev_doesnotexist", phone.server_pub
    with TestClient(app) as client, client.websocket_connect("/v1/ws") as ws:
        assert ghost.handshake(ws)["code"] == "auth_failed"  # still got a challenge first


def test_must_authenticate_first(state: State):
    app = GuardMiddleware(create_public_app(state), state)
    with TestClient(app) as client, client.websocket_connect("/v1/ws") as ws:
        ws.send_text(json.dumps({"type": "session.list"}))
        assert json.loads(ws.receive_text())["code"] == "auth_failed"


def test_browser_origin_rejected(state: State):
    app = GuardMiddleware(create_public_app(state), state)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/v1/ws", headers={"origin": "https://evil.example"}) as ws:
                ws.receive_text()
        assert client.get("/v1/health", headers={"host": "evil.example.com"}).status_code == 403


def test_workspace_escape_rejected(state: State):
    phone = paired_phone(state)
    app = GuardMiddleware(create_public_app(state), state)
    with TestClient(app) as client, client.websocket_connect("/v1/ws") as ws:
        phone.handshake(ws)
        for bad in ("../../", "/etc", "demo/../../.."):
            ws.send_text(json.dumps({"type": "session.create", "profile": "fake", "workspace": bad}))
            assert recv_until(ws, lambda f: f["type"] == "error")["code"] in {"forbidden", "not_found"}


def test_revoked_device_is_cut_off(state: State):
    phone = paired_phone(state)
    app = GuardMiddleware(create_public_app(state), state)
    with TestClient(app) as client, client.websocket_connect("/v1/ws") as ws:
        phone.handshake(ws)
        state.devices.revoke(phone.device_id)
        ws.send_text(json.dumps({"type": "ping"}))
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == 4403
