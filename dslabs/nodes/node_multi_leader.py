from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

from dslabs.protocols import Message, Scheduler, Transport


@dataclass
class NodeMultiLeader:
    """Naive multi-leader replication.

    Any node accepts a write, applies it locally, and broadcasts it to every
    peer, which applies it on arrival. Nothing is retried, deduplicated, or
    ordered. This is the baseline the exercises start from.
    """

    node_id: str
    peers: list[str]
    transport: Transport
    scheduler: Scheduler
    # Key-value store
    store: dict[str, Any] = field(default_factory=dict)
    # Append-only log of everything delivered, in delivery order
    log: list[tuple[str, Any]] = field(default_factory=list)

    # Client-facing API
    def client_put(self, key: str, value: Any) -> None:
        self.receive_and_replicate(key, value)

    def client_get(self, key: str) -> Any:
        return self.store.get(key)

    # Node internals
    def receive_and_replicate(self, key: str, value: Any) -> None:
        self.receive(key, value)
        for peer in self.peers:
            if peer != self.node_id:
                self.transport.send(peer, {"type": "replicate", "key": key, "value": value})

    def receive(self, key: str, value: Any) -> None:
        # Received messages are delivered immediately
        self.deliver(key, value)

    def deliver(self, key: str, value: Any) -> None:
        """Apply a message to this node: update the store, append to the log."""
        self.store[key] = value
        self.log.append((key, value))

    # Network handler
    def on_message(self, msg: Message) -> None:
        if msg["type"] == "replicate":
            self.receive(msg["key"], msg["value"])
        else:
            raise ValueError(f"Unknown message type in {msg!r}")

    # What the trace and diagrams show as this node's state
    def brief_state(self) -> dict[str, Any]:
        return dict(self.store)
