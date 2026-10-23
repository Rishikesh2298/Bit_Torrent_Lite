"""
Child processes the GUI starts, and what it learns from their output.

Every process is one of the project's existing command-line programs, run
with the same Python interpreter as the GUI. Peers print one JSON object per
line on stdout (see application/cli.py and application/runtime.py); a reader
thread turns those lines into a PeerProcess model the browser polls. The
tracker's human-readable log lines are parsed for announces so the host can
see peers from every machine.
"""

import collections
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import bittorrent_lite

PACKAGE_PARENT = str(Path(bittorrent_lite.__file__).resolve().parent.parent)
NO_WINDOW = 0x08000000 if os.name == "nt" else 0      # CREATE_NO_WINDOW
NEW_GROUP = 0x00000200 if os.name == "nt" else 0      # CREATE_NEW_PROCESS_GROUP


def child_env(extra: dict | None = None) -> dict:
    """Environment that finds this checkout of bittorrent_lite even when it is not installed."""
    env = dict(os.environ)
    env["PYTHONPATH"] = PACKAGE_PARENT + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("BTL_EVENT_LOG", None)
    env.update(extra or {})
    return env


def module_command(module: str, *args) -> list[str]:
    return [sys.executable, "-m", module, *[str(a) for a in args]]


def kill_tree(proc: subprocess.Popen) -> None:
    """Kill a process and everything it started (experiment runs start peers)."""
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           capture_output=True, creationflags=NO_WINDOW, timeout=10)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        proc.kill()


