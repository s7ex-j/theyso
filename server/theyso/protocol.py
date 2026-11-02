"""Wire protocol v1 — JSON text frames over a WebSocket.

Every frame is an object with a ``type``. Client frames are validated strictly
(unknown types and unknown fields are rejected). See docs/PROTOCOL.md.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

ID = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")]
B64 = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_\-]+$")]


class _Msg(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: ID | None = None  # optional client correlation id, echoed in replies


# ── handshake ────────────────────────────────────────────────────────────────
class AuthHello(_Msg):
    type: Literal["auth.hello"]
    v: Literal[1] = 1
    device_id: ID
    client_nonce: B64


class AuthResponse(_Msg):
    type: Literal["auth.response"]
    signature: B64


# ── sessions ─────────────────────────────────────────────────────────────────
class SessionList(_Msg):
    type: Literal["session.list"]


class SessionCreate(_Msg):
    type: Literal["session.create"]
    profile: Annotated[str, Field(max_length=64)]
    workspace: Annotated[str, Field(max_length=1024)]
    title: Annotated[str, Field(max_length=120)] | None = None
    resume_agent_session: Annotated[str, Field(max_length=128)] | None = None


class SessionAttach(_Msg):
    type: Literal["session.attach"]
    sid: ID
    after_seq: int = Field(0, ge=0)  # replay events the phone missed while offline


class SessionDetach(_Msg):
    type: Literal["session.detach"]
    sid: ID


class SessionClose(_Msg):
    type: Literal["session.close"]
    sid: ID


class Prompt(_Msg):
    type: Literal["prompt"]
    sid: ID
    text: Annotated[str, Field(min_length=1, max_length=100_000)]


class Interrupt(_Msg):
    type: Literal["interrupt"]
    sid: ID


class SetModel(_Msg):
    type: Literal["model.set"]
    sid: ID
    model: Annotated[str, Field(max_length=128)] | None


class PermissionReply(_Msg):
    type: Literal["permission.reply"]
    sid: ID
    request_id: ID
    decision: Literal["allow", "deny"]
    message: Annotated[str, Field(max_length=2000)] | None = None
    # Required for high-risk requests: the app sets it only after a successful
    # biometric / device-credential check. The server enforces its presence.
    confirmed_strong: bool = False


class UsageQuery(_Msg):
    type: Literal["usage.query"]
    days: int = Field(7, ge=1, le=365)


class Panic(_Msg):
    """Kill switch: interrupt and close every session immediately."""

    type: Literal["panic"]


class Ping(_Msg):
    type: Literal["ping"]


ClientMessage = Annotated[
    AuthHello
    | AuthResponse
    | SessionList
    | SessionCreate
    | SessionAttach
    | SessionDetach
    | SessionClose
    | Prompt
    | Interrupt
    | SetModel
    | PermissionReply
    | UsageQuery
    | Panic
    | Ping,
    Field(discriminator="type"),
]

client_adapter: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)


def parse_client(raw: str | bytes) -> ClientMessage:
    return client_adapter.validate_json(raw)


# ── server → client helpers ──────────────────────────────────────────────────
def out(type_: str, **fields: Any) -> dict[str, Any]:
    return {"type": type_, **{k: v for k, v in fields.items() if v is not None}}


def error(code: str, message: str, ref: str | None = None, sid: str | None = None) -> dict[str, Any]:
    return out("error", code=code, message=message, ref=ref, sid=sid)


# Error codes the app understands
E_AUTH = "auth_failed"
E_LOCKED = "locked_out"
E_RATE = "rate_limited"
E_BAD = "bad_request"
E_NOT_FOUND = "not_found"
E_FORBIDDEN = "forbidden"
E_AGENT = "agent_error"
E_BUDGET = "budget_exceeded"
