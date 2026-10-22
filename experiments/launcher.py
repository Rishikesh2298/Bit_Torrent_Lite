"""
Experiment launcher — Debargha's harness.

Runs one swarm (tracker + S seeders + L downloaders) from a JSON config,
watches structured events until the expected downloaders finish or the
timeout passes, injects the configured failure, then stops everything it
started and writes a manifest.

The harness never supplies pieces or makes selection decisions. It only
starts, observes and stops processes.

Usage:
    python -m experiments.launcher experiments/configs/base.json \
        --set L=2 --set name=smoke --runs-dir experiments/data/runs

Run directory layout:
    <runs-dir>/<run_id>/
        manifest.json          config, environment, ports, IDs, timings, status
        events/<proc>.jsonl    structured events (bittorrent_lite.run_log)
        logs/<proc>.out|.err   raw stdout / stderr
        peers/<peer_id>/       each peer's own storage / output directory

Readiness:
    tracker: "tracker_ready" event; peer: "listening" event.
    A fixed sleep is never treated as proof of readiness.

Timing:
    run_start = launcher's time.monotonic() just before the tracker starts.
    Peers log time.monotonic() too; on one host these are comparable.
    Startup method "launch-sequence": everyone starts in a fixed order with
    a fixed gap, and timings include startup.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from bittorrent_lite import run_log  # noqa: E402

DEFAULTS = {
    "name": "run",
    "L": 2,
    "S": 1,
    "strategy": "rarest",
    "scenario": "baseline",              # baseline | free_rider | failure
    "fixture": "experiments/data/fixture.bin",
    "metadata": "experiments/data/fixture.torrent.json",
    "piece_bytes": 65536,
    "window": 4,
    "upload_slots": 2,
    "upload_cap": None,
    "seed": 1,
    "repeat": 1,
    "timeout_s": 300,
    "ready_timeout_s": 15,
    "launch_gap_s": 0.2,
    "tracker_host": "127.0.0.1",
    "tracker_port": 8000,
    "base_port": 7001,
    "failure_trigger_pct": 25,
    "startup_method": "launch-sequence",
    "environment": "localhost",
    "synthetic": False,
    "tracker_command": ["{python}", "-m", "bittorrent_lite.tracker.tracker_server",
                        "--host", "{tracker_host}", "--port", "{tracker_port}"],
    "peer_command": ["{python}", "-m", "bittorrent_lite.peer.peer_main",
                     "--peer-id", "{peer_id}", "--port", "{port}",
                     "--tracker", "{tracker_url}", "--metadata", "{metadata}",
                     "--output-dir", "{peer_dir}"],
    "seeder_args": ["--seeder", "--file", "{fixture}"],
    "strategy_args": [],                 # e.g. ["--strategy", "{strategy}"] once peer_main has it
    "free_rider_args": [],               # e.g. ["--upload-slots", "0"] once peer_main has it
}

POLL_S = 0.2
STOP_GRACE_S = 5.0


class LaunchError(Exception):
    """A run that could not start; reason goes into the manifest."""


# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────

def load_config(path: str | None, overrides: list[str] | None = None) -> dict:
    config = copy.deepcopy(DEFAULTS)
    if path:
        with open(path, "r", encoding="utf-8") as handle:
            config.update(json.load(handle))
    for item in overrides or []:
        key, _, raw = item.partition("=")
        if key not in DEFAULTS:
            raise ValueError(f"unknown config key {key!r}")
        try:
            config[key] = json.loads(raw)
        except json.JSONDecodeError:
            config[key] = raw
    validate_config(config)
    return config


def validate_config(config: dict) -> None:
    for key in ("L", "S", "tracker_port", "base_port"):
        if type(config[key]) is not int or config[key] < 0:
            raise ValueError(f"{key} must be a nonnegative integer")
    if config["L"] < 1 or config["S"] < 1:
        raise ValueError("need at least one downloader and one seeder")
    if config["scenario"] not in ("baseline", "free_rider", "failure"):
        raise ValueError("scenario must be baseline, free_rider or failure")
    if config["scenario"] == "failure" and config["L"] < 2:
        raise ValueError("failure scenario needs at least two downloaders")


def peer_ids(config: dict) -> tuple[list[str], list[str]]:
    seeders = [f"seed-{i:02d}" for i in range(1, config["S"] + 1)]
    downloaders = [f"peer-{i:02d}" for i in range(1, config["L"] + 1)]
    return seeders, downloaders


def designated_target(config: dict) -> str | None:
    """The downloader that is killed (failure) or free-rides (free_rider)."""
    if config["scenario"] == "baseline":
        return None
    return peer_ids(config)[1][-1]


# ──────────────────────────────────────────────
# Environment record
# ──────────────────────────────────────────────

def git_revision() -> str:
    try:
        rev = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True,
                             text=True, timeout=5).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT,
                               capture_output=True, text=True, timeout=5).stdout.strip()
        return (rev or "unknown") + ("-dirty" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if os.name != "nt":
            # Match the servers' own SO_REUSEADDR so TIME_WAIT from the
            # previous run does not count as "in use"; a live listener still does.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


# ──────────────────────────────────────────────
# Child processes
# ──────────────────────────────────────────────

@dataclass
class Child:
    proc_id: str
    role: str                 # tracker | seeder | downloader
    port: int
    command: list[str]
    event_path: Path
    process: subprocess.Popen | None = None
    launch_mono: float | None = None
    ready_mono: float | None = None
    exit_code: int | None = None
    killed_by_harness: bool = False
    files: list = field(default_factory=list)
    _offset: int = 0
    events: list = field(default_factory=list)

    def poll_events(self) -> list[dict]:
        """Read events appended since the last call (a partial last line waits)."""
        try:
            with open(self.event_path, "rb") as handle:
                handle.seek(self._offset)
                chunk = handle.read()
        except FileNotFoundError:
            return []
        end = chunk.rfind(b"\n")
        if end < 0:
            return []
        self._offset += end + 1
        new = []
        for line in chunk[:end].split(b"\n"):
            try:
                record = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(record, dict) and "event" in record:
                new.append(record)
        self.events.extend(new)
        return new


def fill(template: list[str], values: dict) -> list[str]:
    return [str(part).format(**values) for part in template]


class Run:
    """One launcher run. Use run.execute(); it always cleans up."""

    def __init__(self, config: dict, runs_dir: Path):
        self.config = config
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.run_id = f"{config['name']}-r{config['repeat']}-{stamp}-{os.getpid() % 10000:04d}"
        self.dir = Path(runs_dir) / self.run_id
        self.children: list[Child] = []
        self.manifest: dict = {}
        self.run_start: float | None = None
        self.trigger: dict | None = None

    # ---- setup ----

    def _values(self, peer_id: str = "", port: int = 0) -> dict:
        c = self.config
        return {
            "python": sys.executable,
            "peer_id": peer_id, "port": port,
            "tracker_host": c["tracker_host"], "tracker_port": c["tracker_port"],
            "tracker_url": f"http://{c['tracker_host']}:{c['tracker_port']}",
            "metadata": str((REPO_ROOT / c["metadata"]).resolve()),
            "fixture": str((REPO_ROOT / c["fixture"]).resolve()),
            "peer_dir": str(self.dir / "peers" / peer_id) if peer_id else "",
            "strategy": c["strategy"], "window": c["window"],
            "upload_slots": c["upload_slots"], "seed": c["seed"],
        }

    def _plan_children(self) -> None:
        c = self.config
        seeders, downloaders = peer_ids(c)
        target = designated_target(c)
        self.children.append(Child("tracker", "tracker", c["tracker_port"],
                                   fill(c["tracker_command"], self._values()),
                                   self.dir / "events" / "tracker.jsonl"))
        port = c["base_port"]
        for role, ids in (("seeder", seeders), ("downloader", downloaders)):
            for pid in ids:
                values = self._values(pid, port)
                command = fill(c["peer_command"], values) + fill(c["strategy_args"], values)
                if role == "seeder":
                    command += fill(c["seeder_args"], values)
                if c["scenario"] == "free_rider" and pid == target:
                    command += fill(c["free_rider_args"], values)
                self.children.append(Child(pid, role, port, command,
                                           self.dir / "events" / f"{pid}.jsonl"))
                port += 1

    def _preflight(self) -> None:
        c = self.config
        for key in ("fixture", "metadata"):
            if not (REPO_ROOT / c[key]).is_file():
                raise LaunchError(f"{key} not found: {c[key]}")
        ports = [child.port for child in self.children]
        if len(set(ports)) != len(ports):
            raise LaunchError("port collision in configuration")
        busy = [p for p in ports if not port_is_free(c["tracker_host"], p)]
        if busy:
            raise LaunchError(f"port(s) already in use: {', '.join(map(str, busy))}")

    def _start(self, child: Child) -> None:
        env = dict(os.environ)
        env[run_log.ENV_VAR] = str(child.event_path)
        env[run_log.PROC_ENV_VAR] = child.proc_id
        env["BTL_RUN_ID"] = self.run_id
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        if child.role != "tracker":
            (self.dir / "peers" / child.proc_id).mkdir(parents=True, exist_ok=True)
        out = open(self.dir / "logs" / f"{child.proc_id}.out", "wb")
        err = open(self.dir / "logs" / f"{child.proc_id}.err", "wb")
        child.files = [out, err]
        child.launch_mono = time.monotonic()
        # Argument list, no shell. Output goes to files so pipes never fill.
        creationflags = (
            subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        )
        child.process = subprocess.Popen(
            child.command,
            cwd=REPO_ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            creationflags=creationflags,
        )

    def _wait_ready(self, child: Child, event_name: str) -> None:
        deadline = time.monotonic() + self.config["ready_timeout_s"]
        while time.monotonic() < deadline:
            for record in child.poll_events():
                if record["event"] == event_name:
                    child.ready_mono = record["mono"]
                    return
            code = child.process.poll()
            if code is not None:
                child.exit_code = code
                raise LaunchError(f"{child.proc_id} exited with code {code} before ready "
                                  f"(see logs/{child.proc_id}.err)")
            time.sleep(0.05)
        raise LaunchError(f"{child.proc_id} not ready within {self.config['ready_timeout_s']}s "
                          f"(no '{event_name}' event)")

    # ---- monitoring ----

    def _monitor(self) -> tuple[str, str]:
        c = self.config
        downloaders = [ch for ch in self.children if ch.role == "downloader"]
        target = designated_target(c)
        completed: set[str] = set()
        deadline = self.run_start + c["timeout_s"]

        while True:
            for child in self.children:
                for record in child.poll_events():
                    if record["event"] == "complete" and child.role == "downloader":
                        completed.add(child.proc_id)
                    if (c["scenario"] == "failure" and child.proc_id == target
                            and self.trigger is None and record["event"] == "progress"):
                        total = record.get("total") or 0
                        pct = 100.0 * record.get("pieces", 0) / total if total else 0.0
                        if pct >= c["failure_trigger_pct"]:
                            self._kill_target(child, pct)

            expected = {ch.proc_id for ch in downloaders}
            if c["scenario"] == "failure" and self.trigger is not None:
                expected.discard(target)
            if expected <= completed and (c["scenario"] != "failure" or self.trigger):
                return "ok", ""
            if c["scenario"] == "failure" and self.trigger is None and target in completed:
                return "not_executed", f"{target} completed before reaching the trigger"

            for child in self.children:
                if child.killed_by_harness or child.exit_code is not None:
                    continue
                code = child.process.poll()
                if code is not None:
                    child.exit_code = code
                    if child.proc_id not in completed or child.role != "downloader":
                        return "failed", f"{child.proc_id} exited unexpectedly with code {code}"

            if time.monotonic() >= deadline:
                missing = sorted(expected - completed)
                if c["scenario"] == "failure" and self.trigger is None:
                    return "not_executed", f"trigger never reached; timeout after {c['timeout_s']}s"
                return "timeout", f"not complete after {c['timeout_s']}s: {', '.join(missing)}"
            time.sleep(POLL_S)

    def _kill_target(self, child: Child, pct: float) -> None:
        # SIGKILL simulates a crash: no stopped announce, no clean close.
        child.killed_by_harness = True
        child.process.kill()
        now = time.monotonic()
        self.trigger = {"target": child.proc_id, "progress_pct": round(pct, 2),
                        "mono": now, "elapsed_s": round(now - self.run_start, 3)}
        run_log.emit("failure_injected", proc="launcher", **self.trigger)

    # ---- teardown ----

    
    def _stop_all(self) -> None:
        """Gracefully stop peers before the tracker, with forced cleanup as fallback."""
        import signal

        peers = [ch for ch in self.children if ch.role != "tracker"]
        trackers = [ch for ch in self.children if ch.role == "tracker"]

        # Signal clean stop for peers (especially on Windows where terminate() is SIGKILL)
        stop_file = self.dir / ".stop"
        try:
            stop_file.touch()
        except OSError:
            pass

        deadline = time.monotonic() + STOP_GRACE_S
        alive_peers = [ch for ch in peers if ch.process is not None and ch.process.poll() is None]
        for child in alive_peers:
            rem = max(0.05, deadline - time.monotonic())
            try:
                child.process.wait(timeout=min(1.5, rem))
            except subprocess.TimeoutExpired:
                pass

        for group in (peers, trackers):
            alive = [
                ch for ch in group
                if ch.process is not None and ch.process.poll() is None
            ]

            # Give each process a chance to perform normal shutdown.
            for child in alive:
                try:
                    if os.name == "nt":
                        child.process.send_signal(signal.CTRL_BREAK_EVENT)
                    else:
                        child.process.terminate()
                except (OSError, ValueError):
                    pass

            deadline = time.monotonic() + STOP_GRACE_S

            for child in alive:
                if child.process.poll() is not None:
                    continue

                try:
                    child.process.wait(
                        timeout=max(0.1, deadline - time.monotonic())
                    )
                except subprocess.TimeoutExpired:
                    child.process.terminate()
                    try:
                        child.process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        child.process.kill()
                        child.process.wait(timeout=5)

        for child in self.children:
            if child.process is not None and child.exit_code is None:
                child.exit_code = child.process.returncode

            for handle in child.files:
                handle.close()

            child.poll_events()

    def _check_outputs(self) -> dict:
        """Independent hash check of each downloader's output file."""
        metadata = json.loads((REPO_ROOT / self.config["metadata"]).read_text("utf-8"))
        expected = metadata.get("file_sha256")
        filename = metadata.get("filename", "")
        results = {}
        for child in self.children:
            if child.role != "downloader":
                continue
            out = self.dir / "peers" / child.proc_id / filename
            actual = sha256_file(out)
            results[child.proc_id] = None if actual is None else actual == expected
        return results

    # ---- main ----

    def execute(self) -> dict:
        c = self.config
        (self.dir / "events").mkdir(parents=True, exist_ok=True)
        (self.dir / "logs").mkdir(parents=True, exist_ok=True)
        status, reason = "failed", ""
        started_wall = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        self._plan_children()
        try:
            self._preflight()
            self.run_start = time.monotonic()
            tracker = self.children[0]
            self._start(tracker)
            self._wait_ready(tracker, "tracker_ready")
            for child in self.children[1:]:
                self._start(child)
                self._wait_ready(child, "listening")
                time.sleep(c["launch_gap_s"])
            status, reason = self._monitor()
        except LaunchError as error:
            status, reason = "failed", str(error)
        except KeyboardInterrupt:
            status, reason = "failed", "interrupted"
        finally:
            end = time.monotonic()
            self._stop_all()
            outputs = self._check_outputs() if (REPO_ROOT / c["metadata"]).is_file() else {}
            self.manifest = {
                "run_id": self.run_id,
                "status": status,
                "failure_reason": reason,
                "config": c,
                "revision": git_revision(),
                "environment": {
                    "label": c["environment"] + ("-synthetic" if c["synthetic"] else ""),
                    "python": platform.python_version(),
                    "platform": platform.platform(),
                    "hostname": platform.node(),
                },
                "file_sha256": sha256_file(REPO_ROOT / c["fixture"]),
                "file_bytes": (REPO_ROOT / c["fixture"]).stat().st_size
                if (REPO_ROOT / c["fixture"]).is_file() else None,
                "started_at": started_wall,
                "run_start_mono": self.run_start,
                "end_mono": end,
                "duration_s": None if self.run_start is None else round(end - self.run_start, 3),
                "target": designated_target(c),
                "trigger": self.trigger,
                "output_hash_ok": outputs,
                "processes": [{
                    "proc_id": ch.proc_id, "role": ch.role, "port": ch.port,
                    "command": ch.command, "launch_mono": ch.launch_mono,
                    "ready_mono": ch.ready_mono, "exit_code": ch.exit_code,
                    "killed_by_harness": ch.killed_by_harness,
                } for ch in self.children],
            }
            with open(self.dir / "manifest.json", "w", encoding="utf-8") as handle:
                json.dump(self.manifest, handle, indent=2)
        return self.manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run one BitTorrent-Lite swarm")
    parser.add_argument("config", nargs="?", help="JSON config file")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                        help="override a config value (JSON-parsed when possible)")
    parser.add_argument("--runs-dir", default=str(REPO_ROOT / "experiments" / "data" / "runs"))
    args = parser.parse_args(argv)

    config = load_config(args.config, args.set)
    manifest = Run(config, Path(args.runs_dir)).execute()
    print(f"{manifest['run_id']}: {manifest['status']}"
          + (f" ({manifest['failure_reason']})" if manifest["failure_reason"] else ""))
    print(f"  {Path(args.runs_dir) / manifest['run_id']}")
    return 0 if manifest["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
