import random

import pytest

from dslabs.simulations.sim_send_many import SimSendMany
from dslabs.nodes import (
    NodeMultiLeader,  # Passes the first unit test, but fails the rest
    NodeEagerBroadcast,  # Passes tests 1 and 2 only
    NodeSingleLeader,  # Passes tests 1 and 3 only
    NodeTotalOrderEagerBroadcast,  # Passes all tests except the last one, which we always expect to fail
)


def _run(seed: int, **kwargs):
    random.seed(seed)
    sim = SimSendMany(NodeTotalOrderEagerBroadcast, random_seed=seed, **kwargs)
    sim.run_scenario()
    return sim


def test_converges_without_drops_when_spaced_out():
    """
    With no drops and a large inter-message delay, all nodes should converge to
    the last written value for key 'x'. This serves as a baseline passing test.
    """
    num_messages = 10
    sim = _run(
        seed=7,
        num_nodes=5,
        num_messages=num_messages,
        message_delay=1000,  # >> max network delay; preserves global order
        drop_prob=0.0,
    )
    values = sim.results["stored_values"]
    assert set(values.values()) == {num_messages - 1}


def test_fails_with_drops_on_last_write_replication():
    """
    Intentionally failing test: With a high drop probability, the last write is
    unlikely to replicate to every node, so expecting universal convergence to
    the last value should fail. Students will implement replication to fix this.
    """
    num_messages = 12
    sim = _run(
        seed=12345,
        num_nodes=8,
        num_messages=num_messages,
        message_delay=1000,
        drop_prob=0.5,  # high drop rate
    )
    values = sim.results["stored_values"]
    # Strict requirement (expected to FAIL initially): everyone has the final value
    assert set(values.values()) == {num_messages - 1}


def test_fails_due_to_reordering_with_fast_client_rate():
    """
    Intentionally failing test: Even without drops, a fast client rate plus
    variable network delay can cause older writes to arrive after newer ones,
    leaving some nodes with stale final values.
    """
    num_messages = 20
    sim = _run(
        seed=42,
        num_nodes=6,
        num_messages=num_messages,
        message_delay=10,  # << network delay range; invites reordering
        drop_prob=0.0,  # we are _not_ dropping messages
    )
    values = sim.results["stored_values"]
    # Strict requirement (expected to FAIL initially): everyone has the final value
    assert len(set(values.values())) == 1


@pytest.mark.xfail
def test_fails_due_to_non_global_order():
    """
    Intentionally failing test: Even without drops, a fast client rate plus
    variable network delay can cause older writes to arrive after newer ones,
    leaving some nodes with stale final values.
    """
    num_messages = 20
    sim = _run(
        seed=42,
        num_nodes=6,
        num_messages=num_messages,
        message_delay=10,  # << network delay range; invites reordering
        drop_prob=0.0,  # we are _not_ dropping messages
    )
    values = sim.results["stored_values"]
    # Strict requirement (expected to FAIL initially): everyone has the final value
    assert set(values.values()) == {num_messages - 1}
