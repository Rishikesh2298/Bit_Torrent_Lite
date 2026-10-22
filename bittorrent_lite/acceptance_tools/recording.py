"""Fresh, shell-free preparation/acceptance command records and owned cleanup.

This is acceptance tooling, not the application launcher. ``RecordingSession``
must outlive the pytest/application command it records. The independent watcher
also retains identities of descendants while that command runs. Programs that
create descendants must call ``register_process`` at creation; polling alone
cannot prove that a very short-lived descendant did not escape observation.
That limitation is explicit in every record and is a preparation gate.

Requires psutil, whose version/wheel must be pinned before acceptance. No test
result or JUnit document is synthesized here. All raw streams are binary files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone

import psutil


SCHEMA = "btl-command-v1"
ENV_KEYS = ("PATH", "PYTHONPATH", "PYTHONHOME", "PYTHONUNBUFFERED", "PYTEST_ADDOPTS",
            "PYTEST_PLUGINS", "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "COVERAGE_PROCESS_START",
            "COVERAGE_FILE", "TEMP", "TMP", "MPLCONFIGDIR", "BTL_EVENT_LOG",
            "BTL_PROC_ID", "BTL_RUN_ID", "ACCEPTANCE_PROCESS_REGISTRY",
            "BTL_LOG_STRICT", "BTL_COVERAGE_ROOT", "PYTHONIOENCODING", "PYTHONUTF8")


def _times():
    now = datetime.now(timezone.utc)
    local = now.astimezone()
    return {"utc": now.isoformat(),
            "local": local.isoformat(),
            "local_timezone": str(local.tzinfo), "monotonic": time.monotonic()}


def _hash_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_new(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _append(path, value):
    # Each writer has its own file; consumers parse only newline-complete records.
    data = (json.dumps(value, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    with Path(path).open("ab", buffering=0) as handle:
        handle.write(data)
        os.fsync(handle.fileno())


def _safe_name(value):
    if (not isinstance(value, str) or not value or value in (".", "..")
            or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
                   for c in value)):
        raise ValueError("identifier must be a nonempty safe filename component")
    return value


def _no_redirect(path):
    """Refuse existing symlinks/junctions, including at an ancestor."""
    path = Path(path).absolute()
    for part in (path, *path.parents):
        try:
            reparse = getattr(part.lstat(), "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        except FileNotFoundError:
            reparse = False
        if reparse or part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ValueError(f"redirected evidence path: {part}")
    return path.resolve()


def process_identity(pid):
    process = psutil.Process(pid)
    return {"pid": process.pid, "creation_time": process.create_time(),
            "executable": process.exe(), "arguments": process.cmdline(),
            "parent_pid": process.ppid()}


def matching_process(identity):
    """No signal may be sent until PID, birth time and executable match."""
    try:
        process = psutil.Process(identity["pid"])
        if process.create_time() != identity["creation_time"]:
            return None
        if os.path.normcase(process.exe()) != os.path.normcase(identity["executable"]):
            return None
        if process.status() == psutil.STATUS_ZOMBIE:
            return None
        return process
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return None


def register_process(registry, pid, *, owner_run, role, stop_file=None, expected_identity=None):
    """Register immediately after Popen, before a child is used by its caller.

    Separate files avoid append races when independently supervised launchers
    register concurrently. The returned immutable identity is cleanup authority.
    """
    registry = _no_redirect(registry)
    registry.mkdir(parents=True, exist_ok=True)
    identity = process_identity(pid)
    if expected_identity is not None:
        if not isinstance(expected_identity, dict):
            raise ValueError('expected process identity must be a complete observation')
        for key in ('pid', 'creation_time', 'executable', 'arguments', 'parent_pid'):
            if key not in expected_identity or identity.get(key) != expected_identity[key]:
                raise ValueError(f'process identity changed before registration: {key}')
    identity.update(owner_run=owner_run, role=role,
                    stop_file=str(Path(stop_file).resolve()) if stop_file else None,
                    registered_at=_times(), registration="explicit")
    name = f"{identity['pid']}-{identity['creation_time']:.9f}.json"
    # Publish a complete file with a no-replacement operation. A watcher must
    # never see half of a JSON record while another process registers a child.
    pending = registry / f".pending-{uuid.uuid4().hex}"
    try:
        _write_new(pending, identity)
        os.link(pending, registry / name)
    finally:
        if pending.exists():
            pending.unlink()
    return identity


def _registered(registry):
    records = []
    for path in sorted(Path(registry).glob("*.json")):
        records.append(json.loads(path.read_text(encoding="utf-8")))
    return records


def stop_owned(identities, log_path, *, grace_s=3.0, terminate_s=2.0):
    """Bounded cleanup only of verified identities; preserve every intervention."""
    errors = []
    unique = {(i["pid"], i["creation_time"]): i for i in identities}
    alive = []
    for identity in unique.values():
        try:
            process = matching_process(identity)
            if process is None:
                _append(log_path, {"action": "already_exited_or_identity_changed", "identity": identity,
                                   "at": _times()})
                continue
            stop = identity.get("stop_file")
            if stop:
                Path(stop).touch(exist_ok=False)
                _append(log_path, {"action": "stop_file", "identity": identity, "at": _times()})
            elif os.name != "nt":
                process.send_signal(signal.SIGTERM)
                _append(log_path, {"action": "SIGTERM", "identity": identity, "at": _times()})
            else:
                # CTRL_BREAK is unsafe unless a known console process group was
                # established. Waiting first gives registered parents a chance
                # to propagate their own cooperative shutdown to descendants.
                _append(log_path, {"action": "cooperative_wait_no_stop_channel", "identity": identity,
                                   "at": _times()})
            alive.append(identity)
        except (OSError, psutil.Error) as exc:
            errors.append(f"cooperative stop {identity['pid']}: {exc}")
            alive.append(identity)
    deadline = time.monotonic() + grace_s
    while alive and time.monotonic() < deadline:
        alive = [i for i in alive if matching_process(i) is not None]
        if alive:
            time.sleep(min(.05, max(0, deadline - time.monotonic())))
    for action in ("terminate", "kill"):
        for identity in alive:
            try:
                process = matching_process(identity)
                if process is not None:
                    getattr(process, action)()
                    _append(log_path, {"action": action, "forced": True, "identity": identity,
                                       "at": _times()})
            except (OSError, psutil.Error) as exc:
                errors.append(f"{action} {identity['pid']}: {exc}")
        deadline = time.monotonic() + terminate_s
        while alive and time.monotonic() < deadline:
            alive = [i for i in alive if matching_process(i) is not None]
            if alive:
                time.sleep(min(.05, max(0, deadline - time.monotonic())))
    for identity in alive:
        errors.append(f"owned process still alive: {identity['pid']}")
    _append(log_path, {"action": "cleanup_complete", "at": _times(), "survivors": alive,
                       "errors": errors})
    return errors


def observed_child_identity(child):
    """Preserve the identity captured by children(), rather than adopt reused PID.

