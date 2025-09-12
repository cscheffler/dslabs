# Simulator Overview

This package lets you run distributed algorithms deterministically in a single process.

- `SimNetwork`: schedules deliveries as `(deliver_at_ms, payload)` pairs. Add rules to inject faults:
  - `delay(min,max)`, `drop(p)`, `duplicate(p)`, `partition(cut)`.
- `SimClock` + `SimScheduler`: you advance time; scheduler trigger due callbacks.

Quick demo

```bash
python simulations/demo_kv_replication.py
```

Experiment ideas

- Increase delay: `net.add_rule(delay(200, 600))` — observe election timing.
- Add drops: `net.add_rule(drop(0.2))` — watch retry behavior.
- Partition: `net.add_rule(partition({("n1","n2")}))` — see leader isolation.

Tips

- Seed the simulator for reproducibility: `SimNetwork(clock, seed=42)`.
- Use `scheduler.run_due(); clock.advance(dt)` in loops to step time.
