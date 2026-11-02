"""The server's long-term identity key (Ed25519).

The phone pins the public key it receives inside the pairing QR. On every
later connection the server must prove it still holds the private key, so a
machine that hijacks the IP (or a malicious Wi-Fi) cannot impersonate your PC.
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from theyso.security.fs import write_private_file


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64u_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def raw_public(pub: Ed25519PublicKey) -> bytes:
    return bytes(pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))


def fingerprint(pub_raw: bytes) -> str:
    """Short, human-comparable fingerprint, e.g. ``K3QF-9XZ2-...``."""
    digest = hashlib.sha256(pub_raw).digest()[:10]
    text = base64.b32encode(digest).decode().rstrip("=")
    return "-".join(text[i : i + 4] for i in range(0, len(text), 4))


class ServerIdentity:
    def __init__(self, private: Ed25519PrivateKey) -> None:
        self._private = private
        self.public_raw = raw_public(private.public_key())

    @classmethod
    def load_or_create(cls, path: Path) -> ServerIdentity:
        if path.exists():
            key = serialization.load_pem_private_key(path.read_bytes(), password=None)
            if not isinstance(key, Ed25519PrivateKey):
                raise ValueError(f"{path} is not an Ed25519 key")
            return cls(key)
        key = Ed25519PrivateKey.generate()
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        write_private_file(path, pem)
        return cls(key)

    def sign(self, data: bytes) -> bytes:
        return bytes(self._private.sign(data))

    @property
    def public_b64(self) -> str:
        return b64u(self.public_raw)

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.public_raw)
