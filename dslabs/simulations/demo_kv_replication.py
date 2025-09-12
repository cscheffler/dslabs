"""Toy KV replication demo: single-leader vs multi-leader.

This script uses the deterministic simulator to illustrate how read results
depend on replication timing under two trivial strategies:

- single-leader: all writes go to node n1; n1 forwards updates to others.
- multi-leader: any node can accept writes and broadcasts to others.

Workload: Client A writes x=1 to node n2; client B immediately reads x on n2.
We compare the immediate and eventual outcomes.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List

from dslabs.sim_scheduler import SimClock, SimScheduler
from dslabs.sim_network import SimNetwork, delay


@dataclass
class KvNode:
    node_id: str
    peers: List[str]
    transport: Any
    scheduler: Any
    mode: str  # "single" or "multi"
    leader_id: str = "n1"
    store: Dict[str, Any] = field(default_factory=dict)

    def brief_state(self) -> Dict[str, Any]:
        return {"id": self.node_id, "mode": self.mode, "kv": dict(self.store)}

    # Client-facing APIs (direct calls from the demo)
    def client_put(self, key: str, value: Any) -> None:
        # In single-leader mode, if a write hits a follower, forward to the leader.
        if self.mode == "single" and self.node_id != self.leader_id:
            self.transport.send(
                self.leader_id,
                {
                    "type": "client_put_forward",
                    "from": self.node_id,
                    "key": key,
                    "value": value,
                },
            )
            return

        # In single-leader mode, if a write hits the leader, store value, then replicate to others.
        # In multi-leader mode, accept locally, then replicate to others.
        self._store_and_replicate(key, value)

    def _store_and_replicate(self, key, value):
        self.store[key] = value
        for p in self.peers:
            if p != self.node_id:
                self.transport.send(
                    p,
                    {
                        "type": "replicate",
                        "from": self.node_id,
                        "key": key,
                        "value": value,
                    },
                )

    def client_get(self, key: str):
        return self.store.get(key)

    # Network handler
    def on_message(self, msg: Dict[str, Any]) -> None:
        t = msg.get("type")
        if t == "client_put_forward":
            # Only the leader handles forwarded client writes in single-leader.
            if self.mode == "single" and self.node_id == self.leader_id:
                self._store_and_replicate(msg["key"], msg["value"])
        elif t == "replicate":
            # Apply incoming replication from any peer.
            self.store[msg["key"]] = msg["value"]
        else:
            raise ValueError(f"Unknown type in message {msg!r}")


def run_scenario(mode: str):
    clock = SimClock()
    scheduler = SimScheduler(clock)
    network = SimNetwork(scheduler, seed=123)

    # Create the nodes on the network
    node_ids = ["n1", "n2", "n3"]
    nodes = {}
    for nid in node_ids:
        # Create a node object
        node = KvNode(nid, node_ids, transport=network, scheduler=scheduler, mode=mode)
        nodes[nid] = node
        # "Registration": Tell the network object how to deliver a message to a node object
        network.register(nid, node.on_message)

    # Add realistic network latency to highlight stale reads immediately after a write
    network.add_rule(delay(40, 120))

    # Workload: A writes to n2, B immediately reads from n2
    nodes["n2"].client_put("x", 1)
    immediate = nodes["n2"].client_get("x")

    # Let time pass until replication messages likely delivered (2 seconds)
    for _ in range(200):
        scheduler.run_due()
        clock.advance(10)
    eventual = nodes["n2"].client_get("x")

    return immediate, eventual


def main():
    for mode in ("single", "multi"):
        immediate, eventual = run_scenario(mode)
        print(
            {
                "strategy": mode,
                "read_immediately_on_n2": immediate,
                "read_after_replication_on_n2": eventual,
            }
        )


if __name__ == "__main__":
    main()
