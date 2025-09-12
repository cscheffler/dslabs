from dataclasses import dataclass, field
from typing import Dict, Any, List, Tuple, Set
import uuid


@dataclass
class NodeEagerBroadcast:
    """
    Each node broadcasts all received messages to all other nodes. Use a cache
    to deduplicate messages.
    """

    node_id: str
    peers: List[str]
    transport: Any
    scheduler: Any
    store: Dict[str, Any] = field(default_factory=dict)
    log: List[Tuple[str, str, Any]] = field(default_factory=list)
    # Remember which messages we have already received
    cache: Set[str] = field(default_factory=set)

    def brief_state(self):
        return {"id": self.node_id, "kv": dict(self.store)}

    # Client-facing APIs (direct calls from the demo)
    def client_put(self, key, value):
        # Generate a unique id for this message (so we can dedup later)
        uid = str(uuid.uuid4())
        self.receive_and_replicate(uid, key, value)

    def client_get(self, key):
        return self.store.get(key)

    # Node internal handlers
    def receive_and_replicate(self, uid, key, value):
        if uid not in self.cache:
            self.receive(uid, key, value)
            # Broadcast to all peers
            for peer in self.peers:
                if peer != self.node_id:
                    self.transport.send(
                        peer,
                        {
                            "type": "replicate",
                            "from": self.node_id,
                            "uid": uid,
                            "key": key,
                            "value": value,
                        },
                    )

    def receive(self, uid, key, value):
        self.cache.add(uid)
        # Received messages are delivered immediately
        self.deliver(uid, key, value)

    def deliver(self, uid, key, value):
        """
        Deliver the message to this node.
         1. Update the key-value store
         2. Append the delivery to the permanent log
        """
        self.store[key] = value
        self.log.append((uid, key, value))

    # Network handler
    def on_message(self, msg):
        typ = msg.get("type")
        if typ == "replicate":
            # Apply incoming replication from any peer.
            self.receive_and_replicate(msg["uid"], msg["key"], msg["value"])
        else:
            raise ValueError(f"Unknown type in message {msg!r}")
