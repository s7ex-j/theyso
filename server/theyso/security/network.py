"""Where the server is allowed to listen, and which requests it accepts.

By default Theyso only binds to loopback or to a Tailscale address
(100.64.0.0/10 or fd7a:115c:a1e0::/48). Binding to 0.0.0.0 or a LAN address
would expose an agent that can run shell commands to everyone on the café
Wi-Fi, so it requires an explicit ``allow_insecure_bind = true``.
"""

from __future__ import annotations

import ipaddress
import shutil
import subprocess  # noqa: S404  # nosec B404 — fixed argv, no shell
import sys
from pathlib import Path

TAILSCALE_V4 = ipaddress.ip_network("100.64.0.0/10")
TAILSCALE_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")


class UnsafeBindError(RuntimeError):
    pass


def _tailscale_binary() -> str | None:
    found = shutil.which("tailscale")
    if found:
        return found
    candidates = {
        "darwin": ["/Applications/Tailscale.app/Contents/MacOS/Tailscale"],
        "win32": [r"C:\Program Files\Tailscale\tailscale.exe"],
    }.get(sys.platform, [])
    return next((c for c in candidates if Path(c).exists()), None)


def detect_tailscale_ipv4() -> str | None:
    binary = _tailscale_binary()
    if not binary:
        return None
    try:
        out = subprocess.run(  # noqa: S603  # nosec B603
            [binary, "ip", "-4"], capture_output=True, text=True, timeout=5, check=True
        ).stdout.strip().splitlines()
    except (subprocess.SubprocessError, OSError):
        return None
    for line in out:
        try:
            if ipaddress.ip_address(line.strip()) in TAILSCALE_V4:
                return line.strip()
        except ValueError:
            continue
    return None


def is_safe_bind(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host == "localhost"
    if ip.is_loopback:
        return True
    if ip.version == 4:
        return ip in TAILSCALE_V4
    return ip in TAILSCALE_V6


def resolve_bind_host(configured: str, allow_insecure: bool) -> str:
    host = configured
    if configured == "auto":
        detected = detect_tailscale_ipv4()
        if not detected:
            raise UnsafeBindError(
                "Could not detect a Tailscale IP. Install Tailscale and run `tailscale up`, "
                "or set server.host = \"127.0.0.1\" for local testing."
            )
        host = detected
    if host in {"0.0.0.0", "::"}:  # noqa: S104  # nosec B104 — this REJECTS all-interfaces binds
        if not allow_insecure:
            raise UnsafeBindError("Refusing to bind to all interfaces. See docs/SECURITY.md.")
        return host
    if not is_safe_bind(host) and not allow_insecure:
        raise UnsafeBindError(
            f"{host} is not loopback or a Tailscale address. "
            "Set allow_insecure_bind = true only if you understand the risk."
        )
    return host


def allowed_host_header(host_header: str | None, bind_host: str, port: int) -> bool:
    """DNS-rebinding protection: the Host header must name this server."""
    if not host_header:
        return False
    host = host_header.strip().lower()
    if host.startswith("["):  # [ipv6]:port
        name = host[1 : host.find("]")]
    else:
        name = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    if name in {bind_host.lower(), "localhost", "127.0.0.1"}:
        return True
    # Tailscale MagicDNS names (pc.tailnet-name.ts.net) are fine: only the tailnet resolves them.
    return name.endswith(".ts.net")


def origin_allowed(origin: str | None) -> bool:
    """Native mobile apps never send an Origin header; browsers always do on
    WebSocket upgrades. Rejecting any Origin blocks cross-site WebSocket
    hijacking from a malicious page open on a tailnet device."""
    return origin is None
