"""`theyso` command line.

    theyso init                 create config + server identity key
    theyso doctor               check Tailscale, agents, permissions
    theyso serve                run the bridge
    theyso pair                 show a QR and approve a phone (server must be running)
    theyso devices              list paired phones
    theyso revoke <id>|--all    unpair phones (live connections are cut immediately)
    theyso panic                stop every agent session now
    theyso service install      start Theyso automatically at log-on (systemd / launchd / Task Scheduler)
    theyso audit [-n 50]        show the audit log
    theyso usage export <dir>   dump usage tables to CSV (for Power BI / pandas)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from theyso import __version__

EXIT_OK, EXIT_ERR = 0, 1


def _home() -> Path:
    from theyso.config import theyso_home

    return theyso_home()


def _admin(method: str, path: str, **kwargs: Any) -> Any:
    import httpx

    from theyso.config import Config

    home = _home()
    token_file = home / "admin.token"
    if not token_file.exists():
        sys.exit("Server is not running (no admin token). Start it with `theyso serve`.")
    cfg = Config.load()
    url = f"http://127.0.0.1:{cfg.server.admin_port}{path}"
    headers = {"Authorization": f"Bearer {token_file.read_text().strip()}"}
    try:
        resp = httpx.request(method, url, headers=headers, timeout=40, **kwargs)
    except httpx.ConnectError:
        sys.exit("Cannot reach the Theyso server. Is `theyso serve` running?")
    if resp.status_code >= 400:
        sys.exit(f"Server answered {resp.status_code}: {resp.text}")
    return resp.json()


# ── commands ─────────────────────────────────────────────────────────────────
def cmd_init(args: argparse.Namespace) -> int:
    from theyso.config import init_home
    from theyso.security.keys import ServerIdentity
    from theyso.service import ensure_secrets_file

    cfg_path = init_home(force=args.force)
    identity = ServerIdentity.load_or_create(cfg_path.parent / "server_key.pem")
    secrets_path = ensure_secrets_file(cfg_path.parent)
    print(f"Config:              {cfg_path}")
    print(f"API keys go in:      {secrets_path}")
    print(f"Server fingerprint:  {identity.fingerprint}")
    print("\nNext: edit [workspaces].allowed in the config, then run `theyso doctor`.")
    return EXIT_OK


def cmd_doctor(_: argparse.Namespace) -> int:
    from theyso.config import Config
    from theyso.security.fs import check_private
    from theyso.security.network import detect_tailscale_ipv4

    ok = True

    def line(good: bool, text: str) -> None:
        nonlocal ok
        ok &= good
        print(("  ✔ " if good else "  ✘ ") + text)

    from theyso.power import on_ac_power
    from theyso.service import load_secrets_env

    home = _home()
    print(f"Theyso {__version__} — home {home}")
    for warning in load_secrets_env(home / "secrets.env"):
        line(False, warning)
    try:
        cfg = Config.load()
        line(True, "config.toml is valid")
    except Exception as exc:
        line(False, f"config: {exc}")
        return EXIT_ERR
    ts = detect_tailscale_ipv4()
    line(ts is not None, f"Tailscale IP: {ts or 'not found (install Tailscale and run `tailscale up`)'}")
    agents = {p.agent for p in cfg.profiles.values()}
    if "claude-code" in agents:
        line(shutil.which("claude") is not None, "`claude` CLI on PATH")
    if "opencode" in agents:
        line(shutil.which("opencode") is not None, "`opencode` CLI on PATH")
    for ws in cfg.workspaces.resolved():
        line(ws.is_dir(), f"workspace {ws}")
    if not cfg.workspaces.allowed:
        line(False, "no workspaces configured")
    for name, profile in cfg.profiles.items():
        try:
            profile.resolved_env()
            line(True, f"profile '{name}' env resolved")
        except ValueError as exc:
            line(False, f"profile '{name}': {exc}")
    line(True, f"keep-awake: {cfg.server.keep_awake} (on charger now: {'yes' if on_ac_power() else 'no'})")
    for f in ("server_key.pem", "devices.json", "config.toml", "audit.jsonl", "secrets.env"):
        for warning in check_private(home / f):
            line(False, warning)
    print("\nAll good." if ok else "\nFix the items marked ✘.")
    return EXIT_OK if ok else EXIT_ERR


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from theyso.app import GuardMiddleware, State, create_admin_app, create_public_app, new_admin_token
    from theyso.config import Config
    from theyso.metrics import Metrics
    from theyso.power import KeepAwake
    from theyso.security.audit import AuditLog
    from theyso.security.devices import DeviceRegistry
    from theyso.security.fs import write_private_file
    from theyso.security.keys import ServerIdentity
    from theyso.security.network import UnsafeBindError, resolve_bind_host
    from theyso.security.pairing import PairingManager
    from theyso.security.policy import Policy
    from theyso.security.ratelimit import AuthThrottle
    from theyso.service import load_secrets_env
    from theyso.sessions import SessionManager

    home = _home()
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if args.log_file:
        from logging.handlers import RotatingFileHandler

        log_path = home / "theyso.log" if args.log_file == "auto" else Path(args.log_file)
        if not log_path.exists():
            write_private_file(log_path, b"")  # 0600: logs mention devices and paths
        handlers = [RotatingFileHandler(log_path, maxBytes=5_000_000, backupCount=3, encoding="utf-8")]
    logging.basicConfig(level=logging.INFO if not args.verbose else logging.DEBUG,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers)
    for warning in load_secrets_env(home / "secrets.env"):
        logging.warning(warning)
    cfg = Config.load()
    keep_awake = KeepAwake(cfg.server.keep_awake, cfg.server.keep_awake_ac_only)
    try:
        bind = resolve_bind_host(args.host or cfg.server.host, cfg.server.allow_insecure_bind)
    except UnsafeBindError as exc:
        print(f"✘ {exc}", file=sys.stderr)
        return EXIT_ERR

    identity = ServerIdentity.load_or_create(home / "server_key.pem")
    audit = AuditLog(home / "audit.jsonl", cfg.security.audit_prompts)
    metrics = Metrics(home / "usage.sqlite")
    policy = Policy(cfg.policy)
    admin_token = new_admin_token()  # rotated on every start
    write_private_file(home / "admin.token", admin_token.encode())

    async def main() -> None:
        state = State(
            cfg=cfg, home=home, identity=identity,
            devices=DeviceRegistry(home / "devices.json"),
            pairing=PairingManager(cfg.security.pairing_ttl_s, cfg.security.pairing_max_attempts,
                                   identity.public_raw),
            sessions=SessionManager(cfg, policy, metrics, audit, keep_awake),
            audit=audit, metrics=metrics,
            throttle=AuthThrottle(cfg.security.max_auth_failures, cfg.security.lockout_s),
            bind_host=bind, admin_token=admin_token,
        )
        state.sessions.start_reaper()
        keep_awake.update(0)  # "always" mode takes the lock right away
        public = uvicorn.Server(uvicorn.Config(
            GuardMiddleware(create_public_app(state), state), host=bind, port=cfg.server.port,
            ws_max_size=cfg.server.max_message_bytes, ws_ping_interval=20, ws_ping_timeout=20,
            proxy_headers=False, server_header=False, log_level="info",
            log_config=None,  # use our logging setup (console or rotating file)
        ))
        admin = uvicorn.Server(uvicorn.Config(
            create_admin_app(state), host="127.0.0.1", port=cfg.server.admin_port,
            server_header=False, log_level="warning", log_config=None,
        ))
        audit.write("server_started", bind=bind, port=cfg.server.port, version=__version__)
        logging.getLogger("theyso").info("Theyso %s starting on %s", __version__, state.public_url)
        print(f"\n  Theyso {__version__} listening on {state.public_url}")
        print(f"  Server fingerprint: {identity.fingerprint}")
        print("  Pair a phone from another terminal with: theyso pair\n")
        try:
            await asyncio.gather(public.serve(), admin.serve())
        finally:
            await state.sessions.close_all("server shutdown")
            keep_awake.release()
            (home / "admin.token").unlink(missing_ok=True)
            audit.write("server_stopped")

    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n  Theyso stopped.")
    return EXIT_OK


def cmd_pair(_: argparse.Namespace) -> int:
    import qrcode

    ticket = _admin("POST", "/admin/pair/start")
    qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(ticket["qr"])
    qr.make(fit=True)
    print("\nScan this with the Theyso app (Settings → Pair new PC):\n")
    qr.print_ascii(invert=True)
    print(f"  Server:       {ticket['url']}")
    print(f"  Fingerprint:  {ticket['server_fingerprint']}")
    print(f"  Expires in:   {int(ticket['expires_at'] - time.time())} s — single use\n")

    pid = ticket["pid"]
    while True:
        status = _admin("GET", f"/admin/pair/{pid}/wait")
        if status["state"] == "pending" and status["candidate"]:
            c = status["candidate"]
            print("  A phone wants to pair:")
            print(f"    Name:         {c['name']} ({c['platform']})")
            print(f"    From:         {c['addr']}")
            print(f"    Device key:   {c['fingerprint']}")
            print(f"\n    ┌─────────────────────┐\n    │  Code:  {c['sas'][:3]} {c['sas'][3:]}    │\n"
                  "    └─────────────────────┘")
            answer = input("\n  Does the phone show the SAME code? Approve? [y/N] ").strip().lower()
            if answer in {"y", "yes", "s", "si", "sí"}:
                device = _admin("POST", f"/admin/pair/{pid}/approve")
                print(f"\n  ✔ Paired '{device['name']}' as {device['device_id']}")
                return EXIT_OK
            _admin("POST", f"/admin/pair/{pid}/reject")
            print("\n  ✘ Rejected. The QR is now invalid.")
            return EXIT_ERR
        if status["state"] in {"expired", "rejected", "burned"}:
            print(f"  ✘ Pairing {status['state']}. Run `theyso pair` again.")
            return EXIT_ERR


def cmd_devices(_: argparse.Namespace) -> int:
    rows = _admin("GET", "/admin/devices")
    if not rows:
        print("No paired devices.")
    for d in rows:
        flag = "revoked" if d["revoked"] else ("online" if d["online"] else "offline")
        seen = time.strftime("%Y-%m-%d %H:%M", time.localtime(d["last_seen"])) if d["last_seen"] else "never"
        print(f"{d['device_id']:<18} {d['name']:<28} {flag:<8} last seen {seen}  key {d['fingerprint']}")
    return EXIT_OK


def cmd_revoke(args: argparse.Namespace) -> int:
    if args.all:
        print(_admin("POST", "/admin/devices/revoke-all"))
    elif args.device_id:
        print(_admin("POST", f"/admin/devices/{args.device_id}/revoke"))
    else:
        print("Give a device id or --all", file=sys.stderr)
        return EXIT_ERR
    return EXIT_OK


def cmd_panic(_: argparse.Namespace) -> int:
    print(_admin("POST", "/admin/panic"))
    return EXIT_OK


def cmd_audit(args: argparse.Namespace) -> int:
    for row in _admin("GET", "/admin/audit", params={"n": args.n}):
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(row.pop("ts")))
        print(ts, row.pop("event"), json.dumps(row, ensure_ascii=False))
    return EXIT_OK


def cmd_usage_export(args: argparse.Namespace) -> int:
    from theyso.metrics import Metrics

    dest = Path(args.dir)
    dest.mkdir(parents=True, exist_ok=True)
    metrics = Metrics(_home() / "usage.sqlite")
    for table in ("turns", "tools"):
        n = metrics.export_csv(table, dest / f"theyso_{table}.csv")
        print(f"{table}: {n} rows → {dest / f'theyso_{table}.csv'}")
    return EXIT_OK


def cmd_service(args: argparse.Namespace) -> int:
    from theyso.service import ensure_secrets_file, plan_install, plan_uninstall, run

    home = _home()
    if args.action == "install":
        ensure_secrets_file(home)
        plan = plan_install(home)
    else:
        plan = plan_uninstall()
    for entry in run(plan, install=args.action == "install", dry_run=args.dry_run):
        print(("(dry run) " if args.dry_run else "") + entry)
    if args.action == "install" and not args.dry_run:
        print(f"\n✔ {plan.description} installed. Theyso now starts when you log in.")
        if sys.platform.startswith("linux"):
            print("  To run it even before you log in:  sudo loginctl enable-linger $USER")
        print(f"  Logs: {home / 'theyso.log'}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="theyso", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"theyso {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init")
    p.add_argument("--force", action="store_true", help="overwrite config.toml")
    p.set_defaults(fn=cmd_init)
    sub.add_parser("doctor").set_defaults(fn=cmd_doctor)
    p = sub.add_parser("serve")
    p.add_argument("--host", help="override server.host")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--log-file", help="write logs to a rotating file; 'auto' = <theyso home>/theyso.log")
    p.set_defaults(fn=cmd_serve)
    p = sub.add_parser("service")
    p.add_argument("action", choices=["install", "uninstall"])
    p.add_argument("--dry-run", action="store_true", help="show what would be done")
    p.set_defaults(fn=cmd_service)
    sub.add_parser("pair").set_defaults(fn=cmd_pair)
    sub.add_parser("devices").set_defaults(fn=cmd_devices)
    p = sub.add_parser("revoke")
    p.add_argument("device_id", nargs="?")
    p.add_argument("--all", action="store_true")
    p.set_defaults(fn=cmd_revoke)
    sub.add_parser("panic").set_defaults(fn=cmd_panic)
    p = sub.add_parser("audit")
    p.add_argument("-n", type=int, default=50)
    p.set_defaults(fn=cmd_audit)
    p = sub.add_parser("usage")
    usage_sub = p.add_subparsers(dest="usage_cmd", required=True)
    e = usage_sub.add_parser("export")
    e.add_argument("dir")
    e.set_defaults(fn=cmd_usage_export)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.fn(args))
