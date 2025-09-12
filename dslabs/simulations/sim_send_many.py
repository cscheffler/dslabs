from dslabs import scheduler, network
from dslabs.nodes import NodeMultiLeader

import random


class SimSendMany:
    """
    Send a write messages to nodes with a short delay between consecutive messages. The network
    might drop or delay some messages.
    """

    def __init__(
        self,
        node_class,
        num_nodes=10,
        num_messages=10,
        message_delay=10,
        drop_prob=0,
        random_seed=None,
    ):
        self.params = {
            "node_class": node_class,
            "num_nodes": num_nodes,
            "num_messages": num_messages,
            "message_delay": message_delay,
            "drop_prob": drop_prob,
            "random_seed": random_seed if random_seed else random.randint(0, 2**128),
        }

        self.clock = scheduler.SimClock()
        self.scheduler = scheduler.SimScheduler(self.clock)

        # Create a network with realistic latency to highlight stale reads immediately after a
        # write, and a user-defined message drop probability
        self.network = network.SimNetwork(
            self.scheduler, seed=self.params["random_seed"]
        )
        self.network.add_rule(network.delay(40, 120))
        self.network.add_rule(network.drop(self.params["drop_prob"]))

        # Create the nodes on the network
        node_ids = [f"n{i}" for i in range(self.params["num_nodes"])]
        self.nodes = {}
        for nid in node_ids:
            # Create a node object
            node = self.params["node_class"](
                nid, node_ids, transport=self.network, scheduler=self.scheduler
            )
            self.nodes[nid] = node
            # "Registration": Tell the network object how to deliver a message to a node object
            self.network.register(nid, node.on_message)

        self.results = {}

    def run_scenario(self):
        # Schedule all client puts
        node_ids = list(self.nodes.keys())
        for i in range(self.params["num_messages"]):
            node = self.nodes[random.choice(node_ids)]
            msg_value = i
            at = i * self.params["message_delay"]

            def event(node=node, value=msg_value):
                node.client_put("x", value)

            self.scheduler.call_later(at, event)

        # Let time pass until replication messages likely delivered (2 seconds)
        for _ in range(2000):
            self.scheduler.run_due()
            self.clock.advance(10)
        self.results["stored_values"] = {
            k: n.client_get("x") for k, n in self.nodes.items()
        }


def main():
    sim = SimSendMany(
        NodeMultiLeader, num_messages=10, message_delay=1000, drop_prob=0.5
    )
    sim.run_scenario()
    print(sim.network.stats)
    print(sim.results)


if __name__ == "__main__":
    main()
