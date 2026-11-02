"""Append-only JSONL audit log: who connected, what was approved, what was denied.

Prompts are stored hashed by default (``audit_prompts = "hash"``) so the log
proves *that* something was sent without becoming a second copy of your work.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Literal


class AuditLog:
    def __init__(self, path: Path, prompt_mode: Literal["full", "hash", "none"] = "hash") -> None:
        self.path = path
        self.prompt_mode = prompt_mode
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.touch()
        if sys.platform != "win32":
            os.chmod(path, 0o600)

    def prompt_field(self, text: str) -> dict[str, Any]:
        if self.prompt_mode == "full":
            return {"prompt": text}
        if self.prompt_mode == "hash":
            return {"prompt_sha256": hashlib.sha256(text.encode()).hexdigest(), "prompt_len": len(text)}
        return {}

    def write(self, event: str, **fields: Any) -> None:
        record = {"ts": round(time.time(), 3), "event": event, **fields}
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock, self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def tail(self, n: int = 50) -> list[dict[str, Any]]:
        lines = self.path.read_text(encoding="utf-8").splitlines()[-n:]
        return [json.loads(line) for line in lines if line.strip()]
