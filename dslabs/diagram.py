"""Space-time diagrams of a trace, as plain SVG.

One horizontal lifeline per node, time left to right and drawn to scale. Each
message is an arrow from its send point to its delivery point, so latency is
the arrow's horizontal reach and reordering shows as one arrow overtaking
another. Dropped messages end in a red cross partway across. Client requests,
timers, node state, and notes sit on the lifelines. Hover over anything for
the full detail.

In a notebook, a ``Diagram`` as the last expression of a cell renders inline.
``diagram.save("run.svg")`` writes it out for slides.
"""

from __future__ import annotations

import itertools
import math
from html import escape
from pathlib import Path
from typing import Sequence

from .trace import Event, Trace, describe, describe_state

COLOR = {
    "deliver": "#2b6cb0",
    "duplicate": "#dd6b20",
    "drop": "#c53030",
    "client": "#2f855a",
    "timer": "#805ad5",
    "state": "#1a202c",
    "note": "#4a5568",
    "lifeline": "#cbd5e0",
    "axis": "#718096",
    "cancel": "#a0aec0",
}
LEFT, RIGHT, TOP, BOTTOM = 72, 30, 44, 56
ROW_H = 120
LABEL_MAX = 30
FONT = "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"

_ids = itertools.count(1)


class Diagram:
    """Render a trace as SVG.

    Options:
    - ``nodes``: lifelines to draw, in order (default: every node in the trace)
    - ``t_range``: ``(start_ms, end_ms)`` window (default: the whole run)
    - ``width``: pixel width (default 960)
    - ``labels``, ``timers``, ``notes``, ``states``: toggle each layer
    """

    def __init__(self, trace: Trace, nodes: Sequence[str] | None = None, t_range: tuple[int, int] | None = None,
                 width: int = 960, labels: bool = True, timers: bool = True, notes: bool = True,
                 states: bool = True) -> None:
        self.svg = _render(trace, nodes, t_range, width, labels, timers, notes, states)

    def _repr_svg_(self) -> str:
        return self.svg

    def __str__(self) -> str:
        return self.svg

    def save(self, path: str) -> None:
        Path(path).write_text(self.svg)


def _ticks(t0: int, t1: int, max_ticks: int = 10) -> tuple[list[int], int]:
    span = max(t1 - t0, 1)
    step = 1
    for magnitude in (1, 10, 100, 1_000, 10_000, 100_000, 1_000_000):
        for m in (1, 2, 5):
            step = m * magnitude
            if span / step <= max_ticks:
                break
        else:
            continue
        break
    first = math.ceil(t0 / step) * step
    return list(range(first, t1 + 1, step)), step


def _tick_label(t: int, step: int) -> str:
    return f"{t / 1000:g} s" if step >= 1000 else f"{t} ms"


def _short(text: str, limit: int = LABEL_MAX) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _text(x: float, y: float, s: str, fill: str, size: int = 10, anchor: str = "middle",
          italic: bool = False, bold: bool = False, title: str | None = None) -> str:
    style = "font-style:italic;" if italic else ""
    style += "font-weight:bold;" if bold else ""
    t = f"<title>{escape(title)}</title>" if title else ""
    return (f"<text x='{x:.1f}' y='{y:.1f}' text-anchor='{anchor}' font-size='{size}' fill='{fill}' "
            f"class='dsl-lbl' style='{style}'>{t}{escape(s)}</text>")


