"""The trace: messages, timers, client requests, notes, state, and the views over them."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dslabs import Cluster, SimNetwork, SimScheduler, drop, duplicate, partition
from dslabs.nodes import NodeMultiLeader
from dslabs.protocols import Message, Scheduler, Transport


@dataclass
class TimerNode:
    """A node that arms timers three ways and writes a note, to exercise attribution."""

    node_id: str
    peers: list[str]
    transport: Transport
    scheduler: Scheduler
    store: dict[str, Any] = field(default_factory=dict)
    fired: list[str] = field(default_factory=list)

    def client_put(self, key: str, value: Any) -> None:
        self.store[key] = value
        self.scheduler.call_later(100, self.on_timeout)  # bound method
        cancel = self.scheduler.call_later(200, lambda: self.fired.append("lambda"))  # closure over self
        cancel()

    def client_get(self, key: str) -> Any:
        return self.store.get(key)

    def on_message(self, msg: Message) -> None:
        pass

    def on_timeout(self) -> None:
        self.fired.append("method")
        self.transport.note("timeout handled")
        self.store["fired"] = True

    def brief_state(self) -> dict[str, Any]:
        return dict(self.store)


def test_message_table_reports_delivery_delay_drops_and_duplicates():
    cluster = Cluster(NodeMultiLeader, 3, seed=3)
    cluster.put("n1", "x", 1)
    cluster.run_until(1000)
    rows = list(cluster.messages())
    assert [(r.frm, r.to) for r in rows] == [("n1", "n2"), ("n1", "n3")]
    for r in rows:
        assert r.delivered and 30 <= r.deliveries[0][1] <= 80, r.fate
        assert r.fate.startswith("delivered @")

    cluster.add_rule(partition({"n1"}))
    cluster.put("n1", "x", 2)
    cluster.run_until(2000)
    dropped = cluster.messages(frm="n1", to="n3")[-1]
    assert not dropped.delivered
    assert dropped.fate == "dropped by partition({n1})"

    cluster.network.rules.clear()
    cluster.add_rule(duplicate(1.0))
    cluster.put("n2", "x", 3)
    cluster.run_until(3000)
    twice = cluster.messages(frm="n2", to="n1")[-1]
    assert len(twice.deliveries) == 2
    assert "again @" in twice.fate

    text = str(cluster.messages())
    assert "dropped by partition({n1})" in text and "again @" in text
    assert "<table" in cluster.messages()._repr_html_()


def test_client_requests_and_state_changes_are_on_the_timeline():
    cluster = Cluster(NodeMultiLeader, 2, seed=0)
    cluster.put("n1", "x", 1)
    cluster.run_until(500)
    assert cluster.get("n2", "x") == 1
    kinds = [(ev.kind, ev.node or ev.to) for ev in cluster.timeline(kinds=["client", "state"])]
    assert kinds == [("client", "n1"), ("state", "n1"), ("state", "n2"), ("client", "n2")]
    assert cluster.timeline(kinds=["state"])[0].state == {"x": 1}
    assert "put x=1" in str(cluster.timeline(node="n1"))
    assert "get x -> 1" in str(cluster.timeline(node="n2"))
    assert "get x -&gt; 1" in cluster.timeline(node="n2")._repr_html_()


def test_timers_are_attributed_to_their_node():
    cluster = Cluster(TimerNode, 1)
    cluster.put("n1", "x", 1)
    cluster.run_until(1000)
    timers = [(ev.kind, ev.text) for ev in cluster.timeline(kinds=["timer"])]
    assert timers == [
        ("timer_set", "on_timeout"),
        ("timer_set", "<lambda>"),
        ("timer_cancelled", "<lambda>"),
        ("timer_fired", "on_timeout"),
    ]
    assert all(ev.node == "n1" for ev in cluster.timeline(kinds=["timer"]))
    assert cluster["n1"].fired == ["method"]


def test_notes_and_post_timer_state_land_on_the_timeline():
    cluster = Cluster(TimerNode, 1)
    cluster.put("n1", "x", 1)
    cluster.run_until(1000)
    tail = [(ev.t_ms, ev.kind, ev.detail) for ev in cluster.timeline(kinds=["note", "state"])]
    assert tail == [(0, "state", "x=1"), (100, "note", "timeout handled"), (100, "state", "x=1 fired=True")]


def test_network_delivery_callbacks_are_not_reported_as_node_timers():
    scheduler = SimScheduler()
    network = SimNetwork(scheduler)
    inbox = []
    network.register("n1", inbox.append)
    network.register("n2", inbox.append)
    network.endpoint("n1").send("n2", {"type": "ping"})
    scheduler.run_until(1000)
    assert [ev.kind for ev in scheduler.trace] == ["send", "deliver"]


def test_explain_gathers_one_nodes_view():
    cluster = Cluster(NodeMultiLeader, 3, seed=1)
    cluster.add_rule(drop(1.0))
    cluster.put("n1", "x", 1)
    cluster.run_until(1000)
    text = str(cluster.explain("n3"))
    assert "Messages to n3" in text and "dropped by drop(1.0)" in text
    assert "Messages from n3" in text and "(no messages)" in text
    assert "<h4>Timeline of n3</h4>" in cluster.explain("n3")._repr_html_()


def test_diagram_is_svg_with_the_expected_elements():
    cluster = Cluster(TimerNode, 2, seed=2)
    cluster.put("n1", "x", 1)
    cluster.add_rule(drop(1.0))
    cluster["n1"].transport.send("n2", {"type": "lost"})
    cluster.network.rules.clear()
    cluster["n1"].transport.send("n2", {"type": "kept"})
    cluster.run_until(1000)

    svg = cluster.diagram()._repr_svg_()
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert ">n1</text>" in svg and ">n2</text>" in svg
    assert "marker-end=" in svg, "delivered message drawn as an arrow"
    assert "stroke-dasharray='4 3'" in svg, "dropped message drawn dashed"
    assert "dropped by drop(1.0)" in svg, "drop tooltip names the rule"
    assert ">put x=1</text>" in svg, "client request labelled"
    assert "timeout handled" in svg, "note drawn"
    assert "x=1 fired=True" in svg, "state drawn"
    assert "timer on_timeout" in svg, "timer tooltip"

    only_n2 = cluster.diagram(nodes=["n2"]).svg
    assert ">n1</text>" not in only_n2 and "kept" not in only_n2

    late = cluster.diagram(t_range=(500, 1000)).svg
    assert ">put x=1</text>" not in late

    assert "nothing has happened yet" in Cluster(NodeMultiLeader, 0).diagram().svg


def test_diagram_can_be_saved(tmp_path):
    cluster = Cluster(NodeMultiLeader, 2)
    cluster.put("n1", "x", 1)
    cluster.run_until(100)
    path = tmp_path / "run.svg"
    cluster.diagram().save(path)
    assert path.read_text().startswith("<svg")


def test_verbose_prints_events_as_they_happen(capsys):
    cluster = Cluster(NodeMultiLeader, 2, verbose=True)
    cluster.put("n1", "x", 1)
    cluster.run_until(1000)
    out = capsys.readouterr().out
    assert "client   put x=1" in out and "deliver  #1 replicate x=1" in out
    assert "timer" not in out


def test_step_shows_everything_one_delivery_caused():
    cluster = Cluster(NodeMultiLeader, 3, seed=1)
    cluster.put("n1", "x", 1)
    assert sorted(d for _, d in cluster.pending()) == [
        "deliver #1 n1 -> n2: replicate x=1",
        "deliver #2 n1 -> n3: replicate x=1",
    ]

    nxt = cluster.peek()
    step = cluster.step()
    assert step and step.t_ms == nxt.due_ms and step.trigger == nxt.description
    assert [ev.kind for ev in step.events] == ["deliver", "state"]
    assert str(step).startswith(f"Step 1 @ {step.t_ms} ms: deliver #")
    assert "<b>Step 1 @" in step._repr_html_() and "<table" in step._repr_html_()

    assert cluster.step()
    assert not cluster.step()
    assert cluster.values("x") == {"n1": 1, "n2": 1, "n3": 1}


def test_step_reports_node_timers_by_name_and_node():
    cluster = Cluster(TimerNode, 1)
    cluster.put("n1", "x", 1)
    assert cluster.peek().description == "timer on_timeout at n1"
    step = cluster.step()
    assert step.trigger == "timer on_timeout at n1"
    assert [ev.kind for ev in step.events] == ["timer_fired", "note", "state"]


def test_trace_exports_to_json_for_the_viewer(tmp_path):
    import json

    cluster = Cluster(TimerNode, 2, seed=1)
    cluster.put("n1", "x", 1)
    cluster["n1"].transport.note("contains </script> on purpose")
    cluster.run_until(500)

    data = cluster.trace.to_dict()
    assert data["format"] == "dslabs-trace/1"
    assert data["nodes"] == ["n1", "n2"]
    assert data["end_ms"] == 500
    assert [ev["kind"] for ev in data["events"]][:2] == ["client", "timer_set"]
    assert all(v is not None for ev in data["events"] for v in ev.values()), "None fields are stripped"

    path = cluster.save_json(tmp_path / "run.json")
    assert json.loads(path.read_text()) == json.loads(cluster.trace.to_json())

    page = cluster.save_viewer(tmp_path / "run.html").read_text()
    assert page.startswith("<!doctype html>")
    assert "DSLABS_TRACE_PLACEHOLDER" not in page
    assert '"format": "dslabs-trace/1"' in page
    assert "contains <\\/script> on purpose" in page, "script-closing sequences are escaped"
    assert page.count("</script>") == 2, "only the viewer's own two script tags close"
