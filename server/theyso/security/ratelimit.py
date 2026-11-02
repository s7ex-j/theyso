"""Rate limiting: auth-failure lockout per source address, and a per-connection
message budget so a compromised or buggy client cannot flood the agent."""

from __future__ import annotations

import time
from collections import defaultdict, deque


class AuthThrottle:
    def __init__(self, max_failures: int, lockout_s: int, window_s: int = 600) -> None:
        self.max_failures = max_failures
        self.lockout_s = lockout_s
        self.window_s = window_s
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._locked_until: dict[str, float] = {}

    def is_locked(self, key: str, now: float | None = None) -> bool:
        now = now or time.time()
        until = self._locked_until.get(key)
        if until and until > now:
            return True
        self._locked_until.pop(key, None)
        return False

    def fail(self, key: str, now: float | None = None) -> bool:
        """Record a failure. Returns True if the key is now locked out."""
        now = now or time.time()
        q = self._failures[key]
        q.append(now)
        while q and q[0] < now - self.window_s:
            q.popleft()
        if len(q) >= self.max_failures:
            self._locked_until[key] = now + self.lockout_s
            q.clear()
            return True
        return False

    def success(self, key: str) -> None:
        self._failures.pop(key, None)


class TokenBucket:
    def __init__(self, per_minute: int) -> None:
        self.capacity = float(per_minute)
        self.tokens = float(per_minute)
        self.rate = per_minute / 60.0
        self.updated = time.monotonic()

    def allow(self, cost: float = 1.0) -> bool:
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False
