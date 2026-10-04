"""Rate limits held in memory: one app instance serves the demo (HLD, one run at a time)."""

import time
from collections import deque
from collections.abc import Callable

# LLD-4 §3.1: five failed access-code attempts per IP per 10 minutes
SESSION_MAX_FAILURES = 5
SESSION_WINDOW_S = 600.0
MAX_KEYS = 10_000  # a memory bound: beyond it the oldest keys are forgotten (RV-068)


class FailureLimiter:
    """Counts failures per key in a sliding window; a key at the limit is blocked."""

    def __init__(
        self,
        max_failures: int = SESSION_MAX_FAILURES,
        window_s: float = SESSION_WINDOW_S,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = MAX_KEYS,
    ) -> None:
        self._max, self._window, self._clock = max_failures, window_s, clock
        self._max_keys = max_keys
        self._failures: dict[str, deque[float]] = {}  # insertion order: oldest key first

    def _recent(self, key: str) -> deque[float]:
        cutoff = self._clock() - self._window
        failures = self._failures.get(key, deque())
        while failures and failures[0] <= cutoff:
            failures.popleft()
        if not failures:
            self._failures.pop(key, None)  # a key with no recent failure is not kept
        return failures

    def blocked(self, key: str) -> bool:
        return len(self._recent(key)) >= self._max

    def record_failure(self, key: str) -> None:
        failures = self._recent(key)
        failures.append(self._clock())
        self._failures.pop(key, None)
        self._failures[key] = failures  # now the newest key
        while len(self._failures) > self._max_keys:
            del self._failures[next(iter(self._failures))]

    def __len__(self) -> int:
        """Keys held: each has a failure inside the window, at most `max_keys`."""
        return len(self._failures)
