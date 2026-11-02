"""Mask credentials before agent output leaves the PC.

The agent may ``cat .env`` or print a stack trace with a token in it. The phone
is a more exposed device than your PC (lost, screenshotted, shoulder-surfed),
so secrets are masked on the way out. This is defense in depth, not a
guarantee: unknown formats will slip through.
"""

from __future__ import annotations

import re
from typing import Any

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("anthropic", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("openai", re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{20,}")),
    ("openrouter", re.compile(r"sk-or-v1-[A-Za-z0-9]{32,}")),
    ("github", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,}")),
    ("aws_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("google", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("slack", re.compile(r"xox[abprs]-[A-Za-z0-9\-]{10,}")),
    ("stripe", re.compile(r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{20,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
    (
        "private_key",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----"),
    ),
    (
        "env_assignment",
        re.compile(
            r"(?im)^(\s*(?:export\s+)?[A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASSWD|API_?KEY|PRIVATE)[A-Z0-9_]*\s*=\s*)"
            r"(['\"]?)([^\s'\"]{6,})\2"
        ),
    ),
]


def redact_text(text: str) -> tuple[str, int]:
    count = 0
    for name, pattern in _PATTERNS:
        if name == "env_assignment":
            text, n = pattern.subn(lambda m: f"{m.group(1)}{m.group(2)}«redacted»{m.group(2)}", text)
        else:
            text, n = pattern.subn(f"«redacted:{name}»", text)
        count += n
    return text, count


def redact(value: Any) -> tuple[Any, int]:
    """Recursively redact strings inside dicts/lists. Returns (value, n_redactions)."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        total = 0
        out_list = []
        for item in value:
            red, n = redact(item)
            out_list.append(red)
            total += n
        return out_list, total
    if isinstance(value, dict):
        total = 0
        out_dict = {}
        for key, item in value.items():
            red, n = redact(item)
            out_dict[key] = red
            total += n
        return out_dict, total
    return value, 0
