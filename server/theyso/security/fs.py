"""Filesystem helpers that create files readable only by the current user."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        os.chmod(path, 0o700)


def write_private_file(path: Path, data: bytes) -> None:
    """Atomically write ``data`` to ``path`` with mode 0600.

    The temp file is created with 0600 *before* any data is written, so there is
    no window in which the secret is world-readable, and ``os.replace`` makes the
    swap atomic so a crash never leaves a half-written registry.
    """
    ensure_private_dir(path.parent)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        if sys.platform != "win32":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def check_private(path: Path) -> list[str]:
    """Return human-readable warnings if ``path`` is readable by others."""
    if sys.platform == "win32" or not path.exists():
        return []
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        return [f"{path} has permissions {oct(mode)}; expected 0600/0700"]
    return []
