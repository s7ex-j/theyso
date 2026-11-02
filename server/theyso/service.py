"""Start Theyso automatically when you log in, and load API keys from a private file.

`theyso service install` writes ONE file for your OS and registers it:

* Linux    ~/.config/systemd/user/theyso.service   (systemctl --user)
* macOS    ~/Library/LaunchAgents/io.github.s7ex.theyso.plist   (launchctl)
* Windows  a "Theyso" task in Task Scheduler, run at log-on with normal rights

API keys go in ``<theyso home>/secrets.env`` (KEY=value per line, mode 0600),
which `theyso serve` reads itself — so the same file works on all three systems
and keys never end up inside a service definition.
"""

from __future__ import annotations

import os
import shutil
import subprocess  # noqa: S404  # nosec B404 — fixed argv, no shell
import sys
from dataclasses import dataclass
from pathlib import Path

from theyso.security.fs import check_private, write_private_file

LABEL = "io.github.s7ex.theyso"
SECRETS_TEMPLATE = b"""# Theyso secrets - one KEY=value per line. Keep this file private (0600).
# Referenced from config.toml as env:KEY, e.g.  ANTHROPIC_AUTH_TOKEN = "env:ROUTER_API_KEY"
# ROUTER_API_KEY=
# OPENROUTER_API_KEY=
"""


def load_secrets_env(path: Path) -> list[str]:
    """Read KEY=value lines into os.environ (existing variables win). Returns warnings."""
    if not path.exists():
        return []
    warnings = check_private(path)
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip().removeprefix("export ").strip(), value.strip().strip("'\"")
        if key and value:
            os.environ.setdefault(key, value)
    return warnings


def ensure_secrets_file(home: Path) -> Path:
    path = home / "secrets.env"
    if not path.exists():
        write_private_file(path, SECRETS_TEMPLATE)
    return path


def serve_command() -> list[str]:
    """Run through the current interpreter: works for pipx, venvs and plain installs."""
    python = Path(sys.executable)
    if sys.platform == "win32":
        pythonw = python.with_name("pythonw.exe")  # no console window at log-on
        if pythonw.exists():
            python = pythonw
    return [str(python), "-m", "theyso", "serve", "--log-file", "auto"]


@dataclass
class Plan:
    description: str
    file: Path | None
    content: str | None
    commands: list[list[str]]


def plan_install(home: Path) -> Plan:
    cmd = serve_command()
    if sys.platform.startswith("linux"):
        unit = Path.home() / ".config/systemd/user/theyso.service"
        exec_line = " ".join(f'"{c}"' if " " in c else c for c in cmd)
        content = f"""[Unit]
Description=Theyso - phone remote for coding agents
After=network-online.target

[Service]
ExecStart={exec_line}
Environment=THEYSO_HOME={home}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""
        return Plan("systemd user service", unit, content, [
            ["systemctl", "--user", "daemon-reload"],
            ["systemctl", "--user", "enable", "--now", "theyso.service"],
        ])
    if sys.platform == "darwin":
        plist = Path.home() / f"Library/LaunchAgents/{LABEL}.plist"
        args = "\n".join(f"    <string>{c}</string>" for c in cmd)
        content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key><array>
{args}
  </array>
  <key>EnvironmentVariables</key><dict><key>THEYSO_HOME</key><string>{home}</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
</dict></plist>
"""
        return Plan("launchd agent", plist, content, [["launchctl", "load", "-w", str(plist)]])
    if sys.platform == "win32":
        tr = " ".join(f'"{c}"' for c in cmd)
        return Plan("Task Scheduler task", None, None, [
            ["schtasks", "/Create", "/TN", "Theyso", "/TR", tr, "/SC", "ONLOGON", "/RL", "LIMITED", "/F"],
        ])
    raise RuntimeError(f"Unsupported platform: {sys.platform}")


def plan_uninstall() -> Plan:
    if sys.platform.startswith("linux"):
        unit = Path.home() / ".config/systemd/user/theyso.service"
        return Plan("systemd user service", unit, None, [
            ["systemctl", "--user", "disable", "--now", "theyso.service"],
        ])
    if sys.platform == "darwin":
        plist = Path.home() / f"Library/LaunchAgents/{LABEL}.plist"
        return Plan("launchd agent", plist, None, [["launchctl", "unload", "-w", str(plist)]])
    if sys.platform == "win32":
        return Plan("Task Scheduler task", None, None, [["schtasks", "/Delete", "/TN", "Theyso", "/F"]])
    raise RuntimeError(f"Unsupported platform: {sys.platform}")


def run(plan: Plan, install: bool, dry_run: bool) -> list[str]:
    log: list[str] = []
    if install and plan.file and plan.content is not None:
        log.append(f"write {plan.file}")
        if not dry_run:
            plan.file.parent.mkdir(parents=True, exist_ok=True)
            plan.file.write_text(plan.content, encoding="utf-8")
    for command in plan.commands:
        log.append("run   " + " ".join(command))
        if not dry_run and shutil.which(command[0]):
            subprocess.run(command, check=False)  # noqa: S603  # nosec B603
    if not install and plan.file:
        log.append(f"remove {plan.file}")
        if not dry_run:
            plan.file.unlink(missing_ok=True)
    return log
