"""A small, deterministic network simulator with fault injection.

Key ideas:

- Messages are scheduled as (deliver_at_ms, payload) pairs called an Action.
- To simulate network errors, you can register transformation rules (drop,
  delay, duplicate, partition) that rewrite the pending Action list for each
  send.
- Delivery uses the simulated clock and scheduler, so tests can advance time
  and deterministically observe behavior.
"""

import random
from typing import Callable, Dict, Any, List, Tuple, Set
from .scheduler import SimScheduler

Action = List[Tuple[int, Dict[str, Any]]]


class SimNetwork:
    """Event-driven simulated network.

    - `register(node_id, handler)`: Register a per-node receive handler. The
      handler is used to deliver a message to a node.
    - `add_rule(rule)`: Install a communication rule in the network, used for
      simulation latency, network partitions, etc.
    - `send(to, msg)`: schedule delivery of a message to a node, applying
      all rules to the initial Action list.

    The random seed controls base delays to make runs reproducible.
    """

    def __init__(self, scheduler: SimScheduler, seed: int = 0):
        self.scheduler = scheduler
        self.handlers: Dict[str, Callable[[Dict[str, Any]], None]] = {}
        self.rules: List[Callable[[str, str, Dict[str, Any], Action], Action]] = []
        self.rng = random.Random(seed)
        self.stats = {
            "dropped_messages": 0,
            "delivered_messages": 0,
            "duplicated_messages": 0,
        }

    def register(self, node_id: str, handler: Callable[[Dict[str, Any]], None]) -> None:
        """Associate `node_id` with a message handler function.

        Handlers receive the message dict as delivered.
        """
        self.handlers[node_id] = handler

    def add_rule(self, rule) -> None:
        """Append a message transformation rule to the pipeline.

        Rules are callables that modify each action in a list in some way. The
        rule is called with (from, to, message, actions) so that actions can be
        modified based on the from and to nodes, for example, if the network is
        partitioned.
        """
        self.rules.append(rule)

    def send(self, to: str, msg: Dict[str, Any]) -> None:
        """Schedule delivery of `msg` to `to`, applying all rules.

        A small random base delay is added before rules run to avoid lockstep
        behavior. Rules can introduce more delay, drops, duplicates, etc.
        """
        base_delay = 30 + int(self.rng.random() * 50)
        actions: Action = [(base_delay, msg)]
        frm = msg.get("from", "?")
        for rule in self.rules:
            actions = rule(frm, to, msg, actions, stats=self.stats)
        for at, payload in actions:

            def deliver(to=to, payload=payload):
                h = self.handlers.get(to)
                if h:
                    h(payload)
                self.stats["delivered_messages"] += 1

            self.scheduler.call_later(at, deliver)


def drop(p=0.1):
    """Return a rule that drops each pending delivery with prob `p`."""
    import random

    def _rule(frm, to, msg, actions: Action, stats=None):
        out = [a for a in actions if random.random() > p]
        if stats is not None:
            stats["dropped_messages"] += len(actions) - len(out)
        return out

    return _rule


def delay(min_ms=100, max_ms=300):
    """Return a rule that adds a random delay in [min_ms, max_ms]."""
    import random

    def _rule(frm, to, msg, actions: Action, stats=None):
        out = []
        for at, payload in actions:
            extra = random.randint(min_ms, max_ms)
            out.append((at + extra, payload))
        return out

    return _rule


def duplicate(p=0.05):
    """Return a rule that duplicates deliveries with prob `p`."""
    import random

    def _rule(frm, to, msg, actions: Action, stats=None):
        out = list(actions)
        for at, payload in actions:
            if random.random() < p:
                out.append((at + 1, payload.copy()))
        if stats is not None:
            stats["duplicated_messages"] += len(out) - len(actions)
        return out

    return _rule


def partition(cut: Set[Tuple[str, str]]):
    """Return a rule that blocks traffic for pairs in `cut`.

    The `cut` set contains undirected pairs like (`n1`,`n2`).
    """

    def _rule(frm, to, msg, actions: Action, stats=None):
        out = [] if (frm, to) in cut or (to, frm) in cut else actions
        if stats is not None:
            stats["dropped_messages"] += len(actions) - len(out)
        return out

    return _rule
