"""Strict preparation supervisor for the original nine-by-three experiment.

This does not certify preparation readiness. Missing killed-peer observation
blocks the complete matrix before launch. Historical/permissive collector
output is never used as a semantic oracle. Run through recording.py's guardian.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
from datetime import datetime, timezone
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import platform
import random
import signal
import subprocess
import time

from .evidence import compare_files, file_oracle, strict_events, strict_json, verify_metadata
from .inventory import canonical_bytes, checked_path, compare_snapshots, digest_file, snapshot, write_json_new
from .recording import matching_process, observed_child_identity, register_process
from bittorrent_lite.experiments.scripts.launcher import Child, Run, REPO_ROOT, LaunchError, designated_target
from bittorrent_lite.experiments.scripts.matrix import plan_runs


class PreparationBlocked(RuntimeError):
    """Required provenance is absent; this is not a successful measurement."""


CONFIGURATIONS = {
    "swarm-L2": (2, 1, "rarest", "baseline"),
    "swarm-L4": (4, 1, "rarest", "baseline"),
    "swarm-L6": (6, 1, "rarest", "baseline"),
    "swarm-L8": (8, 1, "rarest", "baseline"),
    "select-random": (6, 1, "random", "baseline"),
    "select-sequential": (6, 1, "sequential", "baseline"),
    "seeders-S2": (6, 2, "rarest", "baseline"),
    "free-rider": (6, 1, "rarest", "free_rider"),
    "failure": (6, 1, "rarest", "failure"),
}
VARYING = {"name", "L", "S", "strategy", "scenario", "repeat", "seed"}
METRICS = {"messages_sent", "requests_sent", "retries", "hash_failures",
           "verified_download_bytes", "uploaded_payload_bytes"}
METHOD = {
    "distribution_origin": "first_peer_launch",
    "peer_completion_origin": "own_process_launch",
    "retries": "For each downloader and piece, every fully written REQUEST after its first fully written REQUEST, across all connections; failed or queued-only requests excluded.",
    "messages_sent": "One actual frame_sent with frame_complete=true; all eleven message types; count only at sender.",
    "uploaded_payload_bytes": "Sum PIECE payload_bytes from complete frame_sent, excluding headers and unacknowledged/partial writes.",
    "verified_download_bytes": "Sum bytes in unique piece_verified commits; duplicate ownership is an error, not extra useful bytes.",
    "hash_failures": "Count piece_verification events with outcome=hash_mismatch; local_io_error and length_mismatch are separate outcomes.",
    "failure_throughput": "Surviving expected downloader count times independently verified source bytes divided by distribution time; killed target excluded from useful completed bytes.",
    "availability": "At each event boundary: validated seeders own all pieces after listening; downloaders own a piece after piece_verified; exclude peers after exit event or independently recorded kill.",
}


def _number(value, label, *, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError(f"invalid {label}")
    return value


def _integer(value, label, *, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"invalid {label}")
    return value


def _digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _identity(config):
    return f"{config['name']}-r{config['repeat']}"


def _asset(config, key):
    return checked_path(REPO_ROOT / config[key], strict=True)


def revision_identity(repo, revision, source_freeze):
    """Read/hash Git identity without starting any helper process.

    The optional '-dirty' label is retained, not independently interpreted as a
    Git status result. The exact file tree is identified by source_freeze.
    """
    git = checked_path(Path(repo) / ".git", strict=True)
    files = []
    def read(path):
        path = checked_path(path, strict=True)
        raw = path.read_bytes()
        files.append({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)})
        return raw.decode("utf-8", errors="strict").strip()
    if git.is_file():
        pointer = read(git)
        if not pointer.startswith("gitdir: "):
            raise ValueError("invalid Git directory pointer")
        git = checked_path(git.parent / pointer[8:], strict=True)
    common = git
    if (git / "commondir").is_file():
        common = checked_path(git / read(git / "commondir"), strict=True)
    head = read(git / "HEAD")
    if head.startswith("ref: "):
        reference = head[5:]
        if not reference.startswith("refs/") or any(part in {"", ".", ".."} for part in reference.split("/")):
            raise ValueError("unsafe Git reference")
        loose = common / reference
        if loose.is_file():
            commit = read(loose)
        else:
            matches = [line.split(" ", 1)[0] for line in read(common / "packed-refs").splitlines()
                       if not line.startswith(("#", "^")) and line.endswith(" " + reference)]
            if len(matches) != 1:
                raise ValueError("Git reference cannot be resolved uniquely")
            commit = matches[0]
    else:
        commit = head
    if (len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit)
            or revision not in {commit, commit + "-dirty"}):
        raise ValueError("frozen revision label does not match independently read Git HEAD")
    return {"method": "direct-git-head-files-v1", "commit": commit, "revision_label": revision,
            "source_freeze": source_freeze, "dirty_status_recomputed": False, "files": files}


def _verify_tracker_probe(probe, metadata_hash, port):
    """Independently check the exact HTTP request and bounded response bytes."""
    request = bytes.fromhex(probe["request_body_hex"])
    expected = {"file_id": metadata_hash, "peer_id": "acceptance-readiness-probe",
                "listen_port": 65535, "event": "stopped"}
    if (probe["method"] != "POST" or probe["path"] != "/announce" or probe["host"] != "127.0.0.1"
            or probe["port"] != port or strict_json(request) != expected
            or hashlib.sha256(request).hexdigest() != probe["request_body_sha256"]
            or probe["request_headers"] != {"Content-Type": "application/json", "Content-Length": str(len(request))}):
        raise ValueError("tracker readiness request method/path/body/header oracle failed")
    raw = bytes.fromhex(probe["body_hex"])
    headers = probe["response_headers"]
    if (not isinstance(headers, list) or any(not isinstance(pair, list) or len(pair) != 2
            or any(not isinstance(value, str) for value in pair) for pair in headers)):
        raise ValueError("tracker readiness response header schema invalid")
    for name, wanted in (("content-type", "application/json"), ("content-length", str(len(raw)))):
        if [value for key, value in headers if key.lower() == name] != [wanted]:
            raise ValueError("tracker readiness response content headers invalid")
    value = strict_json(raw)
    if (probe["status"] != 200 or len(raw) > 65536
            or hashlib.sha256(raw).hexdigest() != probe["body_sha256"]
            or not isinstance(value, dict) or set(value) != {"interval", "peers"}
            or type(value["interval"]) is not int or value["interval"] != 5 or value["peers"] != []):
        raise ValueError("tracker readiness response bytes/schema oracle failed")
    return True


def make_plan(base_path, overrides, *, order_seed, source_freeze, revision, lane="acceptance"):
    """Use the preserved matrix API, then independently check its entire output."""
    _integer(order_seed, "order seed")
    plan = {"schema": 1, "lane": lane, "order_seed": order_seed,
            "source_freeze": source_freeze, "revision": revision, "host": platform.node(),
            "method": copy.deepcopy(METHOD), "configs": plan_runs(base_path, list(overrides), 3, None, order_seed)}
    plan["run_seeds"] = [next(c["seed"] for c in plan["configs"] if c["repeat"] == repeat)
                         for repeat in (1, 2, 3)]
    plan["sha256"] = _digest(plan)
    validate_plan(plan)
    return plan


def validate_plan(plan):
    required = {"schema", "lane", "order_seed", "source_freeze", "revision", "host",
                "method", "configs", "run_seeds", "sha256"}
    if not isinstance(plan, dict) or set(plan) != required or plan["schema"] != 1:
        raise ValueError("measured plan schema mismatch")
    if plan["sha256"] != _digest({k: v for k, v in plan.items() if k != "sha256"}):
        raise ValueError("measured plan digest mismatch")
    if (plan["lane"] not in {"acceptance", "diagnostic"} or plan["method"] != METHOD
            or not isinstance(plan["revision"], str) or plan["revision"] in {"", "unknown"}
            or not isinstance(plan["host"], str) or not plan["host"]
            or not isinstance(plan["source_freeze"], str) or len(plan["source_freeze"]) != 64
            or any(c not in "0123456789abcdef" for c in plan["source_freeze"])):
        raise ValueError("frozen method/revision/source/host/lane is required")
    _integer(plan["order_seed"], "order seed")
    configs = plan["configs"]
    if not isinstance(configs, list) or len(configs) != 27:
        raise ValueError("exactly 27 measured configs required")
    for config in configs:
        if not isinstance(config, dict) or not {"name", "repeat", "L", "S", "strategy", "scenario"} <= config.keys():
            raise ValueError("measured configuration schema incomplete")
        for field in ("L", "S", "repeat", "window", "piece_bytes", "upload_slots"):
            _integer(config.get(field), field, minimum=1)
        for field in ("peer_command", "tracker_command"):
            if (not isinstance(config.get(field), list) or not config[field]
                    or any(not isinstance(value, str) or not value for value in config[field])):
                raise ValueError("measured command must be a nonempty argument vector")
    expected_order = [(name, repeat) for name in CONFIGURATIONS for repeat in (1, 2, 3)]
    random.Random(plan["order_seed"]).shuffle(expected_order)
    actual_order = [(c["name"], c["repeat"]) for c in configs]
    if actual_order != expected_order:
        raise ValueError("missing/duplicate/misordered measured configuration")
    fixed = {k: v for k, v in configs[0].items() if k not in VARYING}
    seeds = {}
    for config in configs:
        name, repeat = config["name"], config["repeat"]
        if tuple(config[k] for k in ("L", "S", "strategy", "scenario")) != CONFIGURATIONS[name]:
            raise ValueError(f"wrong original configuration: {name}")
        if {k: v for k, v in config.items() if k not in VARYING} != fixed:
            raise ValueError("fixed experiment settings differ")
        if (config["synthetic"] is not False or config["window"] != 4 or config["piece_bytes"] != 65536
                or config["upload_slots"] != 2 or config["startup_method"] != "launch-sequence"
                or config["environment"] != "localhost" or config["tracker_host"] != "127.0.0.1"
                or config["failure_trigger_pct"] != 25):
            raise ValueError("unsupported/synthetic original comparison settings")
        _number(config["launch_gap_s"], "launch gap")
        _number(config["timeout_s"], "run timeout", positive=True)
        _number(config["ready_timeout_s"], "ready timeout", positive=True)
        _integer(config["seed"], "run seed")
        if repeat in seeds and seeds[repeat] != config["seed"]:
            raise ValueError("strategy comparisons must share each repetition's seed")
        seeds[repeat] = config["seed"]
        commands = " ".join(config["peer_command"] + config["tracker_command"])
        if ("stand_in" in commands or "bittorrent_lite.application.cli" not in config["peer_command"]
                or "bittorrent_lite.discovery.tracker_server" not in config["tracker_command"]):
            raise ValueError("real project peer/tracker commands required")
        if "--resource-metrics" not in config["peer_command"]:
            raise PreparationBlocked("measured peers require explicit --resource-metrics instrumentation")
    if [seeds[r] for r in (1, 2, 3)] != plan["run_seeds"] or len(set(seeds.values())) != 3:
        raise ValueError("three distinct predeclared run seeds required")
    return configs


FRAME = {"connection_id", "remote", "expected_remote", "local_endpoint", "remote_endpoint",
         "message_type", "request_id", "piece", "payload_bytes"}
LOG_FIELDS = {"log_schema", "log_sequence", "log_pid"}
RUNTIME = {"peer_id", "at"}
REQUEST = {"connection_id", "request_id", "piece", "remote"}
STATUS = {"state", "owned", "total", "connected_peers", "pending_requests", "control_queue_depth",
          "event_queue_depth", "verified_download_bytes", "uploaded_payload_bytes", "completion_seconds",
          "storage_error", "recovery_error"}
# Each entry is (required fields, optional fields). Unknown events/fields fail.
SCHEMAS = {
    "tracker_ready": ({"port"}, set()),
    "tracker_announce": ({"peer", "ip", "port", "announce_event", "returned", "members"}, set()),
    "tracker_rejected": ({"status", "reason"}, set()),
    "tracker_request_failed": ({"ip"}, set()),
    "listening": ({"port"}, set()),
    "complete": ({"final_hash_ok"}, set()),
    "counters": ({"verified_download_bytes", "uploaded_payload_bytes"}, METRICS),
    "exit": ({"reason"}, set()),
    "peers_discovered": ({"count", "announce_event"}, set()),
    "tracker_error": (set(), RUNTIME | {"category", "detail", "retry_in", "message"}),
    "connected": (RUNTIME | {"connection_id", "remote"}, set()),
    "connect_failed": (RUNTIME | {"remote", "message"}, set()),
    "piece_verified": (RUNTIME | REQUEST | {"bytes"}, set()),
    "piece_verification": (RUNTIME | REQUEST | {"outcome"}, {"bytes", "error_type"}),
    "piece_ignored": (RUNTIME | REQUEST | {"bytes", "reason"}, set()),
    "progress": (RUNTIME | {"pieces", "total"}, set()),
    "request_expired": (RUNTIME | {"connection_id", "request_id", "piece", "reason"}, set()),
    "scheduler_snapshot": (RUNTIME | {"reason", "event_queue_depth", "event_queue_capacity", "connected_peers",
                                         "neighbors", "pending", "pipeline_counters", "uploads", "owned"}, set()),
    "status": (RUNTIME | STATUS, set()),
    "resource_sample": (RUNTIME | {"metrics"}, set()),
    "resource_sample_unavailable": (RUNTIME | {"reason"}, set()),
    "resource_sample_error": (RUNTIME | {"error_type", "message"}, set()),
    "writer_queue": ({"connection_id", "remote", "reason", "depth", "capacity"}, set()),
    "frame_sent": (FRAME | {"frame_bytes", "frame_complete"}, set()),
    "frame_received": (FRAME | {"frame_bytes", "frame_complete"}, set()),
    "piece_uploaded": ({"piece", "request_id", "connection_id", "bytes", "to"}, set()),
    "frame_send_failed": (FRAME | {"frame_bytes", "partial_bytes_known", "error_type"}, set()),
    "frame_receive_failed": ({"connection_id", "remote", "received_bytes", "error_type"}, set()),
    "frame_rejected": (FRAME | {"error_type"}, set()),
}
MESSAGE_TYPES = {"HANDSHAKE", "BITFIELD", "HAVE", "INTERESTED", "NOT_INTERESTED", "CHOKE", "UNCHOKE",
                 "REQUEST", "PIECE", "CANCEL", "REJECT"}


def validate_event(row, proc):
    if not isinstance(row, dict) or row.get("proc") != proc or row.get("event") not in SCHEMAS:
        raise ValueError(f"unknown event/process schema: {proc}")
    required, optional = SCHEMAS[row["event"]]
    present_log = set(row) & LOG_FIELDS
    if present_log:
        if present_log != LOG_FIELDS or row["log_schema"] != "btl-log-v1":
            raise ValueError("invalid strict logger identity schema")
        _integer(row["log_sequence"], "event sequence")
        _integer(row["log_pid"], "event interpreter PID", minimum=1)
    fields = set(row) - {"mono", "proc", "event"} - LOG_FIELDS
    if not required <= fields or fields - required - optional:
        raise ValueError(f"missing/unknown telemetry fields: {row['event']}")
    _number(row.get("mono"), "event monotonic")
    if "peer_id" in row and row["peer_id"] != proc:
        raise ValueError("event peer identity differs from process")
    if "at" in row:
        _number(row["at"], "runtime timestamp")
    if row["event"] == "tracker_error" and fields not in (
            {"category", "detail", "retry_in"}, RUNTIME | {"message"}):
        raise ValueError("tracker error telemetry variant invalid")
    if row["event"] in {"piece_verified", "piece_verification", "piece_ignored", "piece_uploaded", "request_expired"}:
        _integer(row["piece"], "piece")
        _integer(row["connection_id"], "connection ID", minimum=1)
        if not 1 <= _integer(row["request_id"], "request ID") < 2 ** 63:
            raise ValueError("request identity outside v1")
        if "bytes" in row:
            _integer(row["bytes"], "piece bytes")
    if row["event"] in {"frame_sent", "frame_received"}:
        if row["frame_complete"] is not True or row["message_type"] not in MESSAGE_TYPES:
            raise ValueError("incomplete or unknown frame counted as complete")
        _integer(row["payload_bytes"], "payload bytes")
        if _integer(row["frame_bytes"], "frame bytes", minimum=5) <= row["payload_bytes"]:
            raise ValueError("frame has no encoded header")
        if row["message_type"] != "PIECE" and row["payload_bytes"] != 0:
            raise ValueError("control payload is not zero")
        if row["message_type"] in {"REQUEST", "PIECE", "CANCEL", "REJECT"}:
            _integer(row["connection_id"], "connection ID", minimum=1)
            if not 1 <= _integer(row["request_id"], "request ID") < 2 ** 63:
                raise ValueError("request identity outside v1")
            _integer(row["piece"], "piece")
        for field in ("local_endpoint", "remote_endpoint"):
            endpoint = row[field]
            if (not isinstance(endpoint, list) or len(endpoint) != 2 or endpoint[0] != "127.0.0.1"
                    or type(endpoint[1]) is not int or not 1 <= endpoint[1] <= 65535):
                raise ValueError("actual loopback frame endpoints required")
    if row["event"] == "piece_verification":
        if row["outcome"] not in {"stored", "hash_mismatch", "length_mismatch", "local_io_error", "store_rejected_unclassified"}:
            raise ValueError("unknown verification outcome")
        needed = "error_type" if row["outcome"] == "local_io_error" else "bytes"
        if needed not in row:
            raise ValueError("verification outcome lacks required detail")
    if row["event"] == "writer_queue":
        if _integer(row["depth"], "queue depth") > _integer(row["capacity"], "queue capacity", minimum=1):
            raise ValueError("writer queue exceeds declared capacity")
    return row


class StrictChild(Child):
    """Preserve incomplete trailing bytes while live; reject every bad full row."""
    def poll_events(self):
        if not self.event_path.exists():
            return []
        with self.event_path.open("rb") as stream:
            stream.seek(self._offset)
            raw = stream.read()
        end = raw.rfind(b"\n")
        if end < 0:
            return []
        new = []
        previous = self.events[-1]["mono"] if self.events else -math.inf
        for line in raw[:end].split(b"\n"):
            row = validate_event(strict_json(line), self.proc_id)
            if getattr(self, "require_sequence", False) and (
                    row.get("log_sequence") != len(self.events) + len(new)
                    or row.get("log_schema") != "btl-log-v1"
                    or (getattr(self, "interpreter_pid", None) is not None
                        and row.get("log_pid") != self.interpreter_pid)):
                raise ValueError("missing/reordered live event or wrong observed interpreter PID")
            if row["mono"] < previous:
                raise ValueError("nonmonotonic live event stream")
            previous = row["mono"]
            if (row["event"] == "resource_sample_error"
                    or row["event"] == "status" and (row["state"] == "ERROR" or row["storage_error"] or row["recovery_error"])
                    or row["event"] == "piece_verification" and row["outcome"] != "stored"):
                raise RuntimeError(f"unexpected measured-run fault in {self.proc_id}: {row['event']}")
            new.append(row)
        self._offset += end + 1
        self.events.extend(new)
        return new


class GuardedRun(Run):
    """Run API with explicit child ownership and append-only supervisor facts."""
    def __init__(self, config, runs_dir, *, source_freeze, revision, registry, lane):
        if lane == "acceptance":
            raise PreparationBlocked("acceptance launch requires independently validated OS source-denial isolation; command-line absence alone is insufficient")
        super().__init__(copy.deepcopy(config), runs_dir)
        self.source_freeze, self.expected_revision = source_freeze, revision
        self.registry = checked_path(registry, strict=True)
        self.lane = lane
        self.supervision = {"schema": 1, "lane": lane, "run_id": self.run_id,
                            "source_freeze": source_freeze, "revision": revision,
                            "host": platform.node(), "processes": {}, "kills": [], "cleanup": [],
                            "started_mono": None, "finished_mono": None}

    def _audit(self, event, **fields):
        row = {"schema": "btl-measured-supervisor-v1", "event": event,
               "run_id": self.run_id, "source_freeze": self.source_freeze,
               "mono": time.monotonic(), "utc": datetime.now(timezone.utc).isoformat(), **fields}
        with (self.dir / "supervision.jsonl").open("ab", buffering=0) as stream:
            stream.write(canonical_bytes(row) + b"\n")
            os.fsync(stream.fileno())
        return row

    def _plan_children(self):
        super()._plan_children()
        self.children = [StrictChild(c.proc_id, c.role, c.port, c.command, c.event_path) for c in self.children]
        for child in self.children:
            child.require_sequence = True

    def _start(self, child):
        if child.event_path.exists():
            raise FileExistsError("child event stream must be fresh")
        if child.role == "downloader" and ("--file" in child.command or "--seeder" in child.command):
            raise ValueError("downloader must not receive source-file arguments")
        if child.role == "seeder":
            self._audit("source_checked_for_seeder", proc_id=child.proc_id,
                        oracle=file_oracle(_asset(self.config, "fixture")))
        self._audit("spawn_requested", proc_id=child.proc_id, argv=child.command)
        env = dict(os.environ)
        env.update(BTL_EVENT_LOG=str(child.event_path), BTL_PROC_ID=child.proc_id,
                   BTL_RUN_ID=self.run_id, BTL_LOG_STRICT="1", PYTHONUNBUFFERED="1",
                   PYTHONPATH=str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", ""))
        if child.role != "tracker":
            (self.dir / "peers" / child.proc_id).mkdir(parents=True, exist_ok=False)
        child.files = [open(self.dir / "logs" / f"{child.proc_id}.{suffix}", "xb") for suffix in ("out", "err")]
        child.launch_mono = time.monotonic()
        child.process = subprocess.Popen(child.command, cwd=REPO_ROOT, env=env, stdin=subprocess.DEVNULL,
                                         stdout=child.files[0], stderr=child.files[1],
                                         creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
        # This is the first action after Popen returns.
        identity = register_process(self.registry, child.process.pid,
                                    owner_run=self.run_id, role=child.role,
                                    stop_file=None if child.role == "tracker" else self.dir / ".stop")
        import psutil
        actual_environment = psutil.Process(child.process.pid).environ()
        environment = {key: actual_environment.get(key) for key in (
            "BTL_EVENT_LOG", "BTL_PROC_ID", "BTL_RUN_ID", "BTL_LOG_STRICT", "PYTHONPATH", "COVERAGE_PROCESS_START",
            "COVERAGE_FILE", "BTL_COVERAGE_ROOT", "ACCEPTANCE_PROCESS_REGISTRY")}
        registry_file = self.registry / f"{identity['pid']}-{identity['creation_time']:.9f}.json"
        entry = {"identity": identity, "registry_file": str(registry_file),
                 "registry_sha256": digest_file(registry_file), "argv": list(child.command),
                 "launch_mono": child.launch_mono, "environment": environment,
                 "executable_sha256": digest_file(Path(identity["executable"])),
                 "exit_code": None, "observed_exit_mono": None}
        self.supervision["processes"][child.proc_id] = entry
        self._audit("child_registered", proc_id=child.proc_id, **entry)

    def _observe_interpreter(self, child):
        """Bind strict log PID to OS observation, never to the log's own claim.

        Windows venv launchers may be wrappers. This is a readiness-time
        descendant observation; it does not claim interception of internal spawn.
        """
        import psutil
        entry = self.supervision["processes"][child.proc_id]
        parent = matching_process(entry["identity"])
        if parent is None:
            raise ValueError("owned process disappeared before interpreter observation")
        candidates = []
        observed = [parent, *parent.children(recursive=True)]
        for process in observed:
            try:
                environment = process.environ()
                if (process.cmdline()[1:] == child.command[1:]
                        and environment.get("BTL_PROC_ID") == child.proc_id
                        and environment.get("BTL_RUN_ID") == self.run_id
                        and environment.get("BTL_LOG_STRICT") == "1"
                        and checked_path(environment["BTL_EVENT_LOG"]) == child.event_path):
                    candidates.append(process)
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
        parents = {process.ppid() for process in candidates}
        leaves = [process for process in candidates if process.pid not in parents]
        if len(leaves) != 1:
            raise ValueError("actual event interpreter cannot be independently identified uniquely")
        actual = leaves[0]
        chain = [actual]
        while chain[-1].pid != parent.pid:
            ancestor = chain[-1].parent()
            if ancestor is None or len(chain) > 8:
                raise ValueError("interpreter ancestry does not reach owned Popen process")
            chain.append(ancestor)
        identities = [entry["identity"]]
        for process in reversed(chain[:-1]):
            captured = observed_child_identity(process)
            if captured is None:
                raise ValueError("interpreter identity changed or exited during observation")
            identities.append(register_process(self.registry, process.pid, owner_run=self.run_id,
                role=child.role + ("-interpreter" if process.pid == actual.pid else "-runtime-wrapper"),
                stop_file=None if child.role == "tracker" else self.dir / ".stop", expected_identity=captured))
        identity = identities[-1]
        registry_file = self.registry / f"{identity['pid']}-{identity['creation_time']:.9f}.json"
        observation = {"method": "independent-live-process-tree-and-environment-v1", "identity": identity,
                       "ancestry": identities, "registry_file": str(registry_file),
                       "registry_sha256": digest_file(registry_file),
                       "executable_sha256": digest_file(Path(identity["executable"])),
                       "environment": {key: actual.environ().get(key) for key in
                                       ("BTL_PROC_ID", "BTL_RUN_ID", "BTL_EVENT_LOG", "BTL_LOG_STRICT")}}
        entry["interpreter"] = observation
        self._audit("interpreter_observed", proc_id=child.proc_id, observation=observation)
        child.interpreter_pid = identity["pid"]
        if any(row.get("log_pid") != identity["pid"] for row in child.events):
            raise ValueError("strict event PID differs from independently observed interpreter")

    def _wait_ready(self, child, event_name):
        super()._wait_ready(child, event_name)
        self._observe_interpreter(child)
        if child.role == "tracker":
            # A stopped announce validates HTTP/schema without admitting a probe
            # into the swarm. Source identity is the exact metadata-file digest.
            metadata_hash = digest_file(_asset(self.config, "metadata"))
            payload = canonical_bytes({"file_id": metadata_hash, "peer_id": "acceptance-readiness-probe",
                                       "listen_port": 65535, "event": "stopped"})
            headers = {"Content-Type": "application/json", "Content-Length": str(len(payload))}
            request = {"method": "POST", "path": "/announce", "host": "127.0.0.1", "port": child.port,
                       "request_headers": headers, "request_body_hex": payload.hex(),
                       "request_body_sha256": hashlib.sha256(payload).hexdigest()}
            self._audit("tracker_http_requested", **request)
            connection = http.client.HTTPConnection("127.0.0.1", child.port, timeout=2)
            try:
                connection.request("POST", "/announce", body=payload, headers=headers)
                response = connection.getresponse()
                raw = response.read(65537)
                probe = self._audit("tracker_http_response", **request, status=response.status,
                    response_headers=[list(pair) for pair in response.getheaders()], body_hex=raw.hex(),
                    body_sha256=hashlib.sha256(raw).hexdigest())
                _verify_tracker_probe(probe, metadata_hash, child.port)
            finally:
                connection.close()
        self._audit("child_ready", proc_id=child.proc_id, ready_event=event_name, ready_mono=child.ready_mono)

    def _kill_target(self, child, pct):
        child.poll_events()
        if any(row["event"] == "complete" for row in child.events):
            raise RuntimeError("failure scenario not executed: target already completed")
        entry = self.supervision["processes"][child.proc_id]
        identity = entry["interpreter"]["identity"]
        actual = matching_process(identity)
        if child.process.poll() is not None or matching_process(entry["identity"]) is None or actual is None:
            raise RuntimeError("failure target was not alive with its registered identity")
        owned = {row["piece"] for row in child.events if row["event"] == "piece_verified"}
        total = len(self.supervision["source_before"]["pieces"])
        actual_pct = 100 * len(owned) / total
        if not 25 <= actual_pct < 100 or pct < 25:
            raise RuntimeError("failure must occur at verified progress >=25% and before completion")
        request = self._audit("kill_requested", proc_id=child.proc_id, identity=identity,
                              verified_pieces=sorted(owned), total_pieces=total,
                              verified_pct=actual_pct, alive=True, complete_seen=False,
                              mechanism="psutil-TerminateProcess-SIGTERM" if os.name == "nt" else "SIGKILL")
        child.killed_by_harness = True
        actual.kill()
        now = time.monotonic()
        self.trigger = {"target": child.proc_id, "progress_pct": round(actual_pct, 2),
                        "mono": now, "elapsed_s": round(now - self.run_start, 3)}
        issued = self._audit("kill_issued", proc_id=child.proc_id, identity=identity,
                             manifest_trigger=copy.deepcopy(self.trigger))
        self.supervision["kills"].append({"requested": request, "issued": issued})

    def _stop_all(self):
        """Bounded peer stop, then explicitly declared tracker termination.

        Forced cleanup of an ordinary peer is retained as a failure. The tracker
        has no stop-file channel; its identity-checked termination is deliberate.
        """
        from .recording import stop_owned
        errors = []
        stop = self.dir / ".stop"
        if stop.exists():
            errors.append("stop-file unexpectedly existed before cleanup")
        else:
            stop.touch(exist_ok=False)
        self._audit("peer_stop_requested", stop_file=str(stop))
        deadline = time.monotonic() + 8
        for child in self.children:
            if child.process is None or child.role == "tracker":
                continue
            entry = self.supervision["processes"].get(child.proc_id)
            if entry is None:
                errors.append(f"unregistered spawned child: {child.proc_id}")
                # Owned Popen is still authoritative emergency cleanup if child
                # registration failed. Do not touch any other process.
                if child.process.poll() is None:
                    child.process.terminate()
            try:
                child.process.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                errors.append(f"peer required forced cleanup: {child.proc_id}")
                if entry is not None:
                    errors.extend(stop_owned(entry.get("interpreter", {}).get("ancestry", [entry["identity"]]),
                                             self.dir / "emergency-cleanup.jsonl",
                                             grace_s=0, terminate_s=2))
                else:
                    child.process.kill()
                child.process.wait(timeout=3)
            if not child.killed_by_harness and child.process.returncode != 0:
                errors.append(f"peer exit {child.proc_id}: {child.process.returncode}")
        for child in self.children:
            if child.role != "tracker" or child.process is None:
                continue
            entry = self.supervision["processes"].get(child.proc_id)
            if child.process.poll() is not None:
                errors.append("tracker exited before declared cleanup")
            elif entry is not None and matching_process(entry["identity"]) is not None:
                actual_identity = entry.get("interpreter", {}).get("identity", entry["identity"])
                actual = matching_process(actual_identity)
                if actual is None:
                    errors.append("tracker interpreter exited before declared cleanup")
                    continue
                action = self._audit("tracker_termination_requested", proc_id=child.proc_id,
                                     identity=actual_identity, mechanism="psutil-TerminateProcess-SIGTERM" if os.name == "nt" else "SIGTERM")
                self.supervision["cleanup"].append(action)
                actual.terminate()
                try:
                    child.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    errors.append("tracker termination exceeded deadline")
                    stop_owned(entry.get("interpreter", {}).get("ancestry", [entry["identity"]]),
                               self.dir / "emergency-cleanup.jsonl", grace_s=0, terminate_s=1)
            else:
                errors.append("tracker identity missing or changed during cleanup")
                if entry is None and child.process.poll() is None:
                    child.process.terminate()
                    child.process.wait(timeout=3)
        for child in self.children:
            if child.process is not None:
                child.exit_code = child.process.poll()
                row = self._audit("child_exit_observed", proc_id=child.proc_id, exit_code=child.exit_code,
                                  killed_by_harness=child.killed_by_harness)
                entry = self.supervision["processes"].get(child.proc_id)
                if entry is not None:
                    entry.update(exit_code=child.exit_code, observed_exit_mono=row["mono"])
                    for identity in entry.get("interpreter", {}).get("ancestry", [entry["identity"]]):
                        if matching_process(identity) is not None:
                            errors.append(f"owned child/interpreter still alive: {child.proc_id}/{identity['pid']}")
            for stream in child.files:
                stream.close()
            # A killed final partial record remains preserved for strict_events;
            # malformed earlier completed records still raise here.
            try:
                child.poll_events()
            except (ValueError, RuntimeError) as exc:
                errors.append(f"invalid final telemetry {child.proc_id}: {exc}")
        self.supervision["cleanup_errors"] = errors
        if errors:
            raise RuntimeError("; ".join(errors))

    def execute(self):
        """Use Run orchestration APIs without its unregistered git helpers."""
        self.dir = checked_path(self.dir)
        self.dir.mkdir(parents=True, exist_ok=False)
        self.supervision["started_mono"] = time.monotonic()
        self.supervision["source_before"] = file_oracle(_asset(self.config, "fixture"))
        self.supervision["revision_identity"] = revision_identity(REPO_ROOT, self.expected_revision, self.source_freeze)
        self._audit("launcher_started", lane=self.lane, revision=self.expected_revision)
        status, reason = "failed", ""
        started_wall = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        (self.dir / "events").mkdir()
        (self.dir / "logs").mkdir()
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
                time.sleep(self.config["launch_gap_s"])
            status, reason = self._monitor()
        except LaunchError as exc:
            status, reason = "failed", str(exc)
        except KeyboardInterrupt:
            status, reason = "failed", "interrupted"
            raise
        except BaseException as exc:
            status, reason = "failed", f"{type(exc).__name__}: {exc}"
            raise
        finally:
            end = time.monotonic()
            try:
                self._stop_all()
            finally:
                # Preserve records even if cleanup or source revalidation fails.
                self.supervision["finished_mono"] = time.monotonic()
                try:
                    self.supervision["source_after"] = file_oracle(_asset(self.config, "fixture"))
                except (OSError, ValueError) as exc:
                    self.supervision["source_after"] = None
                    self.supervision["source_after_error"] = f"{type(exc).__name__}: {exc}"
                self._audit("launcher_finished", observed_processes=sorted(self.supervision["processes"]))
                self.supervision["audit_sha256"] = digest_file(self.dir / "supervision.jsonl")
                self.supervision["raw_logs"] = {
                    p.relative_to(self.dir).as_posix(): {"size": p.stat().st_size, "sha256": digest_file(p)}
                    for p in sorted((self.dir / "logs").glob("*")) if p.is_file()}
                write_json_new(self.dir / "supervision.json", self.supervision)
                after = self.supervision["source_after"]
                self.manifest = {
                    "run_id": self.run_id, "status": status, "failure_reason": reason, "config": self.config,
                    "revision": self.expected_revision,
                    "environment": {"label": self.config["environment"], "python": platform.python_version(),
                                    "platform": platform.platform(), "hostname": platform.node()},
                    "file_sha256": after["sha256"] if after else None, "file_bytes": after["size"] if after else None,
                    "started_at": started_wall, "run_start_mono": self.run_start, "end_mono": end,
                    "duration_s": None if self.run_start is None else round(end - self.run_start, 3),
                    "target": designated_target(self.config), "trigger": self.trigger,
                    "output_hash_ok": self._check_outputs() if _asset(self.config, "metadata").is_file() else {},
                    "processes": [{"proc_id": child.proc_id, "role": child.role, "port": child.port,
                        "command": child.command, "launch_mono": child.launch_mono, "ready_mono": child.ready_mono,
                        "exit_code": child.exit_code, "killed_by_harness": child.killed_by_harness} for child in self.children],
                }
                write_json_new(self.dir / "manifest.json", self.manifest)
        return self.manifest


def _exact_once(events, kind):
    found = [row for row in events if row["event"] == kind]
    if len(found) != 1:
        raise ValueError(f"expected exactly one {kind}, found {len(found)}")
    return found[0]


def _frame_identity(row):
    return (row["connection_id"], row["request_id"], row["piece"], row["payload_bytes"])


def derive_peer_metrics(events, proc, oracle, *, killed=False):
    """Independent event arithmetic; no collect.py or product storage imports."""
    for row in events:
        validate_event(row, proc)
    _exact_once(events, "listening")
    if killed:
        # A complete final line is insufficient: a kill can occur between an
        # actual socket write/commit and its log call. Do not invent final totals.
        raise PreparationBlocked(f"{proc}: killed-peer final metrics need a separately validated observer")
    counters = _exact_once(events, "counters")
    exit_event = _exact_once(events, "exit")
    if exit_event["reason"] != "stopped" or events[-1] != exit_event or counters["mono"] > exit_event["mono"]:
        raise ValueError("peer lacks a complete clean telemetry lifetime")
    frames = [row for row in events if row["event"] == "frame_sent"]
    requests = [row for row in frames if row["message_type"] == "REQUEST"]
    uploads = [row for row in frames if row["message_type"] == "PIECE"]
    if len({(row["connection_id"], row["request_id"]) for row in requests}) != len(requests):
        raise ValueError("duplicate fully written request identity")
    if len({(row["connection_id"], row["request_id"]) for row in uploads}) != len(uploads):
        raise ValueError("duplicate fully written upload identity")
    uploaded_events = Counter((row["connection_id"], row["request_id"], row["piece"], row["bytes"])
                              for row in events if row["event"] == "piece_uploaded")
    if uploaded_events != Counter(_frame_identity(row) for row in uploads):
        raise ValueError("PIECE write and upload acknowledgment records disagree")
    commits = [row for row in events if row["event"] == "piece_verified"]
    if len({row["piece"] for row in commits}) != len(commits):
        raise ValueError("duplicate piece ownership commit")
    verification = [row for row in events if row["event"] == "piece_verification"]
    for row in commits:
        index = _integer(row["piece"], "committed piece")
        if index >= len(oracle["pieces"]) or row["bytes"] != oracle["pieces"][index]["size"]:
            raise ValueError("verified piece byte count differs from independent oracle")
        matches = [v for v in verification if v["outcome"] == "stored"
                   and all(v[key] == row[key] for key in ("connection_id", "request_id", "piece", "bytes"))
                   and v["mono"] <= row["mono"]]
        if len(matches) != 1:
            raise ValueError("commit lacks exactly one stored verification result")
    counts = Counter(row["piece"] for row in requests)
    derived = {"messages_sent": len(frames), "requests_sent": len(requests),
               "retries": sum(count - 1 for count in counts.values()),
               "hash_failures": sum(row["outcome"] == "hash_mismatch" for row in verification),
               "verified_download_bytes": sum(row["bytes"] for row in commits),
               "uploaded_payload_bytes": sum(row["payload_bytes"] for row in uploads)}
    for key in METRICS & counters.keys():
        if _integer(counters[key], key) != derived[key]:
            raise ValueError(f"final {key} disagrees with independently derived event total")
    writer = [row for row in events if row["event"] == "writer_queue"]
    scheduler = [row for row in events if row["event"] == "scheduler_snapshot"]
    resources = [row for row in events if row["event"] == "resource_sample"]
    if not writer or not scheduler or not resources:
        raise PreparationBlocked("required writer/scheduler/resource telemetry absent")
    resource_keys = {"rss_bytes", "thread_count", "tcp_socket_count", "cpu_user_s", "cpu_system_s"}
    maxima = {}
    for row in resources:
        metrics = row["metrics"]
        if (not isinstance(metrics, dict) or not resource_keys <= metrics.keys()
                or (set(metrics) - resource_keys) not in ({"handle_count"}, {"file_descriptor_count"})):
            raise ValueError("unknown or missing resource telemetry fields")
        for key, value in metrics.items():
            maxima[key] = max(maxima.get(key, value), _number(value, key))
    for row in scheduler:
        if _integer(row["event_queue_depth"], "event queue") > _integer(row["event_queue_capacity"], "event capacity", minimum=1):
            raise ValueError("coordinator ingress exceeds capacity")
        if not isinstance(row["pending"], list) or not isinstance(row["neighbors"], dict):
            raise ValueError("scheduler inventory shape invalid")
    return {**derived, "writer_queue_max": max(row["depth"] for row in writer),
            "event_queue_max": max(row["event_queue_depth"] for row in scheduler),
            "pending_total_max": max(len(row["pending"]) for row in scheduler),
            "resource_maxima": maxima, "lifetime_end": exit_event["mono"]}


def verify_network_provenance(streams):
    """Every ownership commit must follow real receive and matching remote send."""
    sent = {(proc, tuple(row["local_endpoint"]), tuple(row["remote_endpoint"]), row["request_id"],
             row["piece"], row["payload_bytes"])
            for proc, events in streams.items() for row in events
            if row["event"] == "frame_sent" and row["message_type"] == "PIECE"}
    for proc, events in streams.items():
        for commit in (row for row in events if row["event"] == "piece_verified"):
            received = [row for row in events if row["event"] == "frame_received" and row["message_type"] == "PIECE"
                        and all(row[key] == commit[key] for key in ("connection_id", "request_id", "piece", "remote"))
                        and row["payload_bytes"] == commit["bytes"] and row["mono"] <= commit["mono"]]
            if len(received) != 1:
                raise ValueError(f"{proc} commit lacks unique actual PIECE receive")
            row = received[0]
            remote_key = (row["remote"], tuple(row["remote_endpoint"]), tuple(row["local_endpoint"]),
                          row["request_id"], row["piece"], row["payload_bytes"])
            if row["remote"] == proc or remote_key not in sent:
                raise ValueError(f"{proc} commit lacks matching independent remote send")


def availability_rows(streams, roles, lifetimes, *, origin, finish, pieces):
    changes = []
    for proc, events in streams.items():
        if roles[proc] == "tracker":
            continue
        start, end = lifetimes[proc]
        changes.extend([(start, 0, proc, None), (end, 2, proc, None)])
        if roles[proc] == "downloader":
            changes.extend((row["mono"], 1, proc, row["piece"]) for row in events if row["event"] == "piece_verified")
    owned, live, result = {}, set(), []
    for at, kind, proc, piece in sorted(changes):
        if kind == 0:
            live.add(proc)
            owned[proc] = set(range(pieces)) if roles[proc] == "seeder" else set()
        elif kind == 2:
            live.discard(proc)
        else:
            if proc not in live or piece in owned[proc] or not 0 <= piece < pieces:
                raise ValueError("piece ownership event outside valid peer lifetime")
            owned[proc].add(piece)
        if origin <= at <= finish:
            counts = [sum(index in owned[peer] for peer in live) for index in range(pieces)]
            result.append({"at_mono": at, "distribution_elapsed_s": at - origin,
                           "live_peers": len(live), "min_owners": min(counts),
                           "mean_owners": sum(counts) / pieces, "max_owners": max(counts)})
    return result


def _verify_initial_seeder(records, metrics, complete, process, source, output, oracle, source_check):
    """An initial source-ready assembly is not a newly completed download.

    The CLI emits COMPLETE after assembling an already complete seed as well as
    after downloading. Retain that evidence, but require independently checked
    initial ownership and zero newly downloaded credit before excluding it from
    downloader timing/population arithmetic.
    """
    if len(complete) != 1 or complete[0]["final_hash_ok"] is not True:
        raise ValueError("initial seeder requires exactly one verified source-ready event")
    command = process["command"]
    if (command.count("--seeder") != 1 or command.count("--file") != 1
            or command.index("--file") + 1 == len(command)
            or checked_path(command[command.index("--file") + 1], strict=True) != source
            or source_check["mono"] > process["launch_mono"]):
        raise ValueError("initial seeder source was not independently checked before launch")
    if (any(metrics[key] != 0 for key in ("verified_download_bytes", "requests_sent", "retries", "hash_failures"))
            or any(row["event"] in {"piece_verified", "piece_verification"}
                   or row["event"] == "frame_received" and row["message_type"] == "PIECE" for row in records)):
        raise ValueError("initial seeder has invented download/request/commit credit")
    snapshots = [row for row in records if row["event"] == "scheduler_snapshot"]
    pieces = len(oracle["pieces"])
    if (not snapshots or records.index(snapshots[0]) >= records.index(complete[0])
            or any(type(row["owned"]) is not int or row["owned"] != pieces or row["pending"] for row in snapshots)):
        raise ValueError("initial seeder lacks full pre-completion ownership throughout its lifetime")
    statuses = [row for row in records if row["event"] == "status"]
    if (not any(row["state"] == "SEEDING" and row["mono"] >= complete[0]["mono"] for row in statuses)
            or any(type(row[key]) is not int or row[key] != pieces for row in statuses for key in ("owned", "total"))
            or any(type(row["verified_download_bytes"]) is not int or row["verified_download_bytes"] != 0 for row in statuses)):
        raise ValueError("initial seeder status contradicts verified source ownership or zero download credit")
    compare_files(source, checked_path(output, strict=True), oracle)


def verify_run(run_dir, config, *, source_freeze, revision, lane="acceptance"):
    """Reject semantic failure even when launcher and process exits say success.

    Killed-peer observation is explicitly not implemented. A callback returning
    scalar totals would not prove independent full-lifetime coverage. No flag can
    turn missing observer evidence into a completed measurement.
    """
    run_dir = checked_path(run_dir, strict=True)
    if lane == "acceptance":
        raise PreparationBlocked("acceptance semantics require independently validated OS source-denial evidence; this verifier currently supports diagnostic validation only")
    manifest = strict_json((run_dir / "manifest.json").read_bytes())
    supervision = strict_json((run_dir / "supervision.json").read_bytes())
    if (manifest.get("status") != "ok" or manifest.get("failure_reason") != ""
            or manifest.get("config") != config or manifest.get("revision") != revision
            or config.get("synthetic") is not False):
        raise ValueError("failed/synthetic/mixed-configuration or revision manifest")
    if (supervision.get("source_freeze") != source_freeze or supervision.get("revision") != revision
            or supervision.get("run_id") != manifest.get("run_id") or supervision.get("lane") != lane
            or supervision.get("cleanup_errors") != []
            or manifest["environment"].get("hostname") != supervision.get("host")
            or manifest["environment"].get("label") != "localhost"):
        raise ValueError("missing or inconsistent supervisor provenance")
    if supervision.get("revision_identity") != revision_identity(REPO_ROOT, revision, source_freeze):
        raise ValueError("Git HEAD/reference files differ from frozen revision evidence")
    audit_path = run_dir / "supervision.jsonl"
    if digest_file(audit_path) != supervision.get("audit_sha256"):
        raise ValueError("supervisor trace digest mismatch")
    audit_raw = audit_path.read_bytes()
    if not audit_raw.endswith(b"\n"):
        raise ValueError("supervisor trace truncated")
    audit = [strict_json(line) for line in audit_raw.splitlines()]
    if not audit or audit[0]["event"] != "launcher_started" or audit[-1]["event"] != "launcher_finished":
        raise ValueError("supervisor lifecycle incomplete")
    previous = -math.inf
    for row in audit:
        if (row.get("run_id") != manifest["run_id"] or row.get("source_freeze") != source_freeze
                or _number(row.get("mono"), "audit timestamp") < previous):
            raise ValueError("supervisor trace identity/time mismatch")
        previous = row["mono"]
    source, metadata = _asset(config, "fixture"), _asset(config, "metadata")
    checked = verify_metadata(source, metadata)
    oracle = file_oracle(source)
    filename = strict_json(metadata.read_bytes())["filename"]
    if lane == "acceptance" and oracle["size"] != 64 * 1024 * 1024:
        raise ValueError("primary measured fixture must be exactly 64 MiB")
    if (manifest.get("file_sha256") != oracle["sha256"] or manifest.get("file_bytes") != oracle["size"]
            or supervision.get("source_before") != oracle or supervision.get("source_after") != oracle):
        raise ValueError("source changed or independently computed source oracle differs")
    seeder_checks = [row for row in audit if row["event"] == "source_checked_for_seeder"]
    if ({row["proc_id"] for row in seeder_checks} != {f"seed-{i:02d}" for i in range(1, config["S"] + 1)}
            or len(seeder_checks) != config["S"] or any(row["oracle"] != oracle for row in seeder_checks)):
        raise ValueError("each seeder requires its own independently recorded source validation")
    expected = {"tracker": "tracker", **{f"seed-{i:02d}": "seeder" for i in range(1, config["S"] + 1)},
                **{f"peer-{i:02d}": "downloader" for i in range(1, config["L"] + 1)}}
    processes = manifest.get("processes")
    if not isinstance(processes, list) or [row.get("proc_id") for row in processes] != list(expected):
        raise ValueError("missing/duplicate/misordered child identity")
    if set(supervision["processes"]) != set(expected):
        raise ValueError("registered child inventory differs")
    recorded_events = {p.name for p in (run_dir / "events").iterdir() if p.is_file()}
    if recorded_events != {f"{proc}.jsonl" for proc in expected}:
        raise ValueError("dedicated event stream inventory differs")
    raw_logs = {f"logs/{proc}.{suffix}" for proc in expected for suffix in ("out", "err")}
    if set(supervision["raw_logs"]) != raw_logs:
        raise ValueError("raw stdout/stderr inventory differs")
    for name, recorded in supervision["raw_logs"].items():
        path = checked_path(run_dir / name, strict=True)
        if path.stat().st_size != recorded["size"] or digest_file(path) != recorded["sha256"]:
            raise ValueError("raw stdout/stderr changed after recording")
    tracker_cleanup = [row for row in audit if row["event"] == "tracker_termination_requested"]
    if len(tracker_cleanup) != 1 or tracker_cleanup != supervision["cleanup"]:
        raise ValueError("tracker cleanup was not precisely predeclared/observed")
    requests = [row for row in audit if row["event"] == "tracker_http_requested"]
    probes = [row for row in audit if row["event"] == "tracker_http_response"]
    if len(probes) != 1 or len(requests) != 1:
        raise ValueError("missing/duplicate actual tracker HTTP readiness probe")
    probe = probes[0]
    if requests[0]["mono"] > probe["mono"] or any(requests[0][key] != probe[key] for key in (
            "method", "path", "host", "port", "request_headers", "request_body_hex", "request_body_sha256")):
        raise ValueError("tracker readiness request and response records do not match")
    _verify_tracker_probe(probe, digest_file(metadata), config["tracker_port"])
    target = f"peer-{config['L']:02d}" if config["scenario"] != "baseline" else None
    failure = config["scenario"] == "failure"
    if manifest.get("target") != target:
        raise ValueError("scenario target mismatch")
    kills = supervision["kills"]
    if (failure and len(kills) != 1) or (not failure and (kills or manifest.get("trigger") is not None)):
        raise ValueError("missing/extra deliberate failure trigger")
    kill = kills[0] if failure else None
    if kill:
        request, issued = kill["requested"], kill["issued"]
        trigger = manifest.get("trigger")
        if (request not in audit or issued not in audit or request["proc_id"] != target
                or issued["proc_id"] != target or request["alive"] is not True or request["complete_seen"] is not False
                or not 25 <= request["verified_pct"] < 100 or not isinstance(trigger, dict)
                or issued["manifest_trigger"] != trigger or trigger["target"] != target
                or not request["mono"] <= trigger["mono"] <= issued["mono"]):
            raise ValueError("failure trigger lacks live/pre-completion identity proof")
    streams, metrics, lifetimes, completions = {}, {}, {}, {}
    launch_order = []
    for process in processes:
        proc, role = process["proc_id"], process["role"]
        entry = supervision["processes"][proc]
        identity = entry["identity"]
        if (role != expected[proc] or process["command"] != entry["argv"] or identity["role"] != role
                or identity["arguments"] != entry["argv"] or identity["owner_run"] != manifest["run_id"]):
            raise ValueError("child role/argv mismatch")
        registrations = [row for row in audit if row["event"] == "child_registered" and row["proc_id"] == proc]
        exits = [row for row in audit if row["event"] == "child_exit_observed" and row["proc_id"] == proc]
        ready = [row for row in audit if row["event"] == "child_ready" and row["proc_id"] == proc]
        if len(registrations) != 1 or len(exits) != 1 or len(ready) != 1:
            raise ValueError("child registration/readiness/exit audit incomplete")
        if (any(registrations[0][key] != entry[key] for key in (
                "identity", "registry_file", "registry_sha256", "argv", "launch_mono", "environment", "executable_sha256"))
                or exits[0]["exit_code"] != entry["exit_code"] or exits[0]["mono"] != entry["observed_exit_mono"]
                or ready[0]["ready_mono"] != process["ready_mono"]):
            raise ValueError("child audit and summary disagree")
        registry_file = checked_path(entry["registry_file"], strict=True)
        if digest_file(registry_file) != entry["registry_sha256"] or strict_json(registry_file.read_bytes()) != identity:
            raise ValueError("child registry mismatch")
        if matching_process(identity) is not None:
            raise ValueError("owned child is still alive")
        if digest_file(Path(identity["executable"])) != entry["executable_sha256"]:
            raise ValueError("child executable changed")
        interpreter = entry.get("interpreter")
        observations = [row for row in audit if row["event"] == "interpreter_observed" and row["proc_id"] == proc]
        if (not isinstance(interpreter, dict) or len(observations) != 1
                or observations[0]["observation"] != interpreter
                or interpreter.get("method") != "independent-live-process-tree-and-environment-v1"):
            raise ValueError("independent interpreter observation is missing or inconsistent")
        actual_identity = interpreter["identity"]
        ancestry = interpreter["ancestry"]
        if not ancestry or ancestry[0] != identity or ancestry[-1] != actual_identity:
            raise ValueError("interpreter is not bound to owned process ancestry")
        for index, ancestor in enumerate(ancestry):
            ancestor_file = registry_file.parent / f"{ancestor['pid']}-{ancestor['creation_time']:.9f}.json"
            if (strict_json(checked_path(ancestor_file, strict=True).read_bytes()) != ancestor
                    or matching_process(ancestor) is not None
                    or index and ancestor["parent_pid"] != ancestry[index - 1]["pid"]):
                raise ValueError("interpreter ancestor unregistered, alive, or unrelated")
        actual_file = checked_path(interpreter["registry_file"], strict=True)
        if (digest_file(actual_file) != interpreter["registry_sha256"]
                or strict_json(actual_file.read_bytes()) != actual_identity
                or digest_file(Path(actual_identity["executable"])) != interpreter["executable_sha256"]
                or actual_identity["arguments"][1:] != entry["argv"][1:]):
            raise ValueError("independently recorded interpreter identity changed")
        actual_environment = interpreter["environment"]
        if (actual_environment.get("BTL_PROC_ID") != proc or actual_environment.get("BTL_RUN_ID") != manifest["run_id"]
                or actual_environment.get("BTL_LOG_STRICT") != "1"
                or checked_path(actual_environment["BTL_EVENT_LOG"]) != run_dir / "events" / f"{proc}.jsonl"):
            raise ValueError("independent interpreter environment does not select strict dedicated logging")
        if process["exit_code"] is None or process["exit_code"] != entry["exit_code"]:
            raise ValueError("actual child exit is missing or differs")
        launch = _number(process["launch_mono"], "child launch")
        if launch != entry["launch_mono"] or entry["observed_exit_mono"] < launch:
            raise ValueError("child lifetime inconsistent")
        launch_order.append(launch)
        environment = entry["environment"]
        if (environment["BTL_PROC_ID"] != proc or environment["BTL_RUN_ID"] != manifest["run_id"]
                or environment.get("BTL_LOG_STRICT") != "1"
                or checked_path(environment["BTL_EVENT_LOG"]) != run_dir / "events" / f"{proc}.jsonl"):
            raise ValueError("dedicated child event environment mismatch")
        killed = failure and proc == target
        if process["killed_by_harness"] is not killed:
            raise ValueError("unexpected or unrecorded killed child")
        if killed and actual_identity != kill["requested"]["identity"]:
            raise ValueError("kill does not match child birth/executable identity")
        if not killed and role != "tracker" and process["exit_code"] != 0:
            raise ValueError("ordinary peer exited unsuccessfully")
        if role == "tracker":
            mechanism = tracker_cleanup[0]["mechanism"]
            # Pinned psutil's Windows termination passes SIGTERM (15) to
            # TerminateProcess. subprocess.Popen.terminate() uses 1 instead;
            # accepting both would hide a different termination path.
            allowed = int(signal.SIGTERM) if mechanism == "psutil-TerminateProcess-SIGTERM" else -signal.SIGTERM if mechanism == "SIGTERM" else None
            if tracker_cleanup[0]["identity"] != actual_identity or process["exit_code"] != allowed:
                raise ValueError("tracker exit differs from declared termination mechanism")
        records, tail = strict_events(run_dir / "events" / f"{proc}.jsonl", expected_proc=proc,
                                      deliberate_kill=killed or role == "tracker",
                                      corroborated_kill=kill if killed else tracker_cleanup[0] if role == "tracker" else None,
                                      require_sequence=True, expected_pid=actual_identity["pid"])
        for row in records:
            validate_event(row, proc)
            if not launch <= row["mono"] <= entry["observed_exit_mono"]:
                raise ValueError("event outside recorded process lifetime")
            if (row["event"] == "resource_sample_error"
                    or row["event"] == "status" and (row["state"] == "ERROR" or row["storage_error"] or row["recovery_error"])
                    or row["event"] == "piece_verification" and row["outcome"] != "stored"):
                raise ValueError("unexpected measured-run runtime/storage/verification failure")
        streams[proc] = records
        if role == "tracker":
            _exact_once(records, "tracker_ready")
            continue
        if killed:
            if any(row["event"] == "complete" for row in records):
                raise ValueError("kill target completed; fault scenario not executed correctly")
            raise PreparationBlocked(f"{proc}: required final metrics/availability after kill lack independent observer")
        else:
            metrics[proc] = derive_peer_metrics(records, proc, oracle)
        start = _exact_once(records, "listening")["mono"]
        lifetimes[proc] = (start, metrics[proc]["lifetime_end"])
        complete = [row for row in records if row["event"] == "complete"]
        if len(complete) > 1 or any(row["final_hash_ok"] is not True for row in complete):
            raise ValueError("duplicate or false complete event")
        if role == "seeder":
            source_check = next(row for row in seeder_checks if row["proc_id"] == proc)
            _verify_initial_seeder(records, metrics[proc], complete, process, source,
                                   run_dir / "peers" / proc / filename, oracle, source_check)
        elif complete:
            completions[proc] = complete[0]["mono"]
        if role == "downloader" and ("--file" in process["command"] or "--seeder" in process["command"]):
            raise ValueError("downloader source independence violated")
        if tail and not killed:
            raise ValueError("unexpected peer event tail")
    if launch_order != sorted(launch_order):
        raise ValueError("actual launch order differs from the fixed schedule")
    expected_complete = {proc for proc, role in expected.items() if role == "downloader" and not (failure and proc == target)}
    if set(completions) != expected_complete:
        raise ValueError("exact expected completion set differs")
    if set(manifest["output_hash_ok"]) != {proc for proc, role in expected.items() if role == "downloader"}:
        raise ValueError("output hash inventory differs")
    for proc in expected_complete:
        if manifest["output_hash_ok"][proc] is not True:
            raise ValueError("launcher reported missing or false output hash")
        compare_files(source, checked_path(run_dir / "peers" / proc / filename, strict=True), oracle)
        if metrics[proc]["verified_download_bytes"] != oracle["size"]:
            raise ValueError("completed peer lacks exactly one useful file worth of verified commits")
    if failure and manifest["output_hash_ok"][target] is not None:
        raise ValueError("killed incomplete target unexpectedly has a completed output")
    if config["scenario"] == "free_rider" and metrics[target]["uploaded_payload_bytes"] != 0:
        raise ValueError("designated free rider uploaded payload bytes")
    verify_network_provenance(streams)
    origin = min(row["launch_mono"] for row in processes if row["role"] != "tracker")
    finish = max(completions.values())
    duration = _number(finish - origin, "distribution duration", positive=True)
    if manifest["run_start_mono"] > origin:
        raise ValueError("tracker/setup origin occurs after first peer launch")
    return {"schema": 1, "lane": lane, "status": "VERIFIED", "run_id": manifest["run_id"],
            "configuration_id": _identity(config), "source_freeze": source_freeze, "revision": revision,
            "metadata_sha256": checked["metadata_sha256"], "source_sha256": oracle["sha256"],
            "expected_complete": sorted(expected_complete), "metrics": metrics,
            "distribution_origin_mono": origin, "distribution_s": duration,
            "launcher_raw_tracker_origin_duration_s": manifest["duration_s"],
            "supervisor_duration_with_cleanup_s": supervision["finished_mono"] - supervision["started_mono"],
            "useful_aggregate_throughput_Bps": len(expected_complete) * oracle["size"] / duration,
            "peer_completion_s": {proc: at - next(p["launch_mono"] for p in processes if p["proc_id"] == proc)
                                  for proc, at in completions.items()},
            "availability": availability_rows(streams, expected, lifetimes, origin=origin, finish=finish,
                                              pieces=len(oracle["pieces"]))}


def verify_result_inventory(plan, results):
    """Exact reconciliation, including every repetition; no empty CSV success."""
    configs = validate_plan(plan)
    wanted = [_identity(config) for config in configs]
    actual = [row.get("configuration_id") for row in results]
    if actual != wanted or len({row.get("run_id") for row in results}) != 27:
        raise ValueError("missing/duplicate/misordered required run results")
    for row in results:
        if (row.get("status") != "VERIFIED" or row.get("source_freeze") != plan["source_freeze"]
                or row.get("revision") != plan["revision"] or row.get("lane") != plan["lane"]):
            raise ValueError("failed/synthetic/mixed-revision required run")
    return True


def execute_schedule(plan, run_one, verify_one, on_verified=None):
    """The single sequential driver. Exceptions propagate before any next run.

    Unit tests may inject callbacks; that provides driver validation only. The
    production supervisor supplies GuardedRun and verify_run, never mock results.
    """
    configs = validate_plan(plan)
    results = []
    for config in configs:
        run_dir = run_one(copy.deepcopy(config))
        result = verify_one(run_dir, config)
        if (result.get("status") != "VERIFIED" or result.get("configuration_id") != _identity(config)
                or result.get("source_freeze") != plan["source_freeze"] or result.get("revision") != plan["revision"]
                or result.get("lane") != plan["lane"] or any(old["run_id"] == result["run_id"] for old in results)):
            raise ValueError("run did not produce unique consistent verified semantics")
        results.append(result)
        if on_verified is not None:
            on_verified(result)
    verify_result_inventory(plan, results)
    return results


def supervise(plan, root, frozen_snapshot):
    """Prepare a new matrix root, fail before launch on any unresolved gate.

    The missing independent killed-peer observer is a real PREPARE gap. There is
    deliberately no 'ignore missing metrics' switch. Once that observer exists,
    it must be implemented/tested/frozen here before the preflight can be changed.
    """
    root = checked_path(root)
    root.mkdir(parents=True, exist_ok=False)
    results = []
    try:
        configs = validate_plan(plan)
        write_json_new(root / "plan.json", plan)
        if frozen_snapshot.get("sha256") != plan["source_freeze"]:
            raise ValueError("plan does not bind this source snapshot")
        compare_snapshots(frozen_snapshot, snapshot(REPO_ROOT))
        oracle = verify_metadata(_asset(configs[0], "fixture"), _asset(configs[0], "metadata"))
        if plan["lane"] == "acceptance" and oracle["size"] != 64 * 1024 * 1024:
            raise PreparationBlocked("primary measured fixture is not 64 MiB")
        challenge_path = _asset(configs[0], "fixture").with_suffix(Path(configs[0]["fixture"]).suffix + ".oracle.json")
        challenge = strict_json(challenge_path.read_bytes())
        if (challenge.get("source_freeze") != plan["source_freeze"] or challenge.get("lane") != plan["lane"]
                or challenge.get("oracle") != file_oracle(_asset(configs[0], "fixture"))
                or not challenge.get("provider") or not challenge.get("token_sha256")):
            raise PreparationBlocked("fresh post-freeze challenge provenance is missing or inconsistent")
        if any(config["scenario"] == "failure" for config in configs):
            raise PreparationBlocked("independent observer for killed-peer final metrics/availability is not implemented; all 27 runs remain NOT RUN")
        # The full matrix above currently blocks. Keep the actual production
        # execution path concrete, ready for a reviewed observer implementation.
        registry_value = os.environ.get("ACCEPTANCE_PROCESS_REGISTRY")
        if not registry_value:
            raise PreparationBlocked("matrix must run inside the recording guardian")
        registry = checked_path(registry_value, strict=True)
        guardian_rows = [strict_json(line) for line in (registry.parent / "guardian.jsonl").read_bytes().splitlines()]
        if not guardian_rows or guardian_rows[0]["action"] != "guardian_ready" or matching_process(guardian_rows[0]["identity"]) is None:
            raise PreparationBlocked("recording guardian is not alive with a recorded identity")
        runs_root = root / "runs"
        runs_root.mkdir()
        def launch(config):
            compare_snapshots(frozen_snapshot, snapshot(REPO_ROOT))
            run = GuardedRun(config, runs_root, source_freeze=plan["source_freeze"],
                             revision=plan["revision"], registry=registry, lane=plan["lane"])
            run.execute()
            compare_snapshots(frozen_snapshot, snapshot(REPO_ROOT))
            return run.dir
        def verify(run_dir, config):
            result = verify_run(run_dir, config, source_freeze=plan["source_freeze"],
                                revision=plan["revision"], lane=plan["lane"])
            write_json_new(run_dir / "semantic-verification.json", result)
            return result
        def retain(result):
            results.append(result)
            write_json_new(root / f"verified-{len(results):02d}.json", result)
        completed = execute_schedule(plan, launch, verify, retain)
        write_json_new(root / "campaign-outcome.json", {"status": "VERIFIED", "results": completed})
        return completed
    except BaseException as exc:
        write_json_new(root / "campaign-outcome.json", {
            "status": "BLOCKED" if isinstance(exc, PreparationBlocked) else "FAILED",
            "reason": f"{type(exc).__name__}: {exc}", "verified_configurations": [r["configuration_id"] for r in results],
            "remaining": [{"configuration_id": _identity(c), "status": "NOT RUN OR NOT VERIFIED"}
                          for c in plan.get("configs", []) if _identity(c) not in {r["configuration_id"] for r in results}],
            "acceptance_credit": False,
            "restart_rule": "Preserve this attempt; any unexpected campaign failure requires repair, fresh freeze and restart from Phase00."})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("plan")
    create.add_argument("base")
    create.add_argument("--set", action="append", default=[])
    create.add_argument("--order-seed", type=int, default=2026)
    create.add_argument("--source-freeze", required=True)
    create.add_argument("--revision", required=True)
    create.add_argument("--lane", choices=("acceptance", "diagnostic"), required=True)
    create.add_argument("--out", type=Path, required=True)
    run = commands.add_parser("execute")
    run.add_argument("--plan", type=Path, required=True)
    run.add_argument("--snapshot", type=Path, required=True)
    run.add_argument("--root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            plan = make_plan(args.base, args.set, order_seed=args.order_seed, source_freeze=args.source_freeze,
                             revision=args.revision, lane=args.lane)
            write_json_new(args.out, plan)
        else:
            supervise(strict_json(args.plan.read_bytes()), args.root, strict_json(args.snapshot.read_bytes()))
        return 0
    except PreparationBlocked as exc:
        print(f"BLOCKED: {exc}")
        return 3
    except (ValueError, OSError) as exc:
        print(f"FAILED: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
