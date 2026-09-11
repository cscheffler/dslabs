"""A timeline of everything that happened in a simulation.

The scheduler owns one ``Trace`` and shares it with the network, so a single
list of events covers messages, timers, client requests, node state, and any
notes a node writes about itself. Views over that list work in a terminal
(``print(...)``) and render richly in a notebook (as the last expression in a
cell):

- ``trace.messages()``: one row per message with its fate and delay
- ``trace.timeline()``: every event in time order
- ``trace.diagram()``: a space-time diagram, as SVG
- ``trace.explain(node_id)``: what one node sent, received, and did

For an animated replay, ``trace.save_json(path)`` exports the run for the
standalone viewer at ``dslabs/viewer.html``, and ``trace.save_viewer(path)``
writes a single HTML file with the run embedded, ready to open in a browser.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterator, Sequence

from .protocols import Message

if TYPE_CHECKING:
    from .diagram import Diagram

VIEWER = Path(__file__).with_name("viewer.html")
_VIEWER_PLACEHOLDER = "/*DSLABS_TRACE_PLACEHOLDER*/"

MESSAGE_KINDS = ("send", "drop", "deliver")
TIMER_KINDS = ("timer_set", "timer_fired", "timer_cancelled")
ALL_KINDS = MESSAGE_KINDS + ("client", "note", "state") + TIMER_KINDS

_KIND_LABEL = {
    "send": "send",
    "deliver": "deliver",
    "drop": "drop",
    "client": "client",
    "note": "note",
    "state": "state",
    "timer_set": "timer",
    "timer_fired": "timer",
    "timer_cancelled": "timer",
}


def describe(msg: Message) -> str:
    """Compact one-line summary of a message, e.g. ``replicate x=1 seq=3``.

    The ``type`` field comes first and ``from`` is left out. A ``key``/``value``
    pair is collapsed to ``key=value``.
    """
    parts = [str(msg["type"])] if "type" in msg else []
    rest = {k: v for k, v in msg.items() if k not in ("type", "from")}
    if "key" in rest and "value" in rest:
        parts.append(f"{rest.pop('key')}={rest.pop('value')}")
    parts.extend(f"{k}={v}" for k, v in rest.items())
    return " ".join(parts) or "{}"


def describe_state(state: dict[str, Any]) -> str:
    return " ".join(f"{k}={v}" for k, v in state.items()) or "{}"


@dataclass
class Event:
    t_ms: int
    kind: str
    frm: str | None = None  # sender (send, drop, deliver)
    to: str | None = None  # receiver (send, drop, deliver)
    node: str | None = None  # the node this happened at (client, note, timer_*, state)
    msg: Message | None = None
    msg_id: int | None = None
    delay_ms: int | None = None  # deliver: time in flight; drop: how long it would have taken
    rule: str | None = None  # drop: the rule that dropped it
    text: str | None = None  # client, note, timer_*: description
    timer_id: int | None = None
    due_ms: int | None = None  # timer_set
    state: dict[str, Any] | None = None  # state

    @property
    def nodes(self) -> tuple[str, ...]:
        """Every node this event touches."""
        return tuple(n for n in (self.frm, self.to, self.node) if n is not None)

    @property
    def place(self) -> str:
        return f"{self.frm} -> {self.to}" if self.frm is not None else (self.node or "")

    @property
    def detail(self) -> str:
        k = self.kind
        if k == "send":
            return f"#{self.msg_id} {describe(self.msg)}"
        if k == "deliver":
            return f"#{self.msg_id} {describe(self.msg)}  (+{self.delay_ms} ms)"
        if k == "drop":
            return f"#{self.msg_id} {describe(self.msg)}  dropped by {self.rule}"
        if k == "timer_set":
            return f"set {self.text}, due @ {self.due_ms} ms"
        if k == "timer_fired":
            return f"fired {self.text}"
        if k == "timer_cancelled":
            return f"cancelled {self.text}"
        if k == "state":
            return describe_state(self.state)
        return self.text or ""

    def __str__(self) -> str:
        return f"@{self.t_ms:>7} ms  {self.place:<10}  {_KIND_LABEL[self.kind]:<8} {self.detail}"


class Trace:
    def __init__(self, now: Callable[[], int] = lambda: 0, verbose: bool = False) -> None:
        self.now = now
        self.verbose = verbose
        self.events: list[Event] = []
        self.nodes: list[str] = []  # in the order they joined; the diagram's row order
        self._msg_seq = 0
        self._timer_seq = 0
        self._last_state: dict[str, str] = {}

    def __iter__(self) -> Iterator[Event]:
        return iter(self.events)

    def __len__(self) -> int:
        return len(self.events)

    def __getitem__(self, i):
        return self.events[i]

    def __str__(self) -> str:
        return str(self.timeline())

    def add_node(self, node_id: str) -> None:
        if node_id not in self.nodes:
            self.nodes.append(node_id)

    # --- recording ----------------------------------------------------------

    def record(self, event: Event) -> None:
        for n in event.nodes:
            self.add_node(n)
        self.events.append(event)
        if self.verbose and event.kind not in ("timer_set", "timer_cancelled"):
            print(event)

    def send(self, frm: str, to: str, msg: Message) -> int:
        self._msg_seq += 1
        self.record(Event(self.now(), "send", frm=frm, to=to, msg=msg, msg_id=self._msg_seq))
        return self._msg_seq

    def drop(self, frm: str, to: str, msg: Message, msg_id: int, rule: str, delay_ms: int) -> None:
        self.record(Event(self.now(), "drop", frm=frm, to=to, msg=msg, msg_id=msg_id, rule=rule, delay_ms=delay_ms))

    def deliver(self, frm: str, to: str, msg: Message, msg_id: int, delay_ms: int) -> None:
        self.record(Event(self.now(), "deliver", frm=frm, to=to, msg=msg, msg_id=msg_id, delay_ms=delay_ms))

    def client(self, node: str, text: str) -> None:
        self.record(Event(self.now(), "client", node=node, text=text))

    def note(self, node: str, text: str) -> None:
        self.record(Event(self.now(), "note", node=node, text=text))

    def timer_set(self, node: str, name: str, due_ms: int) -> int:
        self._timer_seq += 1
        self.record(Event(self.now(), "timer_set", node=node, text=name, timer_id=self._timer_seq, due_ms=due_ms))
        return self._timer_seq

    def timer_fired(self, node: str, name: str, timer_id: int) -> None:
        self.record(Event(self.now(), "timer_fired", node=node, text=name, timer_id=timer_id))

    def timer_cancelled(self, node: str, name: str, timer_id: int) -> None:
        self.record(Event(self.now(), "timer_cancelled", node=node, text=name, timer_id=timer_id))

    def snapshot(self, node: Any) -> None:
        """Record the node's ``brief_state()`` if it has one and it changed."""
        brief = getattr(node, "brief_state", None)
        if brief is None:
            return
        state = brief()
        if not isinstance(state, dict):
            state = {"state": state}
        key = json.dumps(state, sort_keys=True, default=str)
        node_id = node.node_id
        if self._last_state.get(node_id) == key:
            return
        first = node_id not in self._last_state
        self._last_state[node_id] = key
        if first and not state:
            return  # an empty initial state is not worth a label
        self.record(Event(self.now(), "state", node=node_id, state=state))

    # --- views --------------------------------------------------------------

    def timeline(self, node: str | None = None, kinds: Sequence[str] | None = None,
                 t_range: tuple[int, int] | None = None) -> "Timeline":
        """Events in time order, optionally for one node, some kinds, or a window."""
        wanted = None
        if kinds is not None:
            wanted = set()
            for k in kinds:
                wanted.update(TIMER_KINDS if k == "timer" else (k,))
        events = [
            ev for ev in self.events
            if (node is None or node in ev.nodes)
            and (wanted is None or ev.kind in wanted)
            and (t_range is None or t_range[0] <= ev.t_ms <= t_range[1])
        ]
        return Timeline(events)

    def messages(self, frm: str | None = None, to: str | None = None) -> "MessageTable":
        """One row per message with its fate. Filter by sender and/or receiver."""
        rows: dict[int, MessageRow] = {}
        for ev in self.events:
            if ev.kind == "send":
                rows[ev.msg_id] = MessageRow(ev.msg_id, ev.t_ms, ev.frm, ev.to, ev.msg)
            elif ev.kind == "deliver":
                rows[ev.msg_id].deliveries.append((ev.t_ms, ev.delay_ms))
            elif ev.kind == "drop":
                rows[ev.msg_id].dropped_by.append(ev.rule)
        selected = [r for r in rows.values() if (frm is None or r.frm == frm) and (to is None or r.to == to)]
        return MessageTable(selected)

    def diagram(self, **options) -> "Diagram":
        """Space-time diagram as SVG. See ``dslabs.diagram.Diagram`` for options."""
        from .diagram import Diagram

        return Diagram(self, **options)

    def explain(self, node_id: str) -> "Explanation":
        """Everything one node sent and received, plus its own timeline."""
        return Explanation(node_id, self.messages(to=node_id), self.messages(frm=node_id), self.timeline(node=node_id))

    def print(self) -> None:
        print(self.timeline())

    # --- export -------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """The whole trace as plain data: ``{"format", "nodes", "end_ms", "events"}``."""
        end_ms = max([self.now()] + [ev.t_ms for ev in self.events])
        return {
            "format": "dslabs-trace/1",
            "nodes": list(self.nodes),
            "end_ms": end_ms,
            "events": [{k: v for k, v in asdict(ev).items() if v is not None} for ev in self.events],
        }

    def to_json(self, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def save_json(self, path: str | Path) -> Path:
        """Write the trace as JSON, for loading into the animated viewer (``dslabs/viewer.html``)."""
        path = Path(path)
        path.write_text(self.to_json(indent=1))
        return path

    def save_viewer(self, path: str | Path) -> Path:
        """Write a self-contained copy of the animated viewer with this trace embedded."""
        template = VIEWER.read_text()
        assert _VIEWER_PLACEHOLDER in template, "viewer.html has lost its trace placeholder"
        payload = self.to_json().replace("</", "<\\/")  # never let message text close the script tag
        path = Path(path)
        path.write_text(template.replace(_VIEWER_PLACEHOLDER, payload))
        return path


# --- views ----------------------------------------------------------------

_TABLE_STYLE = "font-family:monospace;font-size:12px;border-collapse:collapse;text-align:left"
_CELL_STYLE = "padding:1px 10px 1px 0;vertical-align:top;white-space:nowrap"


def _html_table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    head = "".join(f"<th style='{_CELL_STYLE}'>{escape(h)}</th>" for h in header)
    body = "".join(
        "<tr>" + "".join(f"<td style='{_CELL_STYLE}'>{escape(str(c))}</td>" for c in row) + "</tr>" for row in rows
    )
    return f"<table style='{_TABLE_STYLE}'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _text_table(header: Sequence[str], rows: Sequence[Sequence[str]], right_align: Sequence[int] = ()) -> str:
    cells = [[str(c) for c in row] for row in rows]
    widths = [max(len(c) for c in col) for col in zip(header, *cells)]
    lines = []
    for row in [list(header)] + cells:
        lines.append("  ".join(
            c.rjust(w) if i in right_align else c.ljust(w) for i, (c, w) in enumerate(zip(row, widths))
        ).rstrip())
    return "\n".join(lines)


class Timeline:
    def __init__(self, events: list[Event]) -> None:
        self.events = events

    def __iter__(self) -> Iterator[Event]:
        return iter(self.events)

    def __len__(self) -> int:
        return len(self.events)

    def __getitem__(self, i):
        return self.events[i]

    def __repr__(self) -> str:
        return str(self)

    def __str__(self) -> str:
        return "\n".join(str(ev) for ev in self.events) or "(no events)"

    def _repr_html_(self) -> str:
        if not self.events:
            return "<i>(no events)</i>"
        rows = [(f"{ev.t_ms} ms", ev.place, _KIND_LABEL[ev.kind], ev.detail) for ev in self.events]
        return _html_table(("time", "where", "event", "detail"), rows)


@dataclass
class MessageRow:
    msg_id: int
    sent_ms: int
    frm: str
    to: str
    msg: Message
    deliveries: list[tuple[int, int]] = field(default_factory=list)  # (delivered_at_ms, delay_ms)
    dropped_by: list[str] = field(default_factory=list)

    @property
    def delivered(self) -> bool:
        return bool(self.deliveries)

    @property
    def fate(self) -> str:
        parts = []
        for i, (t, delay) in enumerate(self.deliveries):
            parts.append(f"{'delivered' if i == 0 else 'again'} @ {t} ms (+{delay} ms)")
        if self.dropped_by:
            rules = ", ".join(dict.fromkeys(self.dropped_by))
            if self.deliveries:
                n = len(self.dropped_by)
                parts.append(f"{n} {'copy' if n == 1 else 'copies'} dropped by {rules}")
            else:
                parts.append(f"dropped by {rules}")
        return ", ".join(parts) or "in flight"


class MessageTable:
    _HEADER = ("#", "sent", "from", "to", "message", "outcome")

    def __init__(self, rows: list[MessageRow]) -> None:
        self.rows = rows

    def __iter__(self) -> Iterator[MessageRow]:
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, i):
        return self.rows[i]

    def _cells(self) -> list[tuple[str, ...]]:
        return [(f"#{r.msg_id}", f"{r.sent_ms} ms", r.frm, r.to, describe(r.msg), r.fate) for r in self.rows]

    def __repr__(self) -> str:
        return str(self)

    def __str__(self) -> str:
        return _text_table(self._HEADER, self._cells(), right_align=(0, 1)) if self.rows else "(no messages)"

    def _repr_html_(self) -> str:
        return _html_table(self._HEADER, self._cells()) if self.rows else "<i>(no messages)</i>"


class Explanation:
    def __init__(self, node_id: str, received: MessageTable, sent: MessageTable, timeline: Timeline) -> None:
        self.node_id = node_id
        self.received = received
        self.sent = sent
        self.timeline = timeline

    def __repr__(self) -> str:
        return str(self)

    def __str__(self) -> str:
        n = self.node_id
        return "\n".join([
            f"Messages to {n}", str(self.received), "",
            f"Messages from {n}", str(self.sent), "",
            f"Timeline of {n}", str(self.timeline),
        ])

    def _repr_html_(self) -> str:
        n = escape(self.node_id)
        return (
            f"<h4>Messages to {n}</h4>{self.received._repr_html_()}"
            f"<h4>Messages from {n}</h4>{self.sent._repr_html_()}"
            f"<h4>Timeline of {n}</h4>{self.timeline._repr_html_()}"
        )
