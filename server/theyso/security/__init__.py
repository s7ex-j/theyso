"""Security primitives. Each module is small on purpose so it can be audited alone.

- fs         private files and directories (0600 / 0700)
- keys       the server's long-term Ed25519 identity
- pairing    one-time QR tickets + short authentication string (SAS)
- devices    registry of paired phones (public keys only, never secrets)
- handshake  mutual challenge-response authentication on every connection
- ratelimit  auth lockout and per-connection message budget
- network    bind-address guard (loopback / Tailscale only) and Host/Origin checks
- policy     tool-permission policy: deny / high-risk / auto-allow / ask
- redact     masks credentials before anything is sent to the phone
- audit      append-only JSONL audit log
"""
