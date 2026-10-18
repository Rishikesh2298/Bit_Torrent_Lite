"""
Structured run events for experiments.

Every process in an experiment run (tracker and peers) appends one JSON
object per line to the file named by the BTL_EVENT_LOG environment
variable. The experiment launcher sets that variable for each child it
starts and the collector reads the files afterwards.

When BTL_EVENT_LOG is not set (unit tests, manual runs) emit() does nothing,
so modules can call it unconditionally.

Line format:
    {"mono": 12345.678, "proc": "peer-01", "event": "piece_verified", "piece": 3, "bytes": 65536}

"mono" is time.monotonic(). On one host the monotonic clock is shared by all
processes, so the collector can subtract values from different peers.
Never compare "mono" values recorded on different machines.

Event names and their fields are listed in docs/log-events.md.
"""

import json
import os
import threading
import time

ENV_VAR = "BTL_EVENT_LOG"
PROC_ENV_VAR = "BTL_PROC_ID"

_lock = threading.Lock()
_file = None
_path = None


def _open():
    global _file, _path
    path = os.environ.get(ENV_VAR)
    if not path:
        return None
    if _file is None or _path != path:
        _file = open(path, "a", encoding="utf-8", buffering=1)
        _path = path
    return _file


def emit(event: str, proc: str | None = None, **fields) -> None:
    """Append one event record. Never raises on I/O failure."""
    record = {
        "mono": time.monotonic(),
        "proc": proc or os.environ.get(PROC_ENV_VAR, ""),
        "event": event,
    }
    record.update(fields)
    try:
        with _lock:
            handle = _open()
            if handle is None:
                return
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    except (OSError, TypeError, ValueError):
        # Measurement logging must never break the peer.
        pass


def read_events(path: str) -> list[dict]:
    """Read an event file, skipping a truncated final line or bad lines."""
    events = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict) and "event" in record and "mono" in record:
                    events.append(record)
    except FileNotFoundError:
        pass
    return events
