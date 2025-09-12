"""Deterministic clock and scheduler utilities for simulations.

Use these helpers to control time explicitly during tests and demos.

- `SimClock`: monotonically increasing time in milliseconds; you call
  `advance(ms)` to move time forward.
- `SimScheduler`: schedules callbacks relative to the simulated time and
  executes them when `run_due()` is called.

Typical loop:

    scheduler.run_due()
    clock.advance(10)

This avoids real threads and non-determinism while developing algorithms.
"""

import heapq
from typing import Callable, List, Tuple


class SimClock:
    """Monotonic simulated clock measured in milliseconds."""

    def __init__(self) -> None:
        self.t = 0

    def now_ms(self) -> int:
        """Return the current simulated time in milliseconds."""
        return self.t

    def advance(self, ms: int) -> None:
        """Advance simulated time by `ms` milliseconds (non-negative)."""
        self.t += ms


class SimScheduler:
    """Scheduler backed by a min-heap of scheduled callbacks.

    Schedule callbacks using `call_later(ms, cb)`; get a cancel function back.
    Execute ready callbacks by calling `run_due()` after advancing the clock.
    A counter ensures FIFO ordering for callbacks scheduled for the same time.
    """

    def __init__(self, clock: SimClock) -> None:
        self.clock = clock
        self.heap: List[Tuple[int, int, Callable[[], None], bool]] = []
        self._counter = 0  # tie-breaker for stable ordering

    def call_later(self, ms: int, cb: Callable[[], None]):
        """Schedule `cb` to run after `ms` milliseconds of simulated time.

        Returns a zero-arg cancel function; if invoked before the callback is
        due, the callback will not run.
        """
        when = self.clock.now_ms() + ms
        self._counter += 1
        event = [when, self._counter, cb, True]
        heapq.heappush(self.heap, event)

        def cancel():
            event[3] = False

        return cancel

    def run_due(self) -> None:
        """Run all callbacks whose scheduled time is <= current time."""
        while self.heap and self.heap[0][0] <= self.clock.now_ms():
            when, _, cb, live = heapq.heappop(self.heap)
            if live:
                cb()

    def dump_state(self, n: int = 5) -> str:
        """Return a human-readable snapshot of timer state and queued events.

        Args:
            n: Maximum number of queued events to include (default: 5).

        The snapshot includes the current simulated time, total queued events,
        and details for the first `n` events in due-time order, without
        changing the underlying queue.
        """
        now = self.clock.now_ms()
        events = list(self.heap)  # Copy inspection without changing the original heap
        lines = [
            f"SimScheduler @ t = {now}ms",
            f"queued = {len(events)} (showing first {min(n, len(events))})",
        ]
        i = 0
        while i < n:
            when, counter, cb, live = heapq.heappop(events)
            cb_name = getattr(cb, "__name__", None)
            cb_desc = cb_name if isinstance(cb_name, str) else repr(cb)
            remaining = max(0, when - now)
            lines.append(
                f"#{i:02d} due @ {when}ms (in {remaining}ms) counter={counter} live={live} cb={cb_desc}"
            )
            i += 1
        return "\n".join(lines)
