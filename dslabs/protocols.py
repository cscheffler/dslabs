"""Interfaces that separate node algorithms from the machinery that runs them.

A node only ever touches two things it does not own:

- a ``Transport``, to send messages to other nodes, and
- a ``Scheduler``, to read the clock and to schedule timers.

Keep algorithm code free of anything else (no threads, sleeps, sockets, or
real time) and it will run unchanged in the deterministic simulator or in any
future real runtime.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Protocol, runtime_checkable

# Messages are plain, JSON-serialisable dicts. The transport stamps the sender's
# id into ``msg["from"]`` on every send, so a receiver always knows who sent it.
Message = Dict[str, Any]

# Returned by ``Scheduler.call_later``. Call it to cancel the pending callback.
Cancel = Callable[[], None]


class Transport(Protocol):
    """Sends messages on behalf of one node.

    Sending is fire-and-forget: there is no return value and no delivery
    guarantee. Depending on the network, a message may be delayed, dropped,
    duplicated, or reordered. Reliability, if you need it, is the algorithm's
    job.
    """

    def send(self, to: str, msg: Message) -> None:
        """Send ``msg`` to the node called ``to``."""
        ...

    def note(self, text: str) -> None:
        """Write a note onto this node's timeline, for the trace and diagrams.

        Debugging only: it must never affect what the algorithm does.
        """
        ...


class Scheduler(Protocol):
    """Clock and timers."""

    def now_ms(self) -> int:
        """Current time in milliseconds."""
        ...

    def call_later(self, ms: int, cb: Callable[[], None]) -> Cancel:
        """Run ``cb()`` after ``ms`` milliseconds. Returns a function that cancels it."""
        ...


@runtime_checkable
class Node(Protocol):
    """What the simulation expects from a node class.

    Node classes are constructed as ``NodeClass(node_id, peers, transport,
    scheduler)``, where ``peers`` lists every node id in the cluster, including
    this node's own id. A ``@dataclass`` with those four fields, in that order,
    satisfies the constructor; see ``dslabs.nodes.NodeMultiLeader``.

    Optionally, a node may also define ``brief_state() -> dict``. If it does,
    the simulator snapshots it after every delivery, timer, and client request
    and shows changes on the node's timeline and in diagrams.
    """

    node_id: str
    peers: list[str]

    def on_message(self, msg: Message) -> None:
        """Called by the network when a message is delivered to this node."""
        ...

    def client_put(self, key: str, value: Any) -> None:
        """A client asks this node to write ``key = value``."""
        ...

    def client_get(self, key: str) -> Any:
        """A client asks this node for its current value of ``key``."""
        ...
