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

Event names and their fields are listed in bittorrent_lite/docs/debargha/log-events.md.
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
_sequence = 0


def _open():
    global _file, _path, _sequence
    path = os.environ.get(ENV_VAR)
    if not path:
        return None
    if _file is None or _path != path:
        # Acceptance uses a fresh file and makes logging failures observable.
        # Ordinary manual/legacy logging retains its append/nonfatal contract.
        mode = 'x' if os.environ.get('BTL_LOG_STRICT') == '1' else 'a'
        opened = open(path, mode, encoding="utf-8", buffering=1)
        previous = _file
        _file = opened
        _path = path
        _sequence = 0
        if previous is not None:
            previous.close()
    return _file


def emit(event: str, proc: str | None = None, **fields) -> None:
    """Append one event; BTL_LOG_STRICT=1 rejects evidence loss immediately."""
    global _sequence
    strict = os.environ.get('BTL_LOG_STRICT') == '1'
    try:
        with _lock:
            handle = _open()
            if handle is None:
                return
            record = {
                "mono": time.monotonic(),
                "proc": proc or os.environ.get(PROC_ENV_VAR, ""),
                "event": event,
            }
            record.update(fields)
            if strict:
                if {'mono', 'log_sequence', 'log_pid', 'log_schema'} & fields.keys():
                    raise ValueError('strict log identity/time fields are reserved')
                record.update(log_schema='btl-log-v1', log_sequence=_sequence,
                              log_pid=os.getpid())
                _sequence += 1
            encoded = json.dumps(record, separators=(",", ":"), allow_nan=not strict) + "\n"
            written = handle.write(encoded)
            if strict:
                if written != len(encoded):
                    raise OSError('incomplete strict event write')
                handle.flush()
    except (OSError, TypeError, ValueError):
        if strict:
            raise
        # Preserve optional legacy logging behavior outside acceptance.


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
