"""Deterministic discrete-event scheduler.

Simulated time only moves when you ask the scheduler to run. ``run_until(t)``
executes every callback due at or before ``t`` in due-time order, jumping the
clock to each callback's due time as it goes. Nothing sleeps and nothing runs
in the background, so a run given the same inputs always produces the same
result, and a simulated hour takes milliseconds of real time.

The scheduler also owns the run's ``Trace``. Timers that belong to a node (the
callback is one of the node's bound methods, or a closure over the node) are
recorded on that node's timeline as set, fired, or cancelled.

For working through a run one event at a time, ``peek()`` describes the next
event without running it and ``step()`` runs exactly one event and returns a
``Step`` listing everything it caused.
"""

from __future__ import annotations

import heapq
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable

from .protocols import Cancel, Node
from .trace import Event, Timeline, Trace


@dataclass(order=True)
class _Event:
    when: int
    seq: int  # creation order; breaks ties so equal due times run first-in first-out
    cb: Callable[[], None] = field(compare=False)
    live: bool = field(default=True, compare=False)
    owner: Any = field(default=None, compare=False)  # the node this timer belongs to, if known
    timer_id: int | None = field(default=None, compare=False)
    description: str = field(default="", compare=False)


@dataclass
class Next:
    """The next event that would run, as reported by ``peek()``."""

    due_ms: int
    description: str

    def __repr__(self) -> str:
        return f"next @ {self.due_ms} ms: {self.description}"


@dataclass(repr=False)
class Step:
    """What one call to ``step()`` did: the event that ran and everything it caused."""

    number: int
    t_ms: int
    trigger: str
    events: list[Event]
    ran: bool = True

    def __bool__(self) -> bool:
        return self.ran

    def __repr__(self) -> str:
        return str(self)

    def __str__(self) -> str:
        if not self.ran:
            return f"nothing pending @ {self.t_ms} ms"
        lines = [f"Step {self.number} @ {self.t_ms} ms: {self.trigger}"]
        lines.extend(f"  {ev}" for ev in self.events)
        return "\n".join(lines)

    def _repr_html_(self) -> str:
        from html import escape

        if not self.ran:
            return f"<i>nothing pending @ {self.t_ms} ms</i>"
        head = f"<div><b>Step {self.number} @ {self.t_ms} ms:</b> {escape(self.trigger)}</div>"
        return head + (Timeline(self.events)._repr_html_() if self.events else "<i>(no events recorded)</i>")


def _owner_of(cb: Callable[[], None]) -> Any:
    """The node a callback belongs to: its bound ``self``, or a node it closes over."""
    bound = getattr(cb, "__self__", None)
    if isinstance(bound, Node):
        return bound
    try:
        free = inspect.getclosurevars(cb).nonlocals
    except (TypeError, ValueError):
        return None
    return next((v for v in free.values() if isinstance(v, Node)), None)


def _name_of(cb: Callable[[], None]) -> str:
    return getattr(cb, "__name__", None) or type(cb).__name__


def _describe(cb: Callable[[], None], owner: Any) -> str:
    """How ``pending()``, ``peek()`` and ``step()`` refer to a callback."""
    description = getattr(cb, "description", None)
    if description:
        return description
    if owner is not None:
        return f"timer {_name_of(cb)} at {owner.node_id}"
    return getattr(cb, "__qualname__", None) or repr(cb)


class SimScheduler:
    """Implements the ``Scheduler`` protocol over a simulated clock."""

    def __init__(self, verbose: bool = False) -> None:
        self._now = 0
        self._heap: list[_Event] = []
        self._seq = 0
        self.steps = 0
        self.trace = Trace(now=self.now_ms, verbose=verbose)

    def now_ms(self) -> int:
        return self._now

    def call_later(self, ms: int, cb: Callable[[], None]) -> Cancel:
        if ms < 0:
            raise ValueError(f"call_later delay must be >= 0, got {ms}")
        self._seq += 1
        owner = _owner_of(cb)
        name = _name_of(cb)
        timer_id = self.trace.timer_set(owner.node_id, name, self._now + ms) if owner is not None else None
        event = _Event(self._now + ms, self._seq, cb, owner=owner, timer_id=timer_id,
                       description=_describe(cb, owner))
        heapq.heappush(self._heap, event)

        def cancel() -> None:
            if event.live:
                event.live = False
                if timer_id is not None:
                    self.trace.timer_cancelled(owner.node_id, name, timer_id)

        return cancel

    def run_until(self, t_ms: int) -> None:
        """Run every callback due at or before ``t_ms``, then set the clock to ``t_ms``."""
        while self._heap and self._heap[0].when <= t_ms:
            self._run_next()
        self._now = max(self._now, t_ms)

    def run_until_idle(self, max_ms: int) -> bool:
        """Run until no callbacks remain, or until the next one is due after ``max_ms``.

        Returns True if the scheduler went idle. Returns False if it stopped at
        ``max_ms`` with work still pending, which is what happens for algorithms
        that keep re-arming timers (heartbeats, retries, and the like).
        """
        while self._heap and self._heap[0].when <= max_ms:
            self._run_next()
        if self.pending():
            self._now = max(self._now, max_ms)
            return False
        return True

    def pending(self) -> list[tuple[int, str]]:
        """Live callbacks as ``(due_ms, description)`` pairs, soonest first."""
        return sorted((ev.when, ev.description) for ev in self._heap if ev.live)

    def peek(self) -> Next | None:
        """Describe the next event without running it. ``None`` if nothing is pending."""
        while self._heap and not self._heap[0].live:
            heapq.heappop(self._heap)  # discard cancelled events
        if not self._heap:
            return None
        return Next(self._heap[0].when, self._heap[0].description)

    def step(self) -> Step:
        """Run exactly one event and return what it caused.

        The returned ``Step`` is falsy when nothing was pending, so
        ``while scheduler.step(): ...`` runs to the end.
        """
        start = len(self.trace.events)
        while self._heap:
            event = heapq.heappop(self._heap)
            if event.live:
                self._run(event)
                self.steps += 1
                return Step(self.steps, self._now, event.description, self.trace.events[start:])
        return Step(self.steps, self._now, "nothing pending", [], ran=False)

    def _run_next(self) -> None:
        event = heapq.heappop(self._heap)
        if event.live:
            self._run(event)

    def _run(self, event: _Event) -> None:
        event.live = False
        self._now = event.when
        if event.timer_id is not None:
            self.trace.timer_fired(event.owner.node_id, _name_of(event.cb), event.timer_id)
        event.cb()
        if event.owner is not None:
            self.trace.snapshot(event.owner)
