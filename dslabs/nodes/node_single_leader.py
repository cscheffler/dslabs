from dataclasses import dataclass, field
from typing import Dict, Any, List, Tuple, Set


@dataclass
class NodeSingleLeader:
    """
    Single-leader nodes. Followers forward client messages to the leader. The leader assigns a
    sequence number, stores a message, and replicates to all other nodes.
    """

    node_id: str
    peers: List[str]
    transport: Any
    scheduler: Any
    store: Dict[str, Any] = field(default_factory=dict)
    log: List[Tuple[str, Any]] = field(default_factory=list)
    buffer: List[Tuple[int, str, Any]] = field(default_factory=list)

    def brief_state(self):
        return {"id": self.node_id, "kv": dict(self.store)}

    # Client-facing APIs (direct calls from the demo)
    def client_put(self, key, value):
        # Accept locally, then replicate to others.
        if self.node_id == self.peers[0]:
            self.leader_receive(key, value)
        else:
            # Not the leader; forward the message
            self.transport.send(
                self.peers[0],
                {
                    "type": "forward_to_leader",
                    "from": self.node_id,
                    "key": key,
                    "value": value,
                },
            )

    def client_get(self, key):
        return self.store.get(key)

    # Node internal handlers
    def leader_receive(self, key, value):
        """
        Create sequence number.
        Deliver the message locally.
        Replicate the message.
        """
        seq = len(self.log)
        self.deliver(seq, key, value)
        self.replicate(seq, key, value)

    def replicate(self, seq, key, value):
        # Broadcast to all peers
        for peer in self.peers:
            if peer != self.node_id:
                self.transport.send(
                    peer,
                    {
                        "type": "replicate",
                        "from": self.node_id,
                        "seq": seq,
                        "key": key,
                        "value": value,
                    },
                )

    def receive(self, seq, key, value):
        self.buffer.append((seq, key, value))
        self.buffer.sort()
        if self.buffer[0][0] == len(self.log):
            self.deliver(*self.buffer.pop(0))
        # 10 second timeout for delivering messages in the buffer
        if hasattr(self, "cancel_clear"):
            # We received another message, so reset the timer for clearing the local buffer
            self.cancel_clear()
        self.cancel_clear = self.scheduler.call_later(10_000, self.clear_buffer)

    def clear_buffer(self):
        for msg in self.buffer:
            self.deliver(*msg)

    def deliver(self, seq, key, value):
        """
        Deliver the message to this node.
         1. Update the key-value store
         2. Append the delivery to the permanent log
        """
        self.store[key] = value
        self.log.append((seq, key, value))

    # Network handler
    def on_message(self, msg):
        typ = msg.get("type")
        if typ == "forward_to_leader":
            self.leader_receive(msg["key"], msg["value"])
        elif typ == "replicate":
            # Apply incoming replication from any peer.
            self.receive(msg["seq"], msg["key"], msg["value"])
        else:
            raise ValueError(f"Unknown type in message {msg!r}")
