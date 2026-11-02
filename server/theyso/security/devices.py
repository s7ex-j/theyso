"""Registry of paired devices.

Only public keys are stored. There is no bearer token anywhere: stealing this
file lets an attacker see *which* phones are paired, but not impersonate them.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from theyso.security.fs import write_private_file
from theyso.security.keys import b64u, b64u_decode, fingerprint


@dataclass
class Device:
    device_id: str
    name: str
    platform: str
    public_key: str  # base64url raw Ed25519
    paired_at: float
    last_seen: float | None = None
    last_addr: str | None = None
    revoked: bool = False

    @property
    def fingerprint(self) -> str:
        return fingerprint(b64u_decode(self.public_key))

    def verify(self, signature: bytes, data: bytes) -> bool:
        try:
            Ed25519PublicKey.from_public_bytes(b64u_decode(self.public_key)).verify(signature, data)
            return True
        except (InvalidSignature, ValueError):
            return False


class DeviceRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._devices: dict[str, Device] = {}
        if path.exists():
            raw = json.loads(path.read_text())
            self._devices = {d["device_id"]: Device(**d) for d in raw.get("devices", [])}

    def _save(self) -> None:
        payload = {"version": 1, "devices": [asdict(d) for d in self._devices.values()]}
        write_private_file(self.path, json.dumps(payload, indent=2).encode())

    def active(self) -> list[Device]:
        return [d for d in self._devices.values() if not d.revoked]

    def all(self) -> list[Device]:
        return list(self._devices.values())

    def get_active(self, device_id: str) -> Device | None:
        device = self._devices.get(device_id)
        return device if device and not device.revoked else None

    def add(self, name: str, platform: str, public_key: bytes, max_devices: int) -> Device:
        with self._lock:
            if len(self.active()) >= max_devices:
                raise ValueError(f"Device limit reached ({max_devices}). Revoke one first.")
            pk = b64u(public_key)
            if any(d.public_key == pk and not d.revoked for d in self._devices.values()):
                raise ValueError("This device key is already paired")
            device = Device(
                device_id="dev_" + b64u(secrets.token_bytes(9)),
                name=name,
                platform=platform,
                public_key=pk,
                paired_at=time.time(),
            )
            self._devices[device.device_id] = device
            self._save()
            return device

    def touch(self, device_id: str, addr: str) -> None:
        with self._lock:
            if device := self._devices.get(device_id):
                device.last_seen = time.time()
                device.last_addr = addr
                self._save()

    def revoke(self, device_id: str) -> bool:
        with self._lock:
            device = self._devices.get(device_id)
            if not device or device.revoked:
                return False
            device.revoked = True
            self._save()
            return True

    def revoke_all(self) -> int:
        with self._lock:
            count = 0
            for device in self._devices.values():
                if not device.revoked:
                    device.revoked = True
                    count += 1
            self._save()
            return count
