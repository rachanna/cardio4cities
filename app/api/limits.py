"""Rate limits held in memory: one app instance serves the demo (HLD, one run at a time)."""

import time
from collections import defaultdict, deque
from collections.abc import Callable

# LLD-4 §3.1: five failed access-code attempts per IP per 10 minutes
SESSION_MAX_FAILURES = 5
SESSION_WINDOW_S = 600.0


class FailureLimiter:
    """Counts failures per key in a sliding window; a key at the limit is blocked."""

    def __init__(
        self,
        max_failures: int = SESSION_MAX_FAILURES,
        window_s: float = SESSION_WINDOW_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max, self._window, self._clock = max_failures, window_s, clock
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _recent(self, key: str) -> deque[float]:
        cutoff = self._clock() - self._window
        failures = self._failures[key]
        while failures and failures[0] <= cutoff:
            failures.popleft()
        return failures

    def blocked(self, key: str) -> bool:
        return len(self._recent(key)) >= self._max

    def record_failure(self, key: str) -> None:
        self._recent(key).append(self._clock())
