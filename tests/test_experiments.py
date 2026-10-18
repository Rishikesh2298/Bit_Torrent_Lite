"""
Experiment harness tests (Debargha's module): launcher, collector, plots.

These start real OS processes: the real tracker and the synthetic
stand-in peer (experiments/stand_in_peer.py). Ports are chosen free per test.
"""

import csv
import json
import random
import socket
import sys
from pathlib import Path

import pytest

from experiments.collect import collect
from experiments.launcher import Run, load_config, port_is_free
from experiments.make_fixture import make_fixture
from experiments.plot import make_all

REPO_ROOT = Path(__file__).resolve().parent.parent
STAND_IN = str(REPO_ROOT / "experiments" / "configs" / "stand_in.json")

pytestmark = pytest.mark.timeout(90)


def free_block(n):
    """A run of n consecutive free ports (tracker first, then peers)."""
    rng = random.Random()
    for _ in range(200):
        base = rng.randrange(20000, 50000)
        if all(port_is_free("127.0.0.1", base + i) for i in range(n)):
            return base
    raise RuntimeError("no free port block")


@pytest.fixture(scope="module")
def fixture_files(tmp_path_factory):
    out = tmp_path_factory.mktemp("fixture")
    data, meta, _ = make_fixture(out, 20 * 65536 + 123)
    return data, meta


def config_for(fixture_files, L=2, **changes):
    data, meta = fixture_files
    config = load_config(STAND_IN, [])
    config.update({"fixture": str(data), "metadata": str(meta), "L": L, "timeout_s": 30})
    config.update(changes)
    base = free_block(1 + config["S"] + config["L"])
    config["tracker_port"], config["base_port"] = base, base + 1
    return config


def run_swarm(tmp_path, fixture_files, L=2, **changes):
    return Run(config_for(fixture_files, L, **changes), tmp_path / "runs").execute()


def test_baseline_run_completes_and_records(tmp_path, fixture_files):
    manifest = run_swarm(tmp_path, fixture_files, L=2)
    assert manifest["status"] == "ok", manifest["failure_reason"]
    assert manifest["environment"]["label"] == "localhost-synthetic"
    assert manifest["output_hash_ok"] == {"peer-01": True, "peer-02": True}
    procs = {p["proc_id"]: p for p in manifest["processes"]}
    assert set(procs) == {"tracker", "seed-01", "peer-01", "peer-02"}
    assert all(p["ready_mono"] is not None for p in procs.values())
    run_dir = tmp_path / "runs" / manifest["run_id"]
    assert (run_dir / "events" / "tracker.jsonl").stat().st_size > 0
    # every child stopped and its stopped announce reached the tracker first
    tracker_events = [json.loads(l) for l in (run_dir / "events" / "tracker.jsonl").open()]
    stopped = {e["peer"] for e in tracker_events
               if e["event"] == "tracker_announce" and e["announce_event"] == "stopped"}
    assert stopped == {"seed-01", "peer-01", "peer-02"}
    assert all(p["exit_code"] is not None for p in procs.values())


def test_failure_scenario_kills_only_target(tmp_path, fixture_files):
    manifest = run_swarm(tmp_path, fixture_files, L=3, scenario="failure")
    assert manifest["status"] == "ok", manifest["failure_reason"]
    assert manifest["trigger"]["target"] == "peer-03"
    assert manifest["trigger"]["progress_pct"] >= 25
    procs = {p["proc_id"]: p for p in manifest["processes"]}
    assert procs["peer-03"]["killed_by_harness"]
    assert not any(p["killed_by_harness"] for k, p in procs.items() if k != "peer-03")


def test_port_in_use_is_reported(tmp_path, fixture_files):                 # D-T11
    config = config_for(fixture_files)
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", config["tracker_port"]))
    blocker.listen()
    try:
        manifest = Run(config, tmp_path / "runs").execute()
    finally:
        blocker.close()
    assert manifest["status"] == "failed"
    assert "already in use" in manifest["failure_reason"]
    assert all(p["launch_mono"] is None for p in manifest["processes"])


def test_child_crash_preserves_logs(tmp_path, fixture_files):              # D-T10
    config = config_for(fixture_files)
    config["peer_command"] = config["peer_command"] + ["--exit-after-s", "0.3"]
    manifest = Run(config, tmp_path / "runs").execute()
    assert manifest["status"] == "failed"
    assert "exited unexpectedly" in manifest["failure_reason"]
    run_dir = tmp_path / "runs" / manifest["run_id"]
    assert (run_dir / "logs" / "seed-01.err").exists()
    assert all(p["exit_code"] is not None for p in manifest["processes"]
               if p["launch_mono"] is not None)


def test_peer_never_ready(tmp_path, fixture_files):
    config = config_for(fixture_files)
    config["peer_command"] = [sys.executable, "-c", "import time; time.sleep(30)"]
    config["ready_timeout_s"] = 1
    manifest = Run(config, tmp_path / "runs").execute()
    assert manifest["status"] == "failed"
    assert "not ready" in manifest["failure_reason"]


def test_collect_and_plot_keep_failed_runs(tmp_path, fixture_files):       # D-T12
    ok = run_swarm(tmp_path, fixture_files, L=2)
    config = config_for(fixture_files)
    config["peer_command"] = [sys.executable, "-c", "raise SystemExit(4)"]
    failed = Run(config, tmp_path / "runs").execute()

    runs, peers, problems = collect(tmp_path / "runs", tmp_path / "results")
    assert problems == []
    by_id = {r["run_id"]: r for r in runs}
    assert by_id[ok["run_id"]]["status"] == "ok"
    assert by_id[ok["run_id"]]["distribution_s"] > 0
    assert by_id[ok["run_id"]]["aggregate_throughput_Bps"] > 0
    assert by_id[failed["run_id"]]["status"] == "failed"
    assert by_id[failed["run_id"]]["distribution_s"] == ""

    with open(tmp_path / "results" / "peers.csv", newline="") as handle:
        rows = list(csv.DictReader(handle))
    failed_rows = [r for r in rows if r["run_id"] == failed["run_id"]]
    assert len(failed_rows) == 3
    assert all(r["completion_s"] == "" for r in failed_rows)    # empty, never zero

    figures = make_all(tmp_path / "results")
    assert any(p.name == "fig1_swarm_size_distribution.png" for p in figures)
