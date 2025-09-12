from dataclasses import dataclass, field
from typing import Dict, Any, List, Tuple


@dataclass
class NodeMultiLeader:
    """
    Multi-leader nodes. Any node can accept writes and broadcasts to others.
    """

    node_id: str
    peers: List[str]
    transport: Any
    scheduler: Any
    store: Dict[str, Any] = field(default_factory=dict)
    log: List[Tuple[str, Any]] = field(default_factory=list)

    def brief_state(self):
        return {"id": self.node_id, "kv": dict(self.store)}

    # Client-facing APIs (direct calls from the demo)
    def client_put(self, key, value):
        # Accept locally, then replicate to others.
        self.receive_and_replicate(key, value)

    def client_get(self, key):
        return self.store.get(key)

    # Node internal handlers
    def receive_and_replicate(self, key, value):
        self.receive(key, value)
        # Broadcast to all peers
        for peer in self.peers:
            if peer != self.node_id:
                self.transport.send(
                    peer,
                    {
                        "type": "replicate",
                        "from": self.node_id,
                        "key": key,
                        "value": value,
                    },
                )

    def receive(self, key, value):
        # Received messages are delivered immediately
        self.deliver(key, value)

    def deliver(self, key, value):
        """
        Deliver the message to this node.
         1. Update the key-value store
         2. Append the delivery to the permanent log
        """
        self.store[key] = value
        self.log.append((key, value))

    # Network handler
    def on_message(self, msg):
        typ = msg.get("type")
        if typ == "replicate":
            # Apply incoming replication from any peer.
            self.receive(msg["key"], msg["value"])
        else:
            raise ValueError(f"Unknown type in message {msg!r}")
