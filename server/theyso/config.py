"""Configuration: a single TOML file in the Theyso home directory.

Secrets never live in the config file. Profile env values may reference the
process environment with the ``env:NAME`` syntax, resolved at session start.
"""

from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from theyso.security.fs import ensure_private_dir, write_private_file


def theyso_home() -> Path:
    """Directory holding config, keys, device registry, audit log and metrics."""
    if env := os.environ.get("THEYSO_HOME"):
        return Path(env).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home())) / "theyso"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "theyso"


class ServerConfig(BaseModel):
    host: str = "auto"  # "auto" → this machine's Tailscale IPv4
    port: int = Field(8765, ge=1024, le=65535)
    admin_port: int = Field(8766, ge=1024, le=65535)  # always bound to 127.0.0.1
    allow_insecure_bind: bool = False
    # URL put in the QR. Default: ws://<bind-ip>:<port>. Set it to a MagicDNS name
    # or to the wss:// URL given by `tailscale serve` to add TLS on top of WireGuard.
    public_url: str | None = None
    max_message_bytes: int = Field(256 * 1024, ge=1024)
    permission_timeout_s: int = Field(600, ge=10)
    event_buffer: int = Field(1000, ge=100)
    idle_session_timeout_s: int = Field(6 * 3600, ge=60)
    max_sessions: int = Field(10, ge=1)  # cap concurrent agent processes: each one costs real RAM
    # "sessions" = don't let the PC sleep while an agent session is open (default)
    keep_awake: Literal["sessions", "always", "never"] = "sessions"
    keep_awake_ac_only: bool = True  # only while plugged in
    stream_partial: bool = True  # show replies while they are being written


class SecurityConfig(BaseModel):
    pairing_ttl_s: int = Field(120, ge=30, le=900)
    pairing_max_attempts: int = Field(5, ge=1, le=20)
    auth_timeout_s: int = Field(10, ge=3, le=60)
    max_auth_failures: int = Field(5, ge=1)
    lockout_s: int = Field(300, ge=10)
    max_devices: int = Field(5, ge=1)
    redact_secrets: bool = True
    audit_prompts: Literal["full", "hash", "none"] = "hash"
    messages_per_minute: int = Field(120, ge=10)


class WorkspacesConfig(BaseModel):
    allowed: list[str] = Field(default_factory=list)

    def resolved(self) -> list[Path]:
        return [Path(p).expanduser().resolve() for p in self.allowed]


class PolicyConfig(BaseModel):
    default_permission_mode: Literal["default", "acceptEdits", "plan"] = "default"
    auto_allow_tools: list[str] = Field(default_factory=lambda: ["Read", "Glob", "Grep", "LS"])
    always_deny_patterns: list[str] = Field(default_factory=list)
    high_risk_patterns: list[str] = Field(default_factory=list)
    protected_paths: list[str] = Field(
        default_factory=lambda: ["~/.ssh", "~/.aws", "~/.gnupg", "~/.config/theyso", "**/.env"]
    )

    @field_validator("default_permission_mode", mode="before")
    @classmethod
    def _no_bypass(cls, v: str) -> str:
        if v in {"bypassPermissions", "dontAsk", "auto"}:
            raise ValueError(
                "Theyso refuses to run agents without permission prompts. "
                "Use 'default', 'acceptEdits' or 'plan'."
            )
        return v


class Profile(BaseModel):
    """A named way to run an agent: which CLI, which model, which provider env."""

    agent: Literal["claude-code", "opencode"] = "claude-code"
    model: str | None = None
    fallback_model: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    label: str | None = None
    # Optional price table (USD per 1M tokens) for providers that don't report cost.
    price_input_per_mtok: float | None = None
    price_output_per_mtok: float | None = None
    daily_budget_usd: float | None = None

    def resolved_env(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for key, value in self.env.items():
            if value.startswith("env:"):
                name = value[4:]
                resolved = os.environ.get(name)
                if resolved is None:
                    raise ValueError(f"Profile needs environment variable {name} but it is not set")
                out[key] = resolved
            else:
                out[key] = value
        return out


class Config(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    workspaces: WorkspacesConfig = Field(default_factory=WorkspacesConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    profiles: dict[str, Profile] = Field(default_factory=lambda: {"default": Profile()})

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        path = path or theyso_home() / "config.toml"
        if not path.exists():
            raise FileNotFoundError(f"No config at {path}. Run `theyso init` first.")
        with path.open("rb") as fh:
            return cls.model_validate(tomllib.load(fh))


DEFAULT_CONFIG = """\
# Theyso configuration — https://github.com/s7ex-j/theyso
# Secrets do NOT go here. Use env:VAR_NAME to read them from the environment.

[server]
host = "auto"              # "auto" = your Tailscale IPv4 (100.x.y.z). Never 0.0.0.0.
port = 8765
admin_port = 8766          # local admin API, always 127.0.0.1
allow_insecure_bind = false
permission_timeout_s = 600 # unanswered permission requests are DENIED after this
max_sessions = 10          # most agent RAM you'll allow at once (each session is a `claude`/opencode process)
keep_awake = "sessions"    # no sleep while an agent session is open: "sessions" | "always" | "never"
keep_awake_ac_only = true  # …and only while the charger is connected
stream_partial = true      # show replies while they are being written

[security]
pairing_ttl_s = 120        # QR codes expire after 2 minutes
pairing_max_attempts = 5
max_devices = 5
redact_secrets = true      # mask API keys/tokens before they reach the phone
audit_prompts = "hash"     # "full" | "hash" | "none"

[workspaces]
# The phone can only open sessions inside these folders.
allowed = ["~/proyectos"]

[policy]
default_permission_mode = "default"   # bypassPermissions is rejected on purpose
auto_allow_tools = ["Read", "Glob", "Grep", "LS"]
always_deny_patterns = [
  'rm\\s+-rf\\s+(/|~|\\$HOME)(\\s|$)',
  'mkfs\\.',
  ':\\(\\)\\s*\\{\\s*:\\|:&\\s*\\};:',
  'dd\\s+if=.*\\s+of=/dev/',
]
high_risk_patterns = [
  'git\\s+push\\s+.*--force',
  'curl\\s+.*\\|\\s*(ba)?sh',
  'wget\\s+.*\\|\\s*(ba)?sh',
  '\\bsudo\\b',
  'chmod\\s+-R\\s+777',
  'npm\\s+publish',
]

# ── Profiles: how to run each agent ──────────────────────────────────────────
[profiles.claude]
label = "Claude Code (cuenta oficial / API key)"
agent = "claude-code"

[profiles.router]
label = "Claude Code vía router local (9Router, LiteLLM, etc.)"
agent = "claude-code"
model = "your-router-model-id"
[profiles.router.env]
ANTHROPIC_BASE_URL = "http://127.0.0.1:20128"
ANTHROPIC_AUTH_TOKEN = "env:ROUTER_API_KEY"

[profiles.openrouter]
label = "Claude Code vía OpenRouter"
agent = "claude-code"
model = "anthropic/claude-sonnet-4.5"
[profiles.openrouter.env]
ANTHROPIC_BASE_URL = "https://openrouter.ai/api"
ANTHROPIC_AUTH_TOKEN = "env:OPENROUTER_API_KEY"

[profiles.opencode]
label = "OpenCode (cualquier proveedor configurado en opencode)"
agent = "opencode"
"""


def init_home(force: bool = False) -> Path:
    home = theyso_home()
    ensure_private_dir(home)
    cfg = home / "config.toml"
    if force or not cfg.exists():
        write_private_file(cfg, DEFAULT_CONFIG.encode())
    return cfg