class ManagedProcess:
    """A child process with its output captured line by line."""

    def __init__(self, command: list[str], cwd: Path, log_path: Path, *, env=None,
                 own_group: bool = False):
        self.command = command
        self.cwd = cwd
        self.log_path = log_path
        self.lock = threading.RLock()
        self.lines = collections.deque(maxlen=400)
        self.exit_code = None
        self.started_at = time.time()
        self.ended_at = None
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log = open(log_path, "a", encoding="utf-8", buffering=1)
        self._log.write(f"\n# {time.strftime('%Y-%m-%d %H:%M:%S')} {subprocess.list2cmdline(command)}\n")
        kwargs = {}
        if own_group:
            if os.name == "nt":
                kwargs["creationflags"] = NO_WINDOW | NEW_GROUP
            else:
                kwargs["start_new_session"] = True
        elif NO_WINDOW:
            kwargs["creationflags"] = NO_WINDOW
        self.proc = subprocess.Popen(
            command, cwd=str(cwd), env=env or child_env(), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", bufsize=1, **kwargs)
        self._readers = [threading.Thread(target=self._read, args=(self.proc.stdout, "out"), daemon=True),
                         threading.Thread(target=self._read, args=(self.proc.stderr, "err"), daemon=True)]
        for reader in self._readers:
            reader.start()
        threading.Thread(target=self._wait, daemon=True).start()

    @property
    def running(self) -> bool:
        return self.exit_code is None

    def _read(self, stream, name):
        for line in stream:
            line = line.rstrip("\r\n")
            try:
                self._log.write(line + "\n")
            except ValueError:
                pass
            with self.lock:
                self.handle_line(line, name)

    def _wait(self):
        code = self.proc.wait()
        for reader in self._readers:
            reader.join(timeout=5)
        with self.lock:
            self.exit_code = code
            self.ended_at = time.time()
            self.on_exit(code)
        try:
            self._log.close()
        except OSError:
            pass

    def handle_line(self, line: str, stream: str):
        self.lines.append({"t": time.time(), "stream": stream, "text": line})

    def on_exit(self, code: int):
        pass

    def terminate(self):
        if self.proc.poll() is None:
            self.proc.terminate()

    def kill(self):
        kill_tree(self.proc)


# Events too frequent or too internal for the live event list.
QUIET_EVENTS = {"SCHEDULER_SNAPSHOT", "STATUS", "PIECE_VERIFICATION", "RESOURCE_SAMPLE",
                "RESOURCE_SAMPLE_UNAVAILABLE", "RESOURCE_SAMPLE_ERROR"}


def describe(record: dict) -> str:
    event = record.get("event")
    if event == "START":
        return f"listening, {record.get('strategy')} window {record.get('window')}" + (
            ", free rider" if record.get("free_rider") else "")
    if event == "PIECE_VERIFIED":
        return f"piece {record.get('piece')} from {record.get('remote')}"
    if event == "PROGRESS":
        return f"{record.get('pieces')}/{record.get('total')} pieces"
    if event == "COMPLETE":
        seconds = record.get("completion_seconds")
        return f"file complete in {seconds:.1f} s" if isinstance(seconds, (int, float)) else "file complete"
    if event == "CONNECTED":
        return f"connected to {record.get('remote')}"
    if event == "CONNECT_FAILED":
        return f"could not reach {record.get('remote')}: {record.get('message')}"
    if event == "TRACKER_ERROR":
        return str(record.get("message"))
    if event == "REQUEST_EXPIRED":
        return f"request for piece {record.get('piece', '?')} timed out"
    if event == "STOPPED":
        errors = record.get("errors") or []
        return "stopped" + (f" with {len(errors)} error(s)" if errors else " cleanly")
    fields = {k: v for k, v in record.items() if k not in ("event", "peer_id", "at")}
    return json.dumps(fields)[:160]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def peer_arguments(spec: dict, torrent: dict, stop_file: Path, tracker_url: str) -> list[str]:
    """The peer CLI arguments for one GUI peer. Peers listen on every interface (never Errno 49)."""
    args = ["--peer-id", spec["peer_id"], "--port", spec["port"], "--host", "0.0.0.0",
            "--tracker", tracker_url, "--metadata", torrent["path"],
            "--output-dir", spec["output_dir"], "--strategy", spec["strategy"],
            "--window", spec["window"], "--stop-file", stop_file]
    if spec["role"] == "seeder":
        args += ["--seeder", "--file", spec["source"]]
    if spec.get("seed"):
        args += ["--seed", spec["seed"]]
    if spec.get("upload_workers"):
        args += ["--upload-workers", spec["upload_workers"]]
    if spec.get("free_rider"):
        args += ["--free-rider"]
    return [str(a) for a in args]


class PeerProcess(ManagedProcess):
    """One running `python -m bittorrent_lite` peer and its live state."""

    def __init__(self, spec: dict, torrent: dict, workdir: Path, tracker_url: str):
        self.spec = dict(spec)
        self.torrent = torrent
        self.peer_id = spec["peer_id"]
        self.total = torrent["num_pieces"]
        self.output_root = Path(spec["output_dir"])
        self.output_file = self.output_root / self.peer_id / torrent["filename"]
        self.stop_file = workdir / ".gui" / "stop" / self.peer_id
        self.stop_file.parent.mkdir(parents=True, exist_ok=True)
        if self.stop_file.exists():
            self.stop_file.unlink()
        self.state = "STARTING"
        self.verified = self._pieces_on_disk()
        self.owned = len(self.verified)
        self.requested = set()
        self.connected = 0
        self.neighbors = []
        self.pending_requests = 0
        self.down_bytes = 0
        self.up_bytes = 0
        self.down_rate = 0.0
        self.up_rate = 0.0
        self._rate_samples = collections.deque(maxlen=6)
        self.completion_seconds = None
        self.hash_check = None          # None | checking | ok | mismatch | error
        self.hash_detail = ""
        self.events = collections.deque(maxlen=200)
        self.errors = collections.deque(maxlen=20)
        self.stop_requested_at = None
        self.tracker_url = tracker_url
        command = module_command("bittorrent_lite", *peer_arguments(self.spec, torrent, self.stop_file, tracker_url))
        super().__init__(command, workdir, workdir / ".gui" / "logs" / f"{self.peer_id}.log")
        self._event("GUI", "process started")

    def _pieces_on_disk(self) -> set:
        """Pieces kept from an earlier run of this peer (restart resumes from them)."""
        folder = self.output_root / self.peer_id / "pieces" / self.torrent["file_id"]
        found = set()
        if folder.is_dir():
            for entry in folder.glob("*.piece"):
                if entry.stem.isdigit() and int(entry.stem) < self.total:
                    found.add(int(entry.stem))
        return found

    def _event(self, name, text):
        self.events.append({"t": time.time(), "e": name, "d": text})

    def handle_line(self, line, stream):
        if stream == "err" or not line.startswith("{"):
            super().handle_line(line, stream)
            if line.strip():
                self.errors.append(line.strip())
                self._event("STDERR" if stream == "err" else "OUTPUT", line.strip()[:200])
            return
        try:
            record = json.loads(line)
        except ValueError:
            super().handle_line(line, stream)
            return
        event = record.get("event")
        if event == "STATUS":
            self._status(record)
        elif event == "SCHEDULER_SNAPSHOT":
            self.requested = {p["piece_index"] for p in record.get("pending", ())
                              if isinstance(p, dict) and "piece_index" in p}
            self.neighbors = sorted(n.get("peer_id", "?") for n in record.get("neighbors", {}).values()
                                    if n.get("active"))
        elif event == "PIECE_VERIFIED":
            piece = record.get("piece")
            if isinstance(piece, int):
                self.verified.add(piece)
                self.requested.discard(piece)
        elif event == "START":
            self.state = "STALLED" if self.spec["role"] != "seeder" else "SEEDING"
        elif event == "COMPLETE":
            self.completion_seconds = record.get("completion_seconds")
            self.owned = self.total
            self.verified = set(range(self.total))
            self.requested.clear()
            if self.spec["role"] != "seeder":
                self._start_hash_check()
        elif event == "STOPPED":
            self._status(record)
            self.state = "STOPPED"
        if event not in QUIET_EVENTS:
            self._event(event, describe(record))

    def _status(self, record):
        self.state = record.get("state", self.state)
        self.owned = record.get("owned", self.owned)
        if self.owned >= self.total:
            self.verified = set(range(self.total))
        self.connected = record.get("connected_peers", self.connected)
        self.pending_requests = record.get("pending_requests", self.pending_requests)
        self.down_bytes = record.get("verified_download_bytes", self.down_bytes)
        self.up_bytes = record.get("uploaded_payload_bytes", self.up_bytes)
        if record.get("completion_seconds") is not None:
            self.completion_seconds = record["completion_seconds"]
        at = record.get("at")
        if isinstance(at, (int, float)):
            self._rate_samples.append((at, self.down_bytes, self.up_bytes))
            if len(self._rate_samples) >= 2:
                t0, d0, u0 = self._rate_samples[0]
                span = at - t0
                if span > 0:
                    self.down_rate = max(0.0, (self.down_bytes - d0) / span)
                    self.up_rate = max(0.0, (self.up_bytes - u0) / span)
        for key in ("storage_error", "recovery_error"):
            if record.get(key):
                self.errors.append(f"{key}: {record[key]}")

    def _start_hash_check(self):
        """Hash the finished file independently and compare with the torrent's file_sha256."""
        if self.hash_check in ("checking", "ok"):
            return
        self.hash_check = "checking"
        expected = self.torrent.get("file_sha256")

        def check():
            for _ in range(20):         # the file is assembled right after COMPLETE
                if self.output_file.is_file() and self.output_file.stat().st_size == self.torrent["file_size"]:
                    break
                time.sleep(0.25)
            try:
                actual = sha256_file(self.output_file)
            except OSError as exc:
                result, detail = "error", str(exc)
            else:
                if expected and actual == expected:
                    result, detail = "ok", actual
                else:
                    result, detail = "mismatch", f"got {actual}, torrent says {expected}"
            with self.lock:
                self.hash_check, self.hash_detail = result, detail
                self._event("GUI", {"ok": "SHA-256 of the whole file matches the torrent",
                                    "mismatch": "SHA-256 does NOT match the torrent",
                                    "error": f"could not hash file: {detail}"}[result])

        threading.Thread(target=check, daemon=True).start()

    def on_exit(self, code):
        if self.state != "STOPPED" or code:
            self.state = "STOPPED" if code == 0 else "EXITED"
        self.connected = 0
        self.requested.clear()
        self.down_rate = self.up_rate = 0.0
        self._event("GUI", f"process exited with code {code}")

    def request_stop(self):
        """Graceful stop through --stop-file; the peer tells the tracker it left."""
        if self.running and self.stop_requested_at is None:
            self.stop_requested_at = time.time()
            self.stop_file.touch()
            self._event("GUI", "stop requested")

            def escalate():
                deadline = time.time() + float(self.spec.get("shutdown_timeout", 5)) + 10
                while self.running and time.time() < deadline:
                    time.sleep(0.2)
                if self.running:
                    self.terminate()
                    time.sleep(3)
                    if self.running:
                        self.kill()

            threading.Thread(target=escalate, daemon=True).start()

    def piece_map(self) -> str:
        """One character per piece: v verified, r requested, . missing."""
        chars = []
        for index in range(self.total):
            chars.append("v" if index in self.verified else "r" if index in self.requested else ".")
        return "".join(chars)

    def display_state(self) -> str:
        if self.exit_code is not None:
            return "STOPPED" if self.exit_code == 0 else "EXITED"
        if self.stop_requested_at is not None:
            return "STOPPING"
        if self.state == "SEEDING" and self.spec["role"] != "seeder":
            return "DONE"
        return self.state

    def snapshot(self, detail: bool = False) -> dict:
        with self.lock:
            data = {
                "peer_id": self.peer_id, "file_id": self.torrent["file_id"], "role": self.spec["role"],
                "port": self.spec["port"], "strategy": self.spec["strategy"], "window": self.spec["window"],
                "free_rider": bool(self.spec.get("free_rider")), "state": self.display_state(),
                "owned": max(self.owned, len(self.verified)) if self.state != "STARTING" else len(self.verified),
                "total": self.total, "connected": self.connected, "neighbors": self.neighbors,
                "pending": self.pending_requests, "down_bytes": self.down_bytes, "up_bytes": self.up_bytes,
                "down_rate": self.down_rate, "up_rate": self.up_rate,
                "completion_seconds": self.completion_seconds, "hash_check": self.hash_check,
                "hash_detail": self.hash_detail, "running": self.running, "exit_code": self.exit_code,
                "started_at": self.started_at, "ended_at": self.ended_at,
                "output_file": str(self.output_file), "folder": str(self.output_root / self.peer_id),
                "last_error": self.errors[-1] if self.errors else None,
            }
            if detail:
                data["pieces"] = self.piece_map()
                data["events"] = list(self.events)[-80:]
                data["command"] = subprocess.list2cmdline(self.command)
                data["log_path"] = str(self.log_path)
            return data


ANNOUNCE_RE = re.compile(r"\b(started|update|completed|stopped) ([A-Za-z0-9_-]{1,32}) "
                         r"([0-9a-fA-F.:\[\]]+):(\d+) file=([0-9a-f]{8})")


class TrackerProcess(ManagedProcess):
    """The project's HTTP tracker, started by this GUI on 0.0.0.0."""

    def __init__(self, port: int, workdir: Path, host: str = "0.0.0.0"):
        self.port = port
        self.host = host
        self.ready = False
        self.announces = collections.deque(maxlen=200)
        self.members = {}           # file_id prefix -> {peer_id: {...}}
        command = module_command("bittorrent_lite.discovery.tracker_server", "--host", host, "--port", port)
        super().__init__(command, workdir, workdir / ".gui" / "logs" / "tracker.log")

    def handle_line(self, line, stream):
        super().handle_line(line, stream)
        if "Tracker listening" in line:
            self.ready = True
        match = ANNOUNCE_RE.search(line)
        if match:
            event, peer, ip, port, prefix = match.groups()
            row = {"t": time.time(), "event": event, "peer_id": peer, "ip": ip,
                   "port": int(port), "file": prefix}
            self.announces.append(row)
            swarm = self.members.setdefault(prefix, {})
            if event == "stopped":
                swarm.pop(peer, None)
            else:
                swarm[peer] = row

    def snapshot(self) -> dict:
        with self.lock:
            now = time.time()
            members = {prefix: [m for m in swarm.values() if now - m["t"] < 25]
                       for prefix, swarm in self.members.items()}
            return {"running": self.running, "ready": self.ready, "port": self.port,
                    "exit_code": self.exit_code, "announces": list(self.announces)[-40:],
                    "members": members, "log_tail": [l["text"] for l in list(self.lines)[-8:]]}


class JobProcess(ManagedProcess):
    """A one-off command such as the experiment matrix; keeps its text output."""

    def __init__(self, name: str, command: list[str], workdir: Path, on_line=None, on_done=None):
        self.name = name
        self._on_line = on_line
        self._on_done = on_done
        super().__init__(command, workdir, workdir / ".gui" / "logs" / f"{name}.log", own_group=True)

    def handle_line(self, line, stream):
        super().handle_line(line, stream)
        if self._on_line:
            self._on_line(line, stream)

    def on_exit(self, code):
        if self._on_done:
            self._on_done(code)
