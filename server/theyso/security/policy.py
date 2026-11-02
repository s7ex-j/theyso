"""Tool-permission policy.

Every tool call the agent wants to make is classified *before* it reaches the
phone:

    deny  → refused outright (never shown as a choice): `rm -rf ~`, reading ~/.ssh…
    ask   → sent to the phone as a permission card, tagged with a risk level.
            High-risk cards require biometric confirmation in the app.
    allow → read-only tools inside the workspace, if configured.

The deny layer is enforced through a PreToolUse hook, which runs for *every*
tool call — even ones the agent's own settings would auto-approve.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from theyso.config import PolicyConfig

Action = Literal["allow", "ask", "deny"]
Risk = Literal["low", "medium", "high"]

READ_TOOLS = {"Read", "Glob", "Grep", "LS", "NotebookRead"}
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
SHELL_TOOLS = {"Bash", "BashOutput", "KillShell", "bash", "shell"}
NETWORK_TOOLS = {"WebFetch", "WebSearch", "webfetch"}


@dataclass(frozen=True)
class Decision:
    action: Action
    risk: Risk
    reason: str


class Policy:
    def __init__(self, cfg: PolicyConfig) -> None:
        self.cfg = cfg
        self._deny = [re.compile(p) for p in cfg.always_deny_patterns]
        self._high = [re.compile(p) for p in cfg.high_risk_patterns]
        self._protected_dirs: list[Path] = []
        self._protected_globs: list[str] = []
        for p in cfg.protected_paths:
            if any(ch in p for ch in "*?["):
                self._protected_globs.append(p)
            else:
                self._protected_dirs.append(Path(p).expanduser().resolve())

    # ── paths ──────────────────────────────────────────────────────────────
    def is_protected(self, path: str | Path, cwd: Path) -> bool:
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = cwd / p
        p = p.resolve()
        if any(p == d or p.is_relative_to(d) for d in self._protected_dirs):
            return True
        return any(fnmatch.fnmatch(str(p), g) or fnmatch.fnmatch(p.name, g.split("/")[-1])
                   for g in self._protected_globs)

    @staticmethod
    def inside(path: str | Path, workspace: Path) -> bool:
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = workspace / p
        return p.resolve().is_relative_to(workspace.resolve())

    def _mentions_protected(self, command: str) -> bool:
        for d in self._protected_dirs:
            home_rel = str(d).replace(str(Path.home()), "~")
            if str(d) in command or home_rel in command:
                return True
        return bool(re.search(r"(^|[\s/'\"=])\.env(\.[\w-]+)?(['\"]|\s|$)", command))

    # ── main entry point ───────────────────────────────────────────────────
    def evaluate(self, tool: str, tool_input: dict[str, Any], workspace: Path) -> Decision:
        if tool in SHELL_TOOLS:
            command = str(tool_input.get("command", ""))
            if any(p.search(command) for p in self._deny):
                return Decision("deny", "high", "Command matches an always-deny rule")
            if self._mentions_protected(command):
                return Decision("ask", "high", "Command touches a protected path")
            if any(p.search(command) for p in self._high):
                return Decision("ask", "high", "Command matches a high-risk rule")
            return Decision("ask", "medium", "Shell command")

        path = (
            tool_input.get("file_path")
            or tool_input.get("notebook_path")
            or tool_input.get("path")
            or tool_input.get("filePath")
        )
        if path and self.is_protected(str(path), workspace):
            return Decision("deny", "high", "Path is protected (credentials / Theyso config)")

        if tool in READ_TOOLS:
            if path is None or self.inside(str(path), workspace):
                if tool in self.cfg.auto_allow_tools:
                    return Decision("allow", "low", "Read-only tool inside the workspace")
                return Decision("ask", "low", "Read-only tool")
            return Decision("ask", "medium", "Reads outside the workspace")

        if tool in WRITE_TOOLS:
            if path and not self.inside(str(path), workspace):
                return Decision("ask", "high", "Writes outside the workspace")
            return Decision("ask", "medium", "Modifies a file")

        if tool in NETWORK_TOOLS:
            return Decision("ask", "medium", "Network access")

        if tool.startswith("mcp__"):
            return Decision("ask", "medium", "External MCP tool")

        return Decision("ask", "medium", "Tool requires approval")
