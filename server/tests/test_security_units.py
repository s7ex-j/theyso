from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from conftest import b64u

from theyso.config import Config, PolicyConfig, Profile
from theyso.security.network import (
    UnsafeBindError,
    allowed_host_header,
    is_safe_bind,
    origin_allowed,
    resolve_bind_host,
)
from theyso.security.pairing import PairingError, PairingManager, TicketState, compute_proof, compute_sas
from theyso.security.policy import Policy
from theyso.security.ratelimit import AuthThrottle
from theyso.security.redact import redact, redact_text

SERVER_PUB = b"S" * 32


# ── pairing ──────────────────────────────────────────────────────────────────
def test_pairing_happy_path():
    pm = PairingManager(120, 3, SERVER_PUB)
    t = pm.create()
    dev = b"D" * 32
    proof = compute_proof(t.secret, t.pid, dev)
    secret = t.secret
    t2 = pm.present(t.pid, b64u(dev), b64u(proof), "Pixel\x1b[31m", "android", "100.1.2.3")
    assert t2.state == TicketState.PENDING
    assert t2.candidate.name == "Pixel[31m"  # control chars stripped
    assert t2.candidate.sas == compute_sas(secret, dev, SERVER_PUB)
    pm.approve(t.pid, "dev_x")
    assert t.state == TicketState.APPROVED and t.secret == b"\x00" * 32


def test_pairing_single_use_and_burn():
    pm = PairingManager(120, 3, SERVER_PUB)
    t = pm.create()
    for _ in range(3):
        with pytest.raises(PairingError):
            pm.present(t.pid, b64u(b"D" * 32), b64u(b"x" * 32), "x", "x", "a")
    assert t.state == TicketState.BURNED
    # even the correct proof is useless now
    with pytest.raises(PairingError):
        pm.present(t.pid, b64u(b"D" * 32), b64u(b"y" * 32), "x", "x", "a")


def test_proof_binds_device_key():
    pm = PairingManager(120, 3, SERVER_PUB)
    t = pm.create()
    proof_for_a = compute_proof(t.secret, t.pid, b"A" * 32)
    with pytest.raises(PairingError):  # attacker swaps in their own key
        pm.present(t.pid, b64u(b"B" * 32), b64u(proof_for_a), "x", "x", "a")


def test_new_ticket_invalidates_old_and_expiry():
    pm = PairingManager(120, 3, SERVER_PUB)
    old = pm.create()
    pm.create()
    assert old.state == TicketState.EXPIRED
    t = pm.create()
    t.expires_at = time.time() - 1
    assert pm.get(t.pid).state == TicketState.EXPIRED


# ── network ──────────────────────────────────────────────────────────────────
def test_bind_guard():
    assert is_safe_bind("127.0.0.1") and is_safe_bind("100.101.102.103") and is_safe_bind("::1")
    assert not is_safe_bind("192.168.1.10") and not is_safe_bind("0.0.0.0")
    with pytest.raises(UnsafeBindError):
        resolve_bind_host("0.0.0.0", allow_insecure=False)
    with pytest.raises(UnsafeBindError):
        resolve_bind_host("192.168.1.10", allow_insecure=False)
    assert resolve_bind_host("100.64.0.5", allow_insecure=False) == "100.64.0.5"


def test_host_and_origin():
    assert allowed_host_header("100.64.0.5:8765", "100.64.0.5", 8765)
    assert allowed_host_header("pc.tail1234.ts.net", "100.64.0.5", 8765)
    assert not allowed_host_header("evil.example.com", "100.64.0.5", 8765)  # DNS rebinding
    assert not allowed_host_header(None, "100.64.0.5", 8765)
    assert origin_allowed(None) and not origin_allowed("https://evil.example.com")


