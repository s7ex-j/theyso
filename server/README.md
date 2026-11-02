# theyso-server

The PC side of [Theyso](https://github.com/s7ex-j/theyso): a self-hosted bridge that lets the
Theyso phone app drive Claude Code or OpenCode on this machine, over your Tailscale tailnet.

```bash
pipx install "git+https://github.com/s7ex-j/theyso#subdirectory=server"
theyso init && theyso doctor
theyso serve          # terminal 1
theyso pair           # terminal 2 — scan the QR with the app
```

```
theyso/
├── cli.py                 init · doctor · serve · pair · devices · revoke · panic · audit · usage export
├── app.py                 public API (Tailscale IP) + admin API (127.0.0.1)
├── protocol.py            wire protocol v1 (strict pydantic models)
├── sessions.py            sessions, event buffer + replay, permission flow
├── metrics.py             usage analytics (SQLite) with honest cost basis
├── config.py              TOML config, profiles, env:VAR secrets
├── agents/
│   ├── base.py            adapter interface + normalized events
│   ├── claude_code.py     Claude Agent SDK (can_use_tool + PreToolUse hook)
│   └── opencode.py        opencode serve over HTTP + SSE (experimental)
└── security/
    ├── fs.py              0600/0700 atomic writes
    ├── keys.py            server Ed25519 identity, fingerprints
    ├── pairing.py         QR tickets, HMAC proof, SAS
    ├── devices.py         paired devices (public keys only)
    ├── handshake.py       mutual challenge-response
    ├── ratelimit.py       auth lockout, per-connection budget
    ├── network.py         bind guard, Host/Origin checks
    ├── policy.py          deny / high-risk / ask / allow
    ├── redact.py          secret masking
    └── audit.py           JSONL audit log
```

Development: `pip install -e ".[dev]" && pytest && ruff check . && mypy theyso`.
