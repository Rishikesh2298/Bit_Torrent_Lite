"""
Collect run directories into CSV tables — Debargha's harness.

    python -m experiments.collect --runs-dir experiments/data/runs --out experiments/results

Writes:
    runs.csv          one row per run (schema in docs/experiment-method.md)
    peers.csv         one row per peer per run
    availability.csv  per-run piece-availability samples (1 s steps)

Every run directory with a manifest becomes a row, including failed,
timed-out and not-executed runs. Undefined values are left empty, never 0.
Exit status is nonzero if validation finds a problem.

Definitions (plan §7):
    completion_s   peer's "complete" event minus that peer's launch time
    finish_s       peer's "complete" event minus the common run start
    distribution_s latest expected downloader's finish_s; only when all
                   expected downloaders completed
    aggregate_throughput_Bps  L × file_bytes / distribution_s; baseline
                   and free-rider runs with all L complete only
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from bittorrent_lite.run_log import read_events  # noqa: E402

RUN_FIELDS = [
    "run_id", "revision", "environment", "file_sha256", "file_bytes", "piece_bytes",
    "L", "S", "strategy", "window", "upload_slots", "upload_cap", "seed",
    "startup_method", "scenario", "expected_completers", "actual_completers",
    "duration_s", "status", "failure_reason",
    # additions beyond the plan's minimum schema
    "config_name", "repeat", "distribution_s", "aggregate_throughput_Bps",
    "failure_target", "trigger_elapsed_s",
]
PEER_FIELDS = [
    "run_id", "peer_id", "role_at_start", "completion_s", "final_hash_ok",
    "verified_download_bytes", "uploaded_payload_bytes", "messages_sent",
    "requests_sent", "retries", "hash_failures", "exit_reason",
    # additions
    "finish_s", "throughput_Bps", "is_target", "killed_by_harness",
]
AVAIL_FIELDS = ["run_id", "t_s", "live_peers", "min_owners", "mean_owners", "max_owners"]
COUNTER_KEYS = ["verified_download_bytes", "uploaded_payload_bytes", "messages_sent",
                "requests_sent", "retries", "hash_failures"]


def _round(value, digits=3):
    return "" if value is None else round(value, digits)


def peer_rows(manifest: dict, run_dir: Path) -> list[dict]:
    run_start = manifest.get("run_start_mono")
    file_bytes = manifest.get("file_bytes")
    hashes = manifest.get("output_hash_ok", {})
    rows = []
    for proc in manifest["processes"]:
        if proc["role"] == "tracker":
            continue
        pid = proc["proc_id"]
        events = read_events(str(run_dir / "events" / f"{pid}.jsonl"))
        complete = next((e for e in events if e["event"] == "complete"), None)
        counters = {}
        for event in events:
            if event["event"] == "counters":
                counters = event          # last one wins
        # Prefer the peer's own final "counters" event; otherwise derive what
        # the per-event records allow; otherwise leave the value undefined.
        derived = {}
        if proc["role"] == "downloader" and any(e["event"] == "piece_verified" for e in events):
            derived["verified_download_bytes"] = sum(
                e.get("bytes", 0) for e in events if e["event"] == "piece_verified")
            derived["hash_failures"] = sum(1 for e in events if e["event"] == "hash_failure")
        if any(e["event"] == "piece_uploaded" for e in events):
            derived["uploaded_payload_bytes"] = sum(
                e.get("bytes", 0) for e in events if e["event"] == "piece_uploaded")
        row = {"run_id": manifest["run_id"], "peer_id": pid, "role_at_start": proc["role"]}
        for key in COUNTER_KEYS:
            row[key] = counters.get(key, derived.get(key, ""))

        completion = finish = None
        if complete is not None and proc["role"] == "downloader":
            if proc.get("launch_mono") is not None:
                completion = complete["mono"] - proc["launch_mono"]
            if run_start is not None:
                finish = complete["mono"] - run_start
        row["completion_s"] = _round(completion)
        row["finish_s"] = _round(finish)
        row["throughput_Bps"] = _round(file_bytes / completion, 1) if completion and file_bytes else ""

        if proc["role"] == "downloader":
            harness = hashes.get(pid)
            if harness is None:
                row["final_hash_ok"] = "" if complete is None else complete.get("final_hash_ok", "")
            else:
                row["final_hash_ok"] = harness
        else:
            row["final_hash_ok"] = ""

        exit_event = next((e for e in reversed(events) if e["event"] == "exit"), None)
        if proc.get("killed_by_harness"):
            row["exit_reason"] = "killed_by_harness"
        elif exit_event is not None:
            row["exit_reason"] = exit_event.get("reason", "")
        elif proc.get("exit_code") is None:
            row["exit_reason"] = "not_started"
        else:
            row["exit_reason"] = f"exit_code_{proc['exit_code']}"
        row["is_target"] = pid == manifest.get("target")
        row["killed_by_harness"] = bool(proc.get("killed_by_harness"))
        rows.append(row)
    return rows


def run_row(manifest: dict, peers: list[dict]) -> dict:
    c = manifest["config"]
    target = manifest.get("target")
    trigger = manifest.get("trigger")
    downloaders = [p for p in peers if p["role_at_start"] == "downloader"]
    if c["scenario"] == "failure":
        expected = [p for p in downloaders if p["peer_id"] != target]
    else:
        expected = downloaders
    finished = [p for p in expected if p["finish_s"] != ""]
    actual = sum(1 for p in downloaders if p["finish_s"] != "")

    distribution = None
    if manifest["status"] == "ok" and expected and len(finished) == len(expected):
        distribution = max(p["finish_s"] for p in finished)
    aggregate = None
    if (distribution and c["scenario"] != "failure" and manifest.get("file_bytes")
            and actual == c["L"]):
        aggregate = c["L"] * manifest["file_bytes"] / distribution

    return {
        "run_id": manifest["run_id"],
        "revision": manifest.get("revision", ""),
        "environment": manifest.get("environment", {}).get("label", ""),
        "file_sha256": manifest.get("file_sha256") or "",
        "file_bytes": manifest.get("file_bytes") or "",
        "piece_bytes": c.get("piece_bytes", ""),
        "L": c["L"], "S": c["S"], "strategy": c["strategy"], "window": c.get("window", ""),
        "upload_slots": c.get("upload_slots", ""),
        "upload_cap": "" if c.get("upload_cap") is None else c["upload_cap"],
        "seed": c.get("seed", ""), "startup_method": c.get("startup_method", ""),
        "scenario": c["scenario"],
        "expected_completers": len(expected),
        "actual_completers": actual,
        "duration_s": _round(manifest.get("duration_s")),
        "status": manifest["status"],
        "failure_reason": manifest.get("failure_reason", ""),
        "config_name": c.get("name", ""), "repeat": c.get("repeat", ""),
        "distribution_s": _round(distribution),
        "aggregate_throughput_Bps": _round(aggregate, 1),
        "failure_target": target or "",
        "trigger_elapsed_s": "" if not trigger else trigger.get("elapsed_s", ""),
    }


def availability_rows(manifest: dict, run_dir: Path, step: float = 1.0) -> list[dict]:
    """
    Reconstruct piece availability offline: seeders own every piece from
    their launch; a downloader owns a piece from its piece_verified event;
    a killed peer stops counting at the kill time. Peers use only local
    neighbour information at runtime; this global view is analysis only.
    """
    run_start = manifest.get("run_start_mono")
    end = manifest.get("end_mono")
    try:
        metadata = json.loads((REPO_ROOT / manifest["config"]["metadata"]).read_text("utf-8"))
        total = len(metadata["piece_hashes"])
    except (OSError, KeyError, ValueError):
        return []
    if run_start is None or end is None or total == 0:
        return []
    kill_at = (manifest.get("trigger") or {}).get("mono")
    owners = []      # (peer_id, start_mono, end_mono or None, {piece: mono})
    for proc in manifest["processes"]:
        if proc["role"] == "tracker" or proc.get("launch_mono") is None:
            continue
        stop = kill_at if proc.get("killed_by_harness") else None
        if proc["role"] == "seeder":
            owners.append((proc["launch_mono"], stop, None))
        else:
            events = read_events(str(run_dir / "events" / f"{proc['proc_id']}.jsonl"))
            got = {}
            for e in events:
                if e["event"] == "piece_verified" and isinstance(e.get("piece"), int):
                    got.setdefault(e["piece"], e["mono"])
            owners.append((proc["launch_mono"], stop, got))
    rows, t = [], 0.0
    while run_start + t <= end:
        now = run_start + t
        counts = [0] * total
        live = 0
        for start, stop, got in owners:
            if now < start or (stop is not None and now >= stop):
                continue
            live += 1
            if got is None:
                counts = [n + 1 for n in counts]
            else:
                for piece, when in got.items():
                    if when <= now and 0 <= piece < total:
                        counts[piece] += 1
        rows.append({"run_id": manifest["run_id"], "t_s": round(t, 3), "live_peers": live,
                     "min_owners": min(counts), "mean_owners": round(sum(counts) / total, 3),
                     "max_owners": max(counts)})
        t += step
    return rows


def validate(runs: list[dict], peers: list[dict]) -> list[str]:
    problems = []
    keys = [(p["run_id"], p["peer_id"]) for p in peers]
    if len(keys) != len(set(keys)):
        problems.append("duplicate (run_id, peer_id) rows")
    by_run = {}
    for p in peers:
        by_run.setdefault(p["run_id"], []).append(p)
    for run in runs:
        rows = by_run.get(run["run_id"], [])
        if len(rows) != run["L"] + run["S"]:
            problems.append(f"{run['run_id']}: {len(rows)} peer rows, expected {run['L'] + run['S']}")
        if run["status"] == "ok" and run["actual_completers"] < run["expected_completers"]:
            problems.append(f"{run['run_id']}: status ok but not all expected peers completed")
    for p in peers:
        for key in COUNTER_KEYS:
            value = p[key]
            if value != "" and (not isinstance(value, (int, float)) or value < 0):
                problems.append(f"{p['run_id']}/{p['peer_id']}: bad {key} {value!r}")
        if p["completion_s"] != "" and p["final_hash_ok"] is False:
            problems.append(f"{p['run_id']}/{p['peer_id']}: completed but output hash mismatch")
        if p["completion_s"] != "" and p["completion_s"] < 0:
            problems.append(f"{p['run_id']}/{p['peer_id']}: negative completion time")
    return problems


def collect(runs_dir: Path, out_dir: Path) -> tuple[list[dict], list[dict], list[str]]:
    runs, peers, avail = [], [], []
    for manifest_path in sorted(Path(runs_dir).glob("*/manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text("utf-8"))
        except (OSError, ValueError):
            print(f"skipping unreadable {manifest_path}", file=sys.stderr)
            continue
        rows = peer_rows(manifest, manifest_path.parent)
        peers.extend(rows)
        runs.append(run_row(manifest, rows))
        avail.extend(availability_rows(manifest, manifest_path.parent))
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, fields, rows in (("runs.csv", RUN_FIELDS, runs), ("peers.csv", PEER_FIELDS, peers),
                               ("availability.csv", AVAIL_FIELDS, avail)):
        with open(out_dir / name, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    return runs, peers, validate(runs, peers)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Collect run directories into CSVs")
    parser.add_argument("--runs-dir", default=str(REPO_ROOT / "experiments" / "data" / "runs"))
    parser.add_argument("--out", default=str(REPO_ROOT / "experiments" / "results"))
    args = parser.parse_args(argv)
    runs, peers, problems = collect(Path(args.runs_dir), Path(args.out))
    statuses = {}
    for run in runs:
        statuses[run["status"]] = statuses.get(run["status"], 0) + 1
    print(f"{len(runs)} run(s), {len(peers)} peer row(s): "
          + ", ".join(f"{k}={v}" for k, v in sorted(statuses.items())))
    for problem in problems:
        print(f"PROBLEM: {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