# ── policy ───────────────────────────────────────────────────────────────────
@pytest.fixture
def policy() -> Policy:
    return Policy(Config.model_validate({
        "policy": {"always_deny_patterns": [r"rm\s+-rf\s+(/|~)(\s|$)"],
                   "high_risk_patterns": [r"git\s+push\s+.*--force", r"\bsudo\b"]}
    }).policy)


def test_policy_shell(policy: Policy, tmp_path: Path):
    assert policy.evaluate("Bash", {"command": "rm -rf ~"}, tmp_path).action == "deny"
    assert policy.evaluate("Bash", {"command": "git push origin main --force"}, tmp_path).risk == "high"
    assert policy.evaluate("Bash", {"command": "cat .env"}, tmp_path).risk == "high"
    d = policy.evaluate("Bash", {"command": "pytest -q"}, tmp_path)
    assert d.action == "ask" and d.risk == "medium"


def test_policy_paths(policy: Policy, tmp_path: Path):
    assert policy.evaluate("Read", {"file_path": str(tmp_path / "a.py")}, tmp_path).action == "allow"
    assert policy.evaluate("Read", {"file_path": "~/.ssh/id_ed25519"}, tmp_path).action == "deny"
    assert policy.evaluate("Read", {"file_path": str(tmp_path / ".env")}, tmp_path).action == "deny"
    assert policy.evaluate("Write", {"file_path": "/etc/hosts"}, tmp_path).risk == "high"
    assert policy.evaluate("Edit", {"file_path": str(tmp_path / "x.py")}, tmp_path).risk == "medium"
    if sys.platform == "win32":  # symlinks need admin rights on Windows
        return
    # symlink escaping the workspace is resolved and treated as outside
    link = tmp_path / "link"
    link.symlink_to("/etc")
    assert policy.evaluate("Write", {"file_path": str(link / "passwd")}, tmp_path).risk == "high"


def test_bypass_mode_rejected():
    with pytest.raises(ValueError):
        PolicyConfig(default_permission_mode="bypassPermissions")


# ── redaction ────────────────────────────────────────────────────────────────
def test_redaction():
    text = (
        "key sk-ant-api03-" + "a" * 40 + " and ghp_" + "b" * 36 + "\n"
        "OPENAI_API_KEY=sk-proj-" + "c" * 30 + "\nDATABASE_PASSWORD='hunter22222'\n"
        "-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----"
    )
    out, n = redact_text(text)
    assert "aaaa" not in out and "bbbb" not in out and "cccc" not in out and "hunter" not in out
    assert "BEGIN OPENSSH" not in out and n >= 5
    nested, n2 = redact({"a": ["AKIAABCDEFGHIJKLMNOP"], "b": 3})
    assert nested["a"][0] == "«redacted:aws_key»" and nested["b"] == 3 and n2 == 1


# ── misc ─────────────────────────────────────────────────────────────────────
def test_throttle_lockout():
    t = AuthThrottle(max_failures=3, lockout_s=60)
    assert not t.fail("ip", now=100) and not t.fail("ip", now=101)
    assert t.fail("ip", now=102) and t.is_locked("ip", now=103)
    assert not t.is_locked("ip", now=200)


def test_profile_env_reference(monkeypatch: pytest.MonkeyPatch):
    p = Profile(env={"ANTHROPIC_BASE_URL": "http://127.0.0.1:20128", "ANTHROPIC_AUTH_TOKEN": "env:MY_KEY"})
    with pytest.raises(ValueError):
        p.resolved_env()
    monkeypatch.setenv("MY_KEY", "secret")
    assert p.resolved_env()["ANTHROPIC_AUTH_TOKEN"] == "secret"


def test_default_config_parses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from theyso.config import init_home

    monkeypatch.setenv("THEYSO_HOME", str(tmp_path / "h"))
    path = init_home()
    cfg = Config.load(path)
    assert cfg.policy.always_deny_patterns and "router" in cfg.profiles
    Policy(cfg.policy)  # all default regexes compile
    if sys.platform != "win32":
        assert (path.stat().st_mode & 0o777) == 0o600
