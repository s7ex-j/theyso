"""Mutual challenge-response authentication, run on every WebSocket connection.

    phone                                   server
      │ auth.hello {device_id, client_nonce}  │
      │──────────────────────────────────────▶│  look up device (unknown → generic error)
      │                                       │
      │ auth.challenge {server_nonce, sig_s}  │  sig_s = Sign_server("server" | T)
      │◀──────────────────────────────────────│
      │ verify sig_s with the PINNED key      │
      │ from the QR — abort if it fails       │
      │                                       │
      │ auth.response {sig_c}                 │  sig_c = Sign_device("client" | T)
      │──────────────────────────────────────▶│  verify with stored device key
      │ auth.ok                               │
      │◀──────────────────────────────────────│

    T = "theyso-auth-v1" | device_id | client_nonce | server_nonce | server_pub

Both nonces are 32 random bytes, so a recorded handshake can never be replayed
and each side proves possession of its private key. Role labels ("server",
"client") prevent reflecting one side's signature back as the other's.
"""

from __future__ import annotations

import secrets

AUTH_CONTEXT = b"theyso-auth-v1"
NONCE_BYTES = 32


def new_nonce() -> bytes:
    return secrets.token_bytes(NONCE_BYTES)


def transcript(device_id: str, client_nonce: bytes, server_nonce: bytes, server_pub: bytes) -> bytes:
    if len(client_nonce) != NONCE_BYTES or len(server_nonce) != NONCE_BYTES:
        raise ValueError("bad nonce length")
    return b"|".join([AUTH_CONTEXT, device_id.encode(), client_nonce, server_nonce, server_pub])


def server_signed_part(t: bytes) -> bytes:
    return b"server|" + t


def client_signed_part(t: bytes) -> bytes:
    return b"client|" + t