def _render(trace: Trace, nodes, t_range, width, labels, timers, notes, states) -> str:
    nodes = list(nodes) if nodes else list(trace.nodes)
    node_set = set(nodes)
    events = [ev for ev in trace.events if ev.nodes and all(n in node_set for n in ev.nodes)]
    sends = {ev.msg_id: ev for ev in trace.events if ev.kind == "send"}

    if t_range is not None:
        t0, t1 = t_range
    else:
        t0 = 0
        t1 = max([ev.t_ms for ev in events] + [ev.t_ms + ev.delay_ms for ev in events if ev.kind == "drop"] + [0])
        t1 += max(1, t1 // 12)  # room for labels at the right edge
    span = max(t1 - t0, 1)
    plot_w = width - LEFT - RIGHT
    height = TOP + 36 + max(len(nodes) - 1, 0) * ROW_H + 64 + BOTTOM
    uid = f"dsl{next(_ids)}"

    def x(t: float) -> float:
        return LEFT + (t - t0) / span * plot_w

    y = {nid: TOP + 36 + i * ROW_H for i, nid in enumerate(nodes)}

    def in_window(ev: Event) -> bool:
        if ev.kind == "deliver":
            return sends[ev.msg_id].t_ms <= t1 and ev.t_ms >= t0
        if ev.kind == "drop":
            return sends[ev.msg_id].t_ms <= t1 and ev.t_ms + ev.delay_ms >= t0
        return t0 <= ev.t_ms <= t1

    events = [ev for ev in events if in_window(ev)]

    out = [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' viewBox='0 0 {width} {height}' "
        f"font-family=\"{FONT}\" font-size='11'>",
        "<style>.dsl-lbl{paint-order:stroke;stroke:#ffffff;stroke-width:3px;stroke-linejoin:round}</style>",
        "<defs>",
    ]
    for kind in ("deliver", "duplicate"):
        out.append(
            f"<marker id='{uid}-{kind}' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='7' markerHeight='7' "
            f"orient='auto'><path d='M0,0 L10,5 L0,10 z' fill='{COLOR[kind]}'/></marker>"
        )
    out.append(f"<clipPath id='{uid}-clip'><rect x='{LEFT - 6}' y='{TOP - 4}' width='{plot_w + 12}' "
               f"height='{height - TOP - BOTTOM + 8}'/></clipPath>")
    out.append("</defs>")
    out.append(f"<rect width='{width}' height='{height}' fill='#ffffff'/>")

    if not nodes:
        out.append(_text(width / 2, height / 2, "nothing has happened yet", COLOR["axis"], size=12))
        out.append("</svg>")
        return "\n".join(out)

    # Time axis
    axis_y = TOP - 14
    out.append(f"<line x1='{LEFT}' y1='{axis_y}' x2='{width - RIGHT}' y2='{axis_y}' stroke='{COLOR['axis']}'/>")
    ticks, step = _ticks(t0, t1)
    for t in ticks:
        out.append(f"<line x1='{x(t):.1f}' y1='{axis_y - 4}' x2='{x(t):.1f}' y2='{axis_y + 4}' stroke='{COLOR['axis']}'/>")
        out.append(_text(x(t), axis_y - 8, _tick_label(t, step), COLOR["axis"], size=10))

    # Lifelines
    for nid in nodes:
        out.append(f"<line x1='{LEFT}' y1='{y[nid]}' x2='{width - RIGHT}' y2='{y[nid]}' stroke='{COLOR['lifeline']}' stroke-width='1.5'/>")
        out.append(_text(LEFT - 12, y[nid] + 4, nid, COLOR["state"], size=12, anchor="end", bold=True))

    out.append(f"<g clip-path='url(#{uid}-clip)'>")

    # Timers: join set/fired/cancelled by id, assign lanes per node so overlapping timers stack
    if timers:
        spans: dict[int, dict] = {}
        for ev in trace.events:
            if ev.kind == "timer_set" and ev.node in node_set:
                spans[ev.timer_id] = {"node": ev.node, "name": ev.text, "start": ev.t_ms, "due": ev.due_ms, "end": None, "how": None}
            elif ev.kind in ("timer_fired", "timer_cancelled") and ev.timer_id in spans:
                spans[ev.timer_id].update(end=ev.t_ms, how=ev.kind)
        lanes_end: dict[str, list[int]] = {nid: [] for nid in nodes}
        for sp in sorted(spans.values(), key=lambda s: (s["start"], s["due"])):
            end = sp["end"] if sp["end"] is not None else t1
            if end < t0 or sp["start"] > t1:
                continue
            lanes = lanes_end[sp["node"]]
            lane = next((i for i, e in enumerate(lanes) if e <= sp["start"]), None)
            if lane is None:
                lanes.append(end)
                lane = len(lanes) - 1
            else:
                lanes[lane] = end
            ly = y[sp["node"]] + 12 + (lane % 4) * 5
            x1, x2 = x(sp["start"]), x(end)
            how = {"timer_fired": f"fired @ {sp['end']} ms", "timer_cancelled": f"cancelled @ {sp['end']} ms"}.get(sp["how"], "still pending")
            title = f"timer {sp['name']} set @ {sp['start']} ms for {sp['due']} ms, {how}"
            out.append(f"<line x1='{x1:.1f}' y1='{ly}' x2='{x2:.1f}' y2='{ly}' stroke='{COLOR['timer']}' "
                       f"stroke-dasharray='2 3'><title>{escape(title)}</title></line>")
            if sp["how"] == "timer_fired":
                out.append(f"<path d='M{x2:.1f},{ly - 4} l4,7 l-8,0 z' fill='{COLOR['timer']}'><title>{escape(title)}</title></path>")
                if labels and sp["name"] != "<lambda>":
                    out.append(_text(x2 + 6, ly + 3.5, sp["name"], COLOR["timer"], size=9, anchor="start", title=title))
            elif sp["how"] == "timer_cancelled":
                out.append(f"<path d='M{x2 - 3:.1f},{ly - 3} l6,6 M{x2 + 3:.1f},{ly - 3} l-6,6' stroke='{COLOR['cancel']}' "
                           f"stroke-width='1.5'><title>{escape(title)}</title></path>")

    # Messages
    seen_deliveries: dict[int, int] = {}
    labelled_drops: set[tuple[str, int, str]] = set()  # one label per dropped broadcast
    for ev in events:
        if ev.kind == "send":
            out.append(f"<circle cx='{x(ev.t_ms):.1f}' cy='{y[ev.frm]}' r='2.5' fill='{COLOR['deliver']}'/>")
        elif ev.kind == "deliver" and ev.frm != ev.to:
            s = sends[ev.msg_id]
            n = seen_deliveries[ev.msg_id] = seen_deliveries.get(ev.msg_id, 0) + 1
            kind = "duplicate" if n > 1 else "deliver"
            x1, y1, x2, y2 = x(s.t_ms), y[ev.frm], x(ev.t_ms), y[ev.to]
            title = (f"#{ev.msg_id} {ev.frm} -> {ev.to}: {describe(ev.msg)}\nsent @ {s.t_ms} ms, "
                     f"{'delivered again' if n > 1 else 'delivered'} @ {ev.t_ms} ms (+{ev.delay_ms} ms)")
            out.append(f"<line x1='{x1:.1f}' y1='{y1}' x2='{x2:.1f}' y2='{y2}' stroke='{COLOR[kind]}' stroke-width='1.5' "
                       f"marker-end='url(#{uid}-{kind})'><title>{escape(title)}</title></line>")
            if labels:
                out.append(_text(x2 + 5, y2 - 5, _short(describe(ev.msg)), COLOR[kind], anchor="start", title=title))
        elif ev.kind == "drop" and ev.frm != ev.to:
            s = sends[ev.msg_id]
            x1, y1 = x(s.t_ms), y[ev.frm]
            ex, ey = x(s.t_ms + ev.delay_ms), y[ev.to]
            # Stop the stub half a row gap along its intended path, so it never reaches another lifeline
            frac = 0.5 * ROW_H / abs(ey - y1) if ey != y1 else 0.5
            px, py = x1 + (ex - x1) * frac, y1 + (ey - y1) * frac
            title = f"#{ev.msg_id} {ev.frm} -> {ev.to}: {describe(ev.msg)}\nsent @ {s.t_ms} ms, dropped by {ev.rule}"
            out.append(f"<line x1='{x1:.1f}' y1='{y1}' x2='{px:.1f}' y2='{py:.1f}' stroke='{COLOR['drop']}' stroke-width='1.5' "
                       f"stroke-dasharray='4 3'><title>{escape(title)}</title></line>")
            out.append(f"<path d='M{px - 4:.1f},{py - 4:.1f} l8,8 M{px + 4:.1f},{py - 4:.1f} l-8,8' stroke='{COLOR['drop']}' "
                       f"stroke-width='2'><title>{escape(title)}</title></path>")
            key = (ev.frm, s.t_ms, describe(ev.msg))
            if labels and key not in labelled_drops:
                labelled_drops.add(key)
                out.append(_text(px + 8, py + 3.5, _short(describe(ev.msg)), COLOR["drop"], anchor="start", title=title))

    # Client requests, state, notes
    for ev in events:
        if ev.kind == "client":
            cx, cy = x(ev.t_ms), y[ev.node]
            out.append(f"<circle cx='{cx:.1f}' cy='{cy}' r='4' fill='{COLOR['client']}'><title>{escape(f'{ev.t_ms} ms: {ev.text}')}</title></circle>")
            if labels:
                out.append(_text(cx - 4, cy - 15, ev.text, COLOR["client"], anchor="start", title=f"{ev.t_ms} ms: {ev.text}"))
        elif ev.kind == "state" and states:
            cx, cy = x(ev.t_ms), y[ev.node]
            out.append(f"<line x1='{cx:.1f}' y1='{cy + 3}' x2='{cx:.1f}' y2='{cy + 30}' stroke='{COLOR['lifeline']}'/>")
            out.append(_text(cx + 3, cy + 40, _short(describe_state(ev.state)), COLOR["state"], anchor="start",
                             title=f"{ev.t_ms} ms: {describe_state(ev.state)}"))
        elif ev.kind == "note" and notes:
            cx, cy = x(ev.t_ms), y[ev.node]
            out.append(_text(cx + 3, cy + 54, _short(ev.text, 60), COLOR["note"], anchor="start", italic=True,
                             title=f"{ev.t_ms} ms: {ev.text}"))

    out.append("</g>")

    # Legend
    ly = height - 18
    lx = LEFT
    legend = []
    def item(shape: str, shape_w: int, label: str, color: str) -> None:
        nonlocal lx
        legend.append(shape.replace("LX", f"{lx}"))
        legend.append(_text(lx + shape_w + 5, ly + 3.5, label, color, size=10, anchor="start"))
        lx += shape_w + 5 + len(label) * 6.2 + 18
    item(f"<line x1='LX' y1='{ly}' x2='{lx + 26}' y2='{ly}' stroke='{COLOR['deliver']}' stroke-width='1.5' marker-end='url(#{uid}-deliver)'/>", 26, "delivered", COLOR["deliver"])
    item(f"<line x1='LX' y1='{ly}' x2='{lx + 26}' y2='{ly}' stroke='{COLOR['duplicate']}' stroke-width='1.5' marker-end='url(#{uid}-duplicate)'/>", 26, "duplicate", COLOR["duplicate"])
    item(f"<g><line x1='LX' y1='{ly}' x2='{lx + 18}' y2='{ly}' stroke='{COLOR['drop']}' stroke-width='1.5' stroke-dasharray='4 3'/>"
         f"<path d='M{lx + 15},{ly - 4} l8,8 M{lx + 23},{ly - 4} l-8,8' stroke='{COLOR['drop']}' stroke-width='2'/></g>", 26, "dropped", COLOR["drop"])
    item(f"<circle cx='LX' cy='{ly}' r='4' fill='{COLOR['client']}' transform='translate(4,0)'/>", 8, "client request", COLOR["client"])
    item(f"<line x1='LX' y1='{ly}' x2='{lx + 26}' y2='{ly}' stroke='{COLOR['timer']}' stroke-dasharray='2 3'/>", 26, "timer", COLOR["timer"])
    item(f"<text x='LX' y='{ly + 3.5}' font-size='10' fill='{COLOR['state']}'>x=1</text>", 20, "node state", COLOR["state"])
    item(f"<text x='LX' y='{ly + 3.5}' font-size='10' fill='{COLOR['note']}' style='font-style:italic'>note</text>", 22, "note", COLOR["note"])
    out.extend(legend)

    out.append("</svg>")
    return "\n".join(out)
