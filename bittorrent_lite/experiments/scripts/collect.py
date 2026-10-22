"""
Collect run directories into CSV tables — Debargha's harness.

    python -m bittorrent_lite.experiments.scripts.collect --runs-dir bittorrent_lite/experiments/data/runs --out bittorrent_lite/experiments/results

Writes:
    runs.csv          one row per run (schema in bittorrent_lite/docs/debargha/experiment-method.md)
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

REPO_ROOT = next(
    parent for parent in Path(__file__).resolve().parents
    if (parent / "pyproject.toml").is_file() and (parent / "bittorrent_lite").is_dir()
)
sys.path.insert(0, str(REPO_ROOT))

from bittorrent_lite.common.run_log import read_events  # noqa: E402

RUN_FIELDS = [
    "run_id", "revision", "environment", "file_sha256", "file_bytes", "piece_bytes",
    "L", "S", "strategy", "window", "upload_slots", "upload_cap", "seed",
    "startup_method", "scenario", "expected_completers", "actual_completers",
    "duration_s", "status", "failure_reason",
    # additions beyond the plan's minimum schema
    "config_name", "repeat", "distribution_s", "aggregate_throughput_Bps",
    "failure_target", "trigger_elapsed_s", "distribution_origin",
]
PEER_FIELDS = [
    "run_id", "peer_id", "role_at_start", "completion_s", "final_hash_ok",
    "verified_download_bytes", "uploaded_payload_bytes", "messages_sent",
    "requests_sent", "retries", "hash_failures", "exit_reason",
    # additions
    "finish_s", "throughput_Bps", "is_target", "killed_by_harness",
    "metrics_scope", "observed_verified_download_bytes", "observed_uploaded_payload_bytes",
    "observed_messages_sent", "observed_requests_sent", "observed_retries", "observed_hash_failures",
]
AVAIL_FIELDS = ["run_id", "t_s", "live_peers", "min_owners", "mean_owners", "max_owners"]
COUNTER_KEYS = ["verified_download_bytes", "uploaded_payload_bytes", "messages_sent",
                "requests_sent", "retries", "hash_failures"]


def _round(value, digits=3):
    return "" if value is None else round(value, digits)


def distribution_start(manifest: dict):
    """First peer launch is the declared common origin; retain legacy fallback."""
    recorded = manifest.get("distribution_start_mono")
    launches = [p["launch_mono"] for p in manifest["processes"]
                if p["role"] != "tracker" and p.get("launch_mono") is not None]
    return recorded if recorded is not None else min(launches, default=manifest.get("run_start_mono"))


def logged_metrics(events: list[dict]) -> dict:
    """Observed event totals; a forced kill can leave an unobserved final suffix."""
    frames = [e for e in events if e["event"] == "frame_sent" and e.get("frame_complete") is True]
    requests = [e for e in frames if e.get("message_type") == "REQUEST"]
    commits = {}
    for event in events:
        if event["event"] == "piece_verified":
            commits.setdefault(event["piece"], event["bytes"])
    derived = {}
    if frames:
        derived.update(
            messages_sent=len(frames), requests_sent=len(requests),
            retries=len(requests) - len({e["piece"] for e in requests}),
            uploaded_payload_bytes=sum(e["payload_bytes"] for e in frames
                                       if e.get("message_type") == "PIECE"),
        )
    if commits:
        derived["verified_download_bytes"] = sum(commits.values())
    if frames or any(e["event"] == "piece_verification" for e in events):
        derived["hash_failures"] = sum(
            e["event"] == "piece_verification" and e.get("outcome") == "hash_mismatch"
            for e in events)
    return derived


def peer_rows(manifest: dict, run_dir: Path) -> list[dict]:
    run_start = distribution_start(manifest)
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
        derived = logged_metrics(events)
        exit_event = next((e for e in reversed(events) if e["event"] == "exit"), None)
        final_logged = (not proc.get("killed_by_harness") and bool(counters)
                        and exit_event is not None and exit_event.get("reason") == "stopped")
        row = {"run_id": manifest["run_id"], "peer_id": pid, "role_at_start": proc["role"]}
        row["metrics_scope"] = "final_logged" if final_logged else "observed_prefix" if events else "unavailable"
        for key in COUNTER_KEYS:
            observed = derived.get(key, counters.get(key, ""))
            row[key] = observed if final_logged else ""
            row["observed_" + key] = observed

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
            # A peer's own claim cannot replace the launcher's independent file check.
            row["final_hash_ok"] = "" if harness is None else harness
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
        "distribution_origin": manifest.get("distribution_origin", "first_peer_launch"),
    }


def availability_rows(manifest: dict, run_dir: Path, step: float = 1.0) -> list[dict]:
    """
    Reconstruct piece availability offline: seeders own every piece from
    their readiness; a downloader owns a piece from its piece_verified event;
    a killed peer stops counting at the kill time. Peers use only local
    neighbour information at runtime; this global view is analysis only.
    """
    run_start = distribution_start(manifest)
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
            owners.append((proc.get("ready_mono") or proc["launch_mono"], stop, None))
        else:
            events = read_events(str(run_dir / "events" / f"{proc['proc_id']}.jsonl"))
            got = {}
            for e in events:
                if e["event"] == "piece_verified" and isinstance(e.get("piece"), int):
                    got.setdefault(e["piece"], e["mono"])
            owners.append((proc.get("ready_mono") or proc["launch_mono"], stop, got))
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
        if run["status"] == "ok":
            completed = {p["peer_id"] for p in rows
                         if p["role_at_start"] == "downloader" and p["finish_s"] != ""}
            expected = {p["peer_id"] for p in rows if p["role_at_start"] == "downloader"
                        and not (run["scenario"] == "failure" and p["peer_id"] == run["failure_target"])}
            if completed != expected:
                problems.append(f"{run['run_id']}: status ok but completed peer identities differ from expected")
            if any(p["killed_by_harness"] and p["completion_s"] != "" for p in rows):
                problems.append(f"{run['run_id']}: killed target completed; failure was not in flight")
    for p in peers:
        for key in COUNTER_KEYS:
            value = p[key]
            if value != "" and (not isinstance(value, (int, float)) or value < 0):
                problems.append(f"{p['run_id']}/{p['peer_id']}: bad {key} {value!r}")
        if p["completion_s"] != "" and p["final_hash_ok"] is not True:
            problems.append(f"{p['run_id']}/{p['peer_id']}: completed but independent output hash not verified")
        if p["completion_s"] != "" and p["completion_s"] < 0:
            problems.append(f"{p['run_id']}/{p['peer_id']}: negative completion time")
    return problems


def collect(runs_dir: Path, out_dir: Path) -> tuple[list[dict], list[dict], list[str]]:
    runs, peers, avail, problems = [], [], [], []
    for manifest_path in sorted(Path(runs_dir).glob("*/manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text("utf-8"))
        except (OSError, ValueError):
            problems.append(f"unreadable manifest: {manifest_path}")
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
    if not runs:
        problems.append("no run manifests collected")
    return runs, peers, problems + validate(runs, peers)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Collect run directories into CSVs")
    parser.add_argument("--runs-dir", default=str(REPO_ROOT / "bittorrent_lite" / "experiments" / "data" / "runs"))
    parser.add_argument("--out", default=str(REPO_ROOT / "bittorrent_lite" / "experiments" / "results"))
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
