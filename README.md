# Distributed Systems Labs Scaffold

This scaffold is your playground for exploring distributed systems. It gives you just enough infrastructure to run multiple nodes that talk to each other,

* either in a fast simulated network (single process, fully controllable),
* or in a more realistic multi-process/Docker network.

By keeping the algorithm code separate from the networking and timing layers, you can test your work deterministically in the simulator, then watch it come to life under real failure conditions with Docker. Think of this as scaffolding for building and breaking small distributed systems, safely and repeatably.

You will use this scaffold to complete various exercises during the tutorial. The purpose of these exercises is to make the abstract concepts you will learn from videos and readings to life. Nothing helps you understand the challenges of distributed systems like experiencing (and fixing) the failures that can occur in them.

**Note:** Keep algorithm code free of asyncio/http; use the provided Transport/Timer interfaces in protocols.py.

## Install

Requires Python 3.8.5 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -e .
```

## Quick start (simulator)

```bash
python -m pytest -q
python simulations/demo_kv_replication.py
```

## Quick start (Docker / multi-process)

```bash
docker compose -f dslabs/runtime/docker-compose.yml up --build
# Optional local dashboard without Docker
streamlit run dslabs/dashboard/app.py
```
