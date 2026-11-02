"""Usage analytics in a local SQLite file — the "data" side of the project.

Two tables:

* ``turns``   one row per agent turn: tokens, model, profile, cost.
* ``tools``   one row per tool decision: tool, risk, decision, human latency.

Cost is subtle with routers. Claude Code computes ``total_cost_usd`` from
Anthropic's list prices *by model name*, even if the request actually went to a
free model through 9Router. So each row records a ``cost_basis``:

* ``reported``        official endpoint, the reported cost is real
* ``profile_price``   computed from the profile's own price table
* ``list_equivalent`` third-party endpoint without a price table: the number is
                      what it *would* have cost at list price — i.e. savings.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import threading
import time
from pathlib import Path
from typing import Any

from theyso.agents.base import TurnUsage
from theyso.config import Profile

SCHEMA = """
CREATE TABLE IF NOT EXISTS turns (
  ts REAL NOT NULL, sid TEXT, agent TEXT, profile TEXT, model TEXT,
  input_tokens INTEGER, output_tokens INTEGER, cache_read INTEGER, cache_write INTEGER,
  cost_usd REAL, cost_basis TEXT, duration_ms INTEGER, num_turns INTEGER
);
CREATE TABLE IF NOT EXISTS tools (
  ts REAL NOT NULL, sid TEXT, profile TEXT, tool TEXT, risk TEXT,
  decision TEXT, decided_by TEXT, latency_ms INTEGER
);
CREATE INDEX IF NOT EXISTS turns_ts ON turns(ts);
CREATE INDEX IF NOT EXISTS tools_ts ON tools(ts);
"""


def cost_for(turn: TurnUsage, profile: Profile) -> tuple[float | None, str]:
    if profile.price_input_per_mtok is not None and profile.price_output_per_mtok is not None:
        cost = (
            turn.input_tokens * profile.price_input_per_mtok
            + turn.output_tokens * profile.price_output_per_mtok
        ) / 1_000_000
        return round(cost, 6), "profile_price"
    if "ANTHROPIC_BASE_URL" in profile.env and profile.agent == "claude-code":
        return turn.cost_usd, "list_equivalent"
    return turn.cost_usd, "reported"


class Metrics:
    def __init__(self, path: Path) -> None:
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.executescript(SCHEMA)
        if sys.platform != "win32":
            os.chmod(path, 0o600)

    def record_turn(self, sid: str, agent: str, profile_name: str, profile: Profile, turn: TurnUsage) -> None:
        cost, basis = cost_for(turn, profile)
        with self._lock:
            self._db.execute(
                "INSERT INTO turns VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (time.time(), sid, agent, profile_name, turn.model, turn.input_tokens, turn.output_tokens,
                 turn.cache_read_tokens, turn.cache_write_tokens, cost, basis, turn.duration_ms, turn.num_turns),
            )
            self._db.commit()

    def record_tool(self, sid: str, profile: str, tool: str, risk: str, decision: str,
                    decided_by: str, latency_ms: int) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO tools VALUES (?,?,?,?,?,?,?,?)",
                (time.time(), sid, profile, tool, risk, decision, decided_by, latency_ms),
            )
            self._db.commit()

    def spent_today(self, profile_name: str) -> float:
        start = time.time() - (time.time() % 86400)
        with self._lock:
            row = self._db.execute(
                "SELECT COALESCE(SUM(cost_usd),0) FROM turns WHERE profile=? AND ts>=? "
                "AND cost_basis IN ('reported','profile_price')",
                (profile_name, start),
            ).fetchone()
        return float(row[0])

    def summary(self, days: int) -> dict[str, Any]:
        since = time.time() - days * 86400
        with self._lock:
            cur = self._db.cursor()
            by_day = cur.execute(
                "SELECT date(ts,'unixepoch','localtime') d, SUM(input_tokens), SUM(output_tokens), "
                "SUM(CASE WHEN cost_basis!='list_equivalent' THEN cost_usd ELSE 0 END), "
                "SUM(CASE WHEN cost_basis='list_equivalent' THEN cost_usd ELSE 0 END), COUNT(*) "
                "FROM turns WHERE ts>=? GROUP BY d ORDER BY d", (since,)).fetchall()
            by_model = cur.execute(
                "SELECT COALESCE(model,'?'), profile, SUM(input_tokens), SUM(output_tokens), "
                "SUM(cost_usd), cost_basis, COUNT(*), AVG(duration_ms) FROM turns WHERE ts>=? "
                "GROUP BY model, profile, cost_basis ORDER BY SUM(input_tokens+output_tokens) DESC",
                (since,)).fetchall()
            tools = cur.execute(
                "SELECT tool, COUNT(*), SUM(decision='allow'), SUM(decision='deny'), "
                "AVG(CASE WHEN decided_by='phone' THEN latency_ms END) FROM tools WHERE ts>=? "
                "GROUP BY tool ORDER BY COUNT(*) DESC LIMIT 20", (since,)).fetchall()
        return {
            "days": days,
            "by_day": [
                {"date": d, "input_tokens": i or 0, "output_tokens": o or 0, "cost_usd": round(c or 0, 4),
                 "list_equivalent_usd": round(s or 0, 4), "turns": n}
                for d, i, o, c, s, n in by_day
            ],
            "by_model": [
                {"model": m, "profile": p, "input_tokens": i or 0, "output_tokens": o or 0,
                 "cost_usd": round(c or 0, 4), "cost_basis": b, "turns": n,
                 "avg_duration_ms": int(a) if a else None}
                for m, p, i, o, c, b, n, a in by_model
            ],
            "tools": [
                {"tool": t, "calls": n, "allowed": a or 0, "denied": d or 0,
                 "avg_human_latency_ms": int(lat) if lat else None}
                for t, n, a, d, lat in tools
            ],
        }

    def export_csv(self, table: str, dest: Path) -> int:
        import csv

        if table not in {"turns", "tools"}:
            raise ValueError("table must be 'turns' or 'tools'")
        with self._lock:
            cur = self._db.execute(f"SELECT * FROM {table}")  # noqa: S608  # nosec B608 — table name is whitelisted above
            cols = [c[0] for c in cur.description]
            rows = cur.fetchall()
        with dest.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(cols)
            writer.writerows(rows)
        return len(rows)