psutil's Process object retains its birth identity. A fresh lookup is useful
for the executable/arguments, but it must describe that same observed child.
"""
    creation_time = child.create_time()
    if not child.is_running():
        return None
    identity = process_identity(child.pid)
    if identity['creation_time'] != creation_time:
        return None
    return identity


def _watch(case_dir, supervisor):
    """Sidecar survives a recording-supervisor/pytest crash and preserves evidence."""
    case_dir = Path(case_dir)
    registry = case_dir / "processes"
    observed = {}
    log = case_dir / "guardian.jsonl"
    _append(log, {"action": "guardian_ready", "identity": process_identity(os.getpid()), "at": _times()})
    while True:
        try:
            registered = _registered(registry)
            for identity in registered:
                observed[(identity["pid"], identity["creation_time"])] = identity
                process = matching_process(identity)
                if process is not None:
                    try:
                        descendants = process.children(recursive=True)
                    except (psutil.NoSuchProcess, psutil.ZombieProcess):
                        # Natural exit may occur after the identity check. Keep
                        # the registered identity, but there is no live parent
                        # left to enumerate. Access/other errors still fail.
                        _append(log, {"action": "exited_during_descendant_scan",
                                      "identity": identity, "at": _times()})
                        descendants = []
                    for child in descendants:
                        try:
                            child_id = observed_child_identity(child)
                        except (psutil.NoSuchProcess, psutil.ZombieProcess):
                            continue
                        if child_id is None:
                            _append(log, {"action": "descendant_identity_changed_or_exited",
                                          "pid": child.pid, "at": _times()})
                            continue
                        key = (child_id["pid"], child_id["creation_time"])
                        if key not in observed:
                            child_id.update(owner_run=identity["owner_run"], role="observed-descendant",
                                            stop_file=None, registration="observed")
                            observed[key] = child_id
                            _append(log, {"action": "observed_descendant", "identity": child_id, "at": _times()})
            supervisor_alive = matching_process(supervisor) is not None
            if not supervisor_alive or (case_dir / "guardian.stop").exists():
                _append(log, {"action": "supervisor_exit" if not supervisor_alive else "requested_cleanup",
                               "at": _times()})
                alive_before_cleanup = [i for i in observed.values() if matching_process(i) is not None]
                errors = stop_owned(observed.values(), log)
                _write_new(case_dir / "guardian-result.json", {
                    "supervisor_died": not supervisor_alive, "identities": list(observed.values()),
                    "alive_before_cleanup": alive_before_cleanup, "errors": errors, "at": _times(),
                    "limitation": "Unregistered descendants may evade polling; explicit child registration required."})
                return 1 if errors else 0
        except (OSError, ValueError, psutil.Error):
            fault = traceback.format_exc()
            _append(log, {"action": "guardian_error", "traceback": fault, "at": _times()})
            errors = stop_owned(observed.values(), log)
            _write_new(case_dir / "guardian-result.json", {
                "supervisor_died": None, "identities": list(observed.values()),
                "alive_before_cleanup": [], "errors": [fault, *errors], "at": _times(),
                "limitation": "Guardian observation failed; this command cannot pass."})
            return 2
        time.sleep(.025)


class RecordingFailure(RuntimeError):
    def __init__(self, message, record):
        super().__init__(message)
        self.record = record


class RecordingSession:
    def __init__(self, root, campaign_id, attempt_id, snapshot_hashes):
        self.root = _no_redirect(root)
        self.root.mkdir(parents=True, exist_ok=False)
        self.campaign_id = _safe_name(campaign_id)
        self.attempt_id = _safe_name(attempt_id)
        self.snapshot_hashes = dict(snapshot_hashes)
        _write_new(self.root / "session.json", {"schema": SCHEMA, "campaign_id": campaign_id,
                   "attempt_id": attempt_id, "snapshot_hashes": snapshot_hashes, "created_at": _times()})

    def run(self, case_id, argv, *, cwd, env=None, stdin_bytes=None, timeout_s,
            expected_exit_codes=(0,), oracle, stop_file=None):
        case_id = _safe_name(case_id)
        if not isinstance(argv, (tuple, list)) or not argv or any(not isinstance(a, str) for a in argv):
            raise ValueError("argv must be a nonempty list/tuple of strings")
        executable = Path(argv[0])
        if not executable.is_absolute() or not executable.is_file():
            raise ValueError("record an absolute existing executable, not a PATH alias")
        if not math.isfinite(timeout_s) or timeout_s <= 0 or not oracle or not expected_exit_codes:
            raise ValueError("positive timeout, oracle and explicit accepted exits are required")
        if stdin_bytes is not None and not isinstance(stdin_bytes, bytes):
            raise TypeError("stdin_bytes must contain the exact bytes to supply")
        cwd = Path(cwd).resolve(strict=True)
        case_dir = _no_redirect(self.root / case_id)
        case_dir.mkdir(exist_ok=False)
        registry = case_dir / "processes"
        registry.mkdir()
        environment = dict(os.environ) if env is None else dict(env)
        environment["ACCEPTANCE_PROCESS_REGISTRY"] = str(registry)
        record = {"schema": SCHEMA, "campaign_id": self.campaign_id, "attempt_id": self.attempt_id,
                  "case_id": case_id, "argv": list(argv), "cwd": str(cwd), "shell": False,
                  "environment": {k: environment.get(k) for k in ENV_KEYS},
                  "snapshot_hashes": self.snapshot_hashes, "oracle": oracle,
                  "expected_exit_codes": list(expected_exit_codes), "timeout_s": timeout_s,
                  "semantic_oracle_status": "NOT RUN",  # caller/verifier must evaluate it independently
                  "started_at": _times(), "process": None, "exit_code": None, "timed_out": False,
                  "exception": None, "cleanup_errors": [], "status": "RUNNING",
                  "executable_sha256": _hash_file(executable)}
        if stop_file is not None:
            stop_file = _no_redirect(stop_file)
            if not stop_file.is_relative_to(self.root):
                raise ValueError("stop_file must be under the recording session root")
            if stop_file.exists():
                raise ValueError("stop_file must be absent")
        if stdin_bytes is not None:
            with (case_dir / "stdin.bin").open("xb") as handle:
                handle.write(stdin_bytes)
            record["stdin_sha256"] = _hash_file(case_dir / "stdin.bin")
        else:
            record["stdin_sha256"] = None
        _write_new(case_dir / "started.json", record)
        process = guardian = None
        guardian_streams = []
        try:
            supervisor = process_identity(os.getpid())
            _write_new(case_dir / "supervisor.json", supervisor)
            for name in ("guardian.stdout", "guardian.stderr"):
                guardian_streams.append((case_dir / name).open("xb"))
            guardian = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "--guardian", str(case_dir)],
                cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
                stdout=guardian_streams[0], stderr=guardian_streams[1],
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            record["guardian"] = process_identity(guardian.pid)
            ready_deadline = time.monotonic() + 5
            while not (case_dir / "guardian.jsonl").exists():
                if guardian.poll() is not None or time.monotonic() > ready_deadline:
                    raise RuntimeError("process guardian failed to start")
                time.sleep(.01)
            with (case_dir / "stdout.bin").open("xb") as stdout, (case_dir / "stderr.bin").open("xb") as stderr:
                process = subprocess.Popen(list(argv), cwd=cwd, env=environment,
                                           stdin=subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
                                           stdout=stdout, stderr=stderr,
                                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                record["process"] = register_process(registry, process.pid,
                    owner_run=f"{self.attempt_id}/{case_id}", role="command", stop_file=stop_file)
                _write_new(case_dir / "launched.json", {"process": record["process"], "at": _times()})
                try:
                    process.communicate(input=stdin_bytes, timeout=timeout_s)
                except subprocess.TimeoutExpired:
                    record["timed_out"] = True
                    (case_dir / "guardian.stop").touch(exist_ok=False)
                    guardian.wait(timeout=15)
                    process.wait(timeout=2)
                record["exit_code"] = process.returncode
        except BaseException:
            record["exception"] = traceback.format_exc()
        finally:
            # Never allow an unexpected recorder exception to strand a known child.
            if guardian is not None and guardian.poll() is None:
                (case_dir / "guardian.stop").touch(exist_ok=True)
                try:
                    guardian.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    record["cleanup_errors"].append("guardian cleanup deadline exceeded")
                    record["cleanup_errors"].extend(stop_owned(_registered(registry), case_dir / "fallback-cleanup.jsonl"))
                    guardian.terminate()
                    guardian.wait(timeout=3)
            for handle in guardian_streams:
                handle.close()
            if process is not None:
                try:
                    process.wait(timeout=2)
                    record["exit_code"] = process.returncode
                except subprocess.TimeoutExpired:
                    record["cleanup_errors"].append("command still alive after guardian cleanup; emergency owned-handle cleanup")
                    try:
                        direct_identity = record["process"] or process_identity(process.pid)
                        record["cleanup_errors"].extend(stop_owned([direct_identity], case_dir / "emergency-cleanup.jsonl"))
                        process.wait(timeout=3)
                        record["exit_code"] = process.returncode
                    except (OSError, psutil.Error, subprocess.TimeoutExpired) as exc:
                        record["cleanup_errors"].append(f"emergency cleanup failed: {exc}")
            guardian_result = case_dir / "guardian-result.json"
            if guardian_result.exists():
                details = json.loads(guardian_result.read_text(encoding="utf-8"))
                record["cleanup_errors"].extend(details["errors"])
                # Surviving descendants after normal parent completion are a fault,
                # even if our guardian subsequently cleaned them successfully.
                if process is not None and not record["timed_out"]:
                    lingering = [i for i in details["alive_before_cleanup"]
                                 if i["pid"] != process.pid]
                    if lingering:
                        record["cleanup_errors"].append("command left live descendants after exit")
                    events = [json.loads(line) for line in (case_dir / "guardian.jsonl").read_text().splitlines()]
                    forced = [e for e in events if e.get("forced")]
                    if forced:
                        record["cleanup_errors"].append("normal command required forced descendant cleanup")
            elif guardian is not None:
                record["cleanup_errors"].append("missing guardian result")
            record["finished_at"] = _times()
            record["elapsed_s"] = record["finished_at"]["monotonic"] - record["started_at"]["monotonic"]
            record["artifacts"] = [{"path": p.relative_to(case_dir).as_posix(),
                                    "size": p.stat().st_size, "sha256": _hash_file(p)}
                                   for p in sorted(case_dir.rglob("*")) if p.is_file()]
            record["status"] = ("PASS" if record["exception"] is None and not record["timed_out"]
                                and record["exit_code"] in expected_exit_codes and not record["cleanup_errors"]
                                else "FAIL")
            _write_new(case_dir / "record.json", record)
        if record["status"] != "PASS":
            raise RecordingFailure(f"recorded command failed: {case_id}; inspect {case_dir}", record)
        return record


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--guardian", type=Path, required=True)
    args = parser.parse_args(argv)
    supervisor = json.loads((args.guardian / "supervisor.json").read_text(encoding="utf-8"))
    return _watch(args.guardian, supervisor)


if __name__ == "__main__":
    raise SystemExit(main())
