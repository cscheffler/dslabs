"""``Cluster``: build a cluster of one node class, drive it, and look at what happened.

    cluster = Cluster(NodeMultiLeader, 3, seed=1)   # nodes n1, n2, n3
    cluster.add_rule(drop(0.2))
    cluster.put("n2", "x", 1)
    cluster.run_until(2000)
    cluster.values("x")
    cluster.messages()      # one row per message and its fate
    cluster.diagram()       # space-time diagram (renders inline in a notebook)
    cluster.explain("n3")   # what one node saw

Or take it one event at a time: ``cluster.peek()`` says what happens next,
``cluster.step()`` runs it and shows everything it caused.

This is only the three simulator objects wired together; ``cluster.scheduler``,
``cluster.network``, and ``cluster.nodes`` are all there if you need them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Sequence

from .network import Rule, SimNetwork
from .protocols import Node
from .scheduler import Next, SimScheduler, Step
from .diagram import Diagram
from .trace import Explanation, MessageTable, Timeline, Trace


class Cluster:
    def __init__(self, node_class: Callable[..., Node], nodes: int | Sequence[str] = 3, seed: int = 0,
                 latency_ms: tuple[int, int] = (30, 80), verbose: bool = False) -> None:
        self.node_ids = [f"n{i}" for i in range(1, nodes + 1)] if isinstance(nodes, int) else list(nodes)
        self.scheduler = SimScheduler(verbose=verbose)
        self.network = SimNetwork(self.scheduler, seed=seed, latency_ms=latency_ms)
        self.trace: Trace = self.scheduler.trace
        self.nodes: dict[str, Node] = {}
        for nid in self.node_ids:
            node = node_class(nid, self.node_ids, self.network.endpoint(nid), self.scheduler)
            if not isinstance(node, Node):
                raise TypeError(
                    f"{type(node).__name__} does not implement the Node interface "
                    "(needs node_id, peers, on_message, client_put, client_get)"
                )
            self.network.register(nid, node.on_message)
            self.nodes[nid] = node

    def __getitem__(self, node_id: str) -> Node:
        return self.nodes[node_id]

    # --- clients ---------------------------------------------------------------

    def put(self, node_id: str, key: str, value: Any) -> None:
        """A client writes ``key = value`` at ``node_id``."""
        node = self.nodes[node_id]
        self.trace.client(node_id, f"put {key}={value}")
        node.client_put(key, value)
        self.trace.snapshot(node)

    def get(self, node_id: str, key: str) -> Any:
        """A client reads ``key`` at ``node_id``."""
        value = self.nodes[node_id].client_get(key)
        self.trace.client(node_id, f"get {key} -> {value}")
        return value

    def values(self, key: str) -> dict[str, Any]:
        """Every node's current value of ``key``. Not recorded as client traffic."""
        return {nid: node.client_get(key) for nid, node in self.nodes.items()}

    # --- time and faults -------------------------------------------------------

    def run_until(self, t_ms: int) -> None:
        self.scheduler.run_until(t_ms)

    def run_until_idle(self, max_ms: int = 60_000) -> bool:
        return self.scheduler.run_until_idle(max_ms)

    def pending(self) -> list[tuple[int, str]]:
        """What is in flight or armed, as ``(due_ms, description)``, soonest first."""
        return self.scheduler.pending()

    def peek(self) -> Next | None:
        """The next event, without running it."""
        return self.scheduler.peek()

    def step(self) -> Step:
        """Run exactly one event and show everything it caused. Falsy when idle."""
        return self.scheduler.step()

    def add_rule(self, rule: Rule) -> None:
        self.network.add_rule(rule)

    def remove_rule(self, rule: Rule) -> None:
        self.network.remove_rule(rule)

    @property
    def stats(self) -> dict[str, int]:
        return self.network.stats

    # --- what happened ---------------------------------------------------------

    def messages(self, **filters) -> MessageTable:
        return self.trace.messages(**filters)

    def timeline(self, **filters) -> Timeline:
        return self.trace.timeline(**filters)

    def diagram(self, **options) -> Diagram:
        return self.trace.diagram(**options)

    def explain(self, node_id: str) -> Explanation:
        return self.trace.explain(node_id)

    def save_json(self, path) -> Path:
        """Export the run for the animated viewer at ``dslabs/viewer.html``."""
        return self.trace.save_json(path)

    def save_viewer(self, path) -> Path:
        """Write a self-contained animated replay of the run as one HTML file."""
        return self.trace.save_viewer(path)
