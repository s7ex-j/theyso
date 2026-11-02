"""Keep the PC awake while an agent is working — only on charger, only when needed.

Instead of asking you to change power settings forever, Theyso holds a
"don't sleep" lock while at least one session is open and the PC is on AC power,
and releases it as soon as the last session closes or you unplug:

* Windows  SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
* macOS    `caffeinate -i -s -w <pid>`  (-s = only while on AC power)
* Linux    `systemd-inhibit --what=sleep:idle … sleep infinity`

The screen may still turn off and lock — that is fine, the server keeps running.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import subprocess  # noqa: S404  # nosec B404 — fixed argv, no shell
import sys
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

Mode = Literal["sessions", "always", "never"]

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def on_ac_power() -> bool:
    """Best effort. Unknown → True (desktops have no battery)."""
    try:
        if sys.platform == "win32":
            import ctypes

            class SystemPowerStatus(ctypes.Structure):
                _fields_ = [("ACLineStatus", ctypes.c_byte), ("BatteryFlag", ctypes.c_byte),
                            ("BatteryLifePercent", ctypes.c_byte), ("SystemStatusFlag", ctypes.c_byte),
                            ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]

            status = SystemPowerStatus()
            if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):  # type: ignore[attr-defined]
                return True
            return status.ACLineStatus != 0  # 0 = battery, 1 = AC, 255 = unknown
        if sys.platform == "darwin":
            out = subprocess.run(["/usr/bin/pmset", "-g", "batt"], capture_output=True,  # noqa: S603  # nosec B603
                                 text=True, timeout=3).stdout
            return "Battery Power" not in out
        supplies = Path("/sys/class/power_supply")
        mains = [p for p in supplies.glob("*") if (p / "type").exists() and (p / "type").read_text().strip() == "Mains"]
        if not mains:
            return True
        return any((p / "online").read_text().strip() == "1" for p in mains if (p / "online").exists())
    except Exception:
        return True


class KeepAwake:
    def __init__(self, mode: Mode = "sessions", ac_only: bool = True) -> None:
        self.mode = mode
        self.ac_only = ac_only
        self.held = False
        self._proc: subprocess.Popen[bytes] | None = None

    def update(self, active_sessions: int) -> None:
        """Call whenever sessions change, and periodically (to react to unplugging)."""
        want = self.mode == "always" or (self.mode == "sessions" and active_sessions > 0)
        if want and self.ac_only and not on_ac_power():
            want = False
        if want and not self.held:
            self._acquire()
        elif not want and self.held:
            self.release()

    def _acquire(self) -> None:
        try:
            if sys.platform == "win32":
                import ctypes

                ctypes.windll.kernel32.SetThreadExecutionState(  # type: ignore[attr-defined]
                    ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
            elif sys.platform == "darwin":
                self._proc = subprocess.Popen(  # noqa: S603  # nosec B603
                    ["/usr/bin/caffeinate", "-i", "-s", "-w", str(os.getpid())])
            else:
                binary = shutil.which("systemd-inhibit")
                if not binary:
                    log.warning("systemd-inhibit not found; cannot keep the PC awake")
                    return
                self._proc = subprocess.Popen(  # noqa: S603  # nosec B603
                    [binary, "--what=sleep:idle", "--who=theyso", "--why=Agent session running",
                     "--mode=block", "sleep", "infinity"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.held = True
            log.info("Keeping the PC awake while agent sessions are open")
        except Exception:
            log.exception("Could not take the keep-awake lock")

    def release(self) -> None:
        if not self.held:
            return
        if sys.platform == "win32":
            with contextlib.suppress(Exception):
                import ctypes

                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)  # type: ignore[attr-defined]
        if self._proc is not None:
            self._proc.terminate()
            with contextlib.suppress(Exception):
                self._proc.wait(timeout=3)
            self._proc = None
        self.held = False
        log.info("Released the keep-awake lock")
