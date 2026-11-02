"""QR pairing.

Flow (see docs/PAIRING.md for the diagram):

1. ``theyso pair`` asks the running server for a ticket. The ticket holds a
   random 256-bit secret and expires in ``pairing_ttl_s`` (default 120 s).
2. The QR encodes: server URL, ticket id, secret, server public key.
3. The phone generates its own Ed25519 key pair and POSTs
   ``{pid, device_pub, name, proof}`` where
   ``proof = HMAC-SHA256(secret, "theyso-pair-v1" | pid | device_pub)``.
   The secret itself never travels over the network, and the proof binds it to
   that specific device key — nobody can swap in another key in transit.
4. Both screens show a 6-digit Short Authentication String (SAS) derived from
   the secret and both public keys. The human on the PC compares them and
   approves. A person who merely photographed the QR cannot pass this step
   without the PC owner noticing an extra request with a different code.
5. Tickets are single-use and are burned after too many bad proofs.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from enum import StrEnum

from theyso.security.keys import b64u, b64u_decode, fingerprint

PAIR_CONTEXT = b"theyso-pair-v1"
SAS_CONTEXT = b"theyso-sas-v1"


class TicketState(StrEnum):
    WAITING = "waiting"  # QR shown, no phone yet
    PENDING = "pending"  # a phone presented a valid proof, waiting for the human
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    BURNED = "burned"  # too many bad attempts


@dataclass
class PairingCandidate:
    device_pub: bytes
    name: str
    platform: str
    sas: str
    remote_addr: str

    @property
    def device_fingerprint(self) -> str:
        return fingerprint(self.device_pub)


@dataclass
class PairingTicket:
    pid: str
    secret: bytes
    expires_at: float
    state: TicketState = TicketState.WAITING
    attempts: int = 0
    candidate: PairingCandidate | None = None
    device_id: str | None = None
    decided: asyncio.Event = field(default_factory=asyncio.Event)
    candidate_arrived: asyncio.Event = field(default_factory=asyncio.Event)

    def expired(self, now: float | None = None) -> bool:
        return (now or time.time()) >= self.expires_at


def compute_proof(secret: bytes, pid: str, device_pub: bytes) -> bytes:
    return hmac.new(secret, PAIR_CONTEXT + b"|" + pid.encode() + b"|" + device_pub, hashlib.sha256).digest()


def compute_sas(secret: bytes, device_pub: bytes, server_pub: bytes) -> str:
    mac = hmac.new(secret, SAS_CONTEXT + b"|" + device_pub + b"|" + server_pub, hashlib.sha256).digest()
    return f"{int.from_bytes(mac[:4], 'big') % 1_000_000:06d}"


def qr_payload(url: str, ticket: PairingTicket, server_pub_b64: str, server_name: str) -> str:
    """The string encoded in the QR. A custom scheme so a normal camera app
    does not try to open it in a browser."""
    body = {
        "v": 1,
        "url": url,
        "pid": ticket.pid,
        "sec": b64u(ticket.secret),
        "spk": server_pub_b64,
        "name": server_name,
        "exp": int(ticket.expires_at),
    }
    return "theyso://pair?d=" + b64u(json.dumps(body, separators=(",", ":")).encode())


class PairingError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class PairingManager:
    def __init__(self, ttl_s: int, max_attempts: int, server_pub: bytes) -> None:
        self.ttl_s = ttl_s
        self.max_attempts = max_attempts
        self.server_pub = server_pub
        self._tickets: dict[str, PairingTicket] = {}

    def create(self) -> PairingTicket:
        self._gc()
        # Only one live ticket at a time: opening a new QR invalidates the old one.
        for t in self._tickets.values():
            if t.state in (TicketState.WAITING, TicketState.PENDING):
                self._finish(t, TicketState.EXPIRED)
        ticket = PairingTicket(
            pid=b64u(secrets.token_bytes(9)),
            secret=secrets.token_bytes(32),
            expires_at=time.time() + self.ttl_s,
        )
        self._tickets[ticket.pid] = ticket
        return ticket

    def get(self, pid: str) -> PairingTicket | None:
        ticket = self._tickets.get(pid)
        if ticket and ticket.expired() and ticket.state in (TicketState.WAITING, TicketState.PENDING):
            self._finish(ticket, TicketState.EXPIRED)
        return ticket

    def present(
        self, pid: str, device_pub_b64: str, proof_b64: str, name: str, platform: str, remote_addr: str
    ) -> PairingTicket:
        """Called when a phone POSTs to /v1/pair. Raises PairingError on any problem.

        Error messages are deliberately generic to avoid acting as an oracle.
        """
        ticket = self.get(pid)
        if ticket is None or ticket.state != TicketState.WAITING:
            raise PairingError("invalid_ticket", "Pairing code is invalid or expired")
        try:
            device_pub = b64u_decode(device_pub_b64)
            proof = b64u_decode(proof_b64)
        except (ValueError, TypeError) as exc:
            raise PairingError("bad_request", "Malformed pairing request") from exc
        if len(device_pub) != 32:
            raise PairingError("bad_request", "Malformed pairing request")

        expected = compute_proof(ticket.secret, pid, device_pub)
        if not hmac.compare_digest(expected, proof):
            ticket.attempts += 1
            if ticket.attempts >= self.max_attempts:
                self._finish(ticket, TicketState.BURNED)
            raise PairingError("invalid_ticket", "Pairing code is invalid or expired")

        ticket.candidate = PairingCandidate(
            device_pub=device_pub,
            name=_clean_name(name),
            platform=_clean_name(platform)[:20],
            sas=compute_sas(ticket.secret, device_pub, self.server_pub),
            remote_addr=remote_addr,
        )
        ticket.state = TicketState.PENDING
        ticket.candidate_arrived.set()
        return ticket

    def approve(self, pid: str, device_id: str) -> PairingTicket:
        ticket = self.get(pid)
        if ticket is None or ticket.state != TicketState.PENDING:
            raise PairingError("invalid_state", "Nothing to approve")
        ticket.device_id = device_id
        self._finish(ticket, TicketState.APPROVED)
        return ticket

    def reject(self, pid: str) -> None:
        ticket = self.get(pid)
        if ticket is not None and ticket.state in (TicketState.WAITING, TicketState.PENDING):
            self._finish(ticket, TicketState.REJECTED)

    def _finish(self, ticket: PairingTicket, state: TicketState) -> None:
        ticket.state = state
        ticket.secret = b"\x00" * 32  # the secret is never useful again
        ticket.decided.set()
        ticket.candidate_arrived.set()

    def _gc(self) -> None:
        cutoff = time.time() - 600
        for pid in [p for p, t in self._tickets.items() if t.expires_at < cutoff]:
            del self._tickets[pid]


def _clean_name(name: str) -> str:
    """Device names are shown in a terminal: strip control chars (no ANSI injection)."""
    return "".join(ch for ch in name if ch.isprintable())[:60] or "unnamed device"
