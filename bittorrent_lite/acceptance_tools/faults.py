"""Finite, owned socket and storage fault injection for acceptance preparation.

These helpers never claim successful application transfers. Every socket action
records its endpoint and actual bytes accepted by ``send`` or returned by
``recv``. ``send`` counts are local socket-write observations, not remote receipt.
Storage faults touch only a newly created, explicitly owned directory. No global
network settings, firewall rules, disk filling, or process-name termination.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import threading
import time
from tempfile import NamedTemporaryFile


MAX_SCRIPT_BYTES = 8 * 1024 * 1024


def _number(value, name, *, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError(f"{name} must be a finite {'positive' if positive else 'nonnegative'} number")
    return float(value)


def _integer(value, name, *, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


def _not_redirected(path):
    path = Path(path).absolute()
    for candidate in (path, *path.parents):
        if candidate.is_symlink() or (hasattr(candidate, "is_junction") and candidate.is_junction()):
            raise ValueError(f"redirected path is not owned: {candidate}")
    return path


class FaultTrace:
    """Exclusive-create JSONL trace. Closed/truncated/missing traces never pass."""
    def __init__(self, path, owner):
        if not isinstance(owner, str) or not owner:
            raise ValueError("a nonempty campaign/case owner is required")
        self.path = _not_redirected(path)
        self._stream = self.path.open("x", encoding="utf-8", newline="\n")
        self._lock = threading.Lock()
        self._sequence = 0
        self._owner = owner
        self._closed = False
        self.emit("trace_started", pid=os.getpid())

    def emit(self, event, **fields):
        with self._lock:
            if self._closed:
                raise RuntimeError("fault trace is closed")
            row = {"schema": "btl-fault-v1", "owner": self._owner,
                   "sequence": self._sequence, "event": event,
                   "utc": datetime.now(timezone.utc).isoformat(),
                   "monotonic": time.monotonic(), "thread_id": threading.get_ident(), **fields}
            self._stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
            self._stream.flush()
            self._sequence += 1

    def bytes(self, event, data, **fields):
        self.emit(event, byte_count=len(data), sha256=hashlib.sha256(data).hexdigest(),
                  data_hex=data.hex(), **fields)

    def close(self):
        if not self._closed:
            self.emit("trace_closed")
            with self._lock:
                self._stream.flush()
                os.fsync(self._stream.fileno())
                self._stream.close()
                self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def frame(header, payload=b""):
    """Independent fixture encoder, deliberately not a project protocol oracle.

    Callers can supply invalid declared fields for negative cases. Valid scripts
    must declare ``payload_length`` themselves; no silent repair is performed.
    """
    if not isinstance(header, dict) or type(payload) is not bytes:
        raise ValueError("header dictionary and immutable payload bytes required")
    encoded = json.dumps(header, separators=(",", ":"), ensure_ascii=False,
                         allow_nan=False).encode("utf-8")
    if len(encoded) + len(payload) > MAX_SCRIPT_BYTES:
        raise ValueError("fault fixture exceeds bounded script size")
    return len(encoded).to_bytes(4, "big") + encoded + payload


def corrupt_byte(payload, index, mask=1):
    if type(payload) is not bytes:
        raise ValueError("payload must be immutable bytes")
    _integer(index, "index")
    _integer(mask, "mask", minimum=1)
    if index >= len(payload) or mask > 255:
        raise ValueError("corruption must select one existing byte and an 8-bit nonzero mask")
    return payload[:index] + bytes((payload[index] ^ mask,)) + payload[index + 1:]


@dataclass(frozen=True)
class Send:
    data: bytes
    fragments: tuple[int, ...] = ()
    gap_s: float = 0.0
    bytes_per_second: float | None = None
    corrupt_offset: int | None = None
    xor_mask: int = 1

    def __post_init__(self):
        if type(self.data) is not bytes or len(self.data) > MAX_SCRIPT_BYTES:
            raise ValueError("send data must be bounded immutable bytes")
        if type(self.fragments) is not tuple or any(type(n) is not int or n <= 0 for n in self.fragments):
            raise ValueError("fragments must be a tuple of positive byte counts")
        if self.fragments and sum(self.fragments) != len(self.data):
            raise ValueError("fragment sizes must cover data exactly")
        _number(self.gap_s, "gap_s")
        if self.bytes_per_second is not None:
            _number(self.bytes_per_second, "bytes_per_second", positive=True)
        if self.corrupt_offset is not None:
            corrupt_byte(self.data, self.corrupt_offset, self.xor_mask)


@dataclass(frozen=True)
class Receive:
    length: int
    expected: bytes | None = None

    def __post_init__(self):
        _integer(self.length, "length")
        if self.length > MAX_SCRIPT_BYTES:
            raise ValueError("receive exceeds script bound")
        if self.expected is not None and (type(self.expected) is not bytes or len(self.expected) != self.length):
            raise ValueError("expected bytes must have the exact declared length")


@dataclass(frozen=True)
class Pause:
    seconds: float

    def __post_init__(self):
        _number(self.seconds, "seconds")


@dataclass(frozen=True)
class Drop:
    """Predeclared connection close at this exact point in the script."""
    reason: str = "scripted_close"

    def __post_init__(self):
        if not isinstance(self.reason, str) or not self.reason:
            raise ValueError("drop requires a declared nonempty reason")


@dataclass(frozen=True)
class ExpectEOF:
    """No additional bytes are permitted before peer closure."""


def _endpoint(sock):
    try:
        return {"local": list(sock.getsockname()), "remote": list(sock.getpeername())}
    except OSError:
        return {}


class SocketFaultPeer:
    """One loopback listener, one connection, one finite recorded action script."""
    def __init__(self, script, trace, *, timeout=10.0):
        if not isinstance(script, (list, tuple)) or len(script) > 4096:
            raise ValueError("script must be a finite list/tuple of at most 4096 actions")
        self.script = tuple(script)
        if not self.script or any(type(action) not in (Send, Receive, Pause, Drop, ExpectEOF) for action in self.script):
            raise ValueError("script must contain only declared fault actions")
        if any(isinstance(action, Drop) for action in self.script[:-1]):
            raise ValueError("drop must be the final action; unreachable actions are forbidden")
        if sum(len(action.data) if isinstance(action, Send) else action.length if isinstance(action, Receive) else 0
               for action in self.script) > MAX_SCRIPT_BYTES:
            raise ValueError("total script bytes exceed limit")
        self.timeout = _number(timeout, "timeout", positive=True)
        self.trace = trace
        self._stop = threading.Event()
        self._listener = None
        self._connection = None
        self._thread = None
        self.error = None
        self.completed = False
        self.received = []
        self.address = None

    def start(self):
        if self._thread is not None:
            raise RuntimeError("fault peer cannot be reused")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(0.05)
        except BaseException:
            listener.close()
            raise
        self._listener = listener
        self.address = listener.getsockname()
        self._deadline = time.monotonic() + self.timeout
        self.trace.emit("peer_listening", endpoint=list(self.address), timeout=self.timeout)
        self._thread = threading.Thread(target=self._run, name="acceptance-fault-peer", daemon=False)
        self._thread.start()
        return self

    def _check(self):
        if self._stop.is_set():
            raise InterruptedError("owned fault peer stopped")
        if time.monotonic() >= self._deadline:
            raise TimeoutError("fault script deadline expired")

    def _pause(self, seconds):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            self._check()
            self._stop.wait(min(0.05, until - time.monotonic()))

    def _send(self, action, step):
        data = action.data
        if action.corrupt_offset is not None:
            data = corrupt_byte(data, action.corrupt_offset, action.xor_mask)
            self.trace.emit("fault_triggered", fault="peer_corruption", step=step,
                            offset=action.corrupt_offset, xor_mask=action.xor_mask,
                            before_sha256=hashlib.sha256(action.data).hexdigest(),
                            after_sha256=hashlib.sha256(data).hexdigest())
        sizes = action.fragments or ((len(action.data),) if action.data else ())
        offset, total, started = 0, 0, time.monotonic()
        for number, size in enumerate(sizes):
            if number:
                self._pause(action.gap_s)
            fragment_end = offset + size
            while offset < fragment_end:
                self._check()
                # Rate limiting permits at most a 1 KiB initial burst.
                end = min(fragment_end, offset + 1024) if action.bytes_per_second else fragment_end
                try:
                    count = self._connection.send(data[offset:end])
                except socket.timeout:
                    continue
                if count <= 0:
                    raise ConnectionError("zero socket write")
                sent = data[offset:offset + count]
                self.trace.bytes("socket_write", sent, step=step, fragment=number,
                                 **_endpoint(self._connection))
                offset += count
                total += count
                if action.bytes_per_second:
                    self._pause(max(0, started + total / action.bytes_per_second - time.monotonic()))

    def _receive(self, action, step):
        chunks, length = [], 0
        while length < action.length:
            self._check()
            try:
                data = self._connection.recv(min(65536, action.length - length))
            except socket.timeout:
                continue
            if not data:
                raise EOFError(f"received {length} of {action.length} expected bytes")
            self.trace.bytes("socket_read", data, step=step, **_endpoint(self._connection))
            chunks.append(data)
            length += len(data)
        received = b"".join(chunks)
        if action.expected is not None and received != action.expected:
            raise AssertionError("fault peer received bytes different from predeclared oracle")
        self.received.append(received)

    def _run(self):
        try:
            while self._connection is None:
                self._check()
                try:
                    self._connection, _ = self._listener.accept()
                except socket.timeout:
                    continue
            self._connection.settimeout(0.05)
            self.trace.emit("peer_connected", **_endpoint(self._connection))
            for step, action in enumerate(self.script):
                self._check()
                self.trace.emit("action_started", step=step, action=type(action).__name__)
                if isinstance(action, Send):
                    self.trace.emit("send_plan", step=step, bytes=len(action.data),
                                    sha256=hashlib.sha256(action.data).hexdigest(),
                                    fragments=action.fragments, gap_s=action.gap_s,
                                    bytes_per_second=action.bytes_per_second)
                    self._send(action, step)
                elif isinstance(action, Receive):
                    self._receive(action, step)
                elif isinstance(action, Pause):
                    self._pause(action.seconds)
                elif isinstance(action, Drop):
                    self.trace.emit("fault_triggered", step=step, fault="connection_drop", reason=action.reason)
                    break
                else:
                    while True:
                        self._check()
                        try:
                            data = self._connection.recv(1)
                        except socket.timeout:
                            continue
                        self.trace.bytes("socket_read_eof_probe", data, step=step, **_endpoint(self._connection))
                        if data:
                            raise AssertionError("unexpected bytes before expected EOF")
                        break
                self.trace.emit("action_completed", step=step)
            self.trace.emit("script_completed")
            self.completed = True
        except BaseException as exc:
            if self._stop.is_set() and isinstance(exc, (OSError, InterruptedError)):
                self.trace.emit("script_cancelled", reason=str(exc))
            else:
                self.error = exc
                self.trace.emit("script_failed", error=type(exc).__name__, reason=str(exc))
        finally:
            self._close_sockets()
            self.trace.emit("peer_exited")

    def _close_sockets(self):
        for sock in (self._connection, self._listener):
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                sock.close()

    def wait(self, timeout=None):
        if self._thread is None:
            raise RuntimeError("fault peer has not started")
        bound = self.timeout + 1 if timeout is None else _number(timeout, "wait timeout", positive=True)
        self._thread.join(bound)
        if self._thread.is_alive():
            raise TimeoutError("fault peer did not exit within wait bound")
        if self.error is not None:
            raise RuntimeError(f"fault peer failed: {self.error}") from self.error
        if not self.completed:
            raise RuntimeError("fault peer was stopped before script completion")

    def close(self):
        self._stop.set()
        self._close_sockets()
        if self._thread is not None:
            self._thread.join(2)
            if self._thread.is_alive():
                raise TimeoutError("owned fault peer thread did not stop")

    @property
    def alive(self):
        return self._thread is not None and self._thread.is_alive()

    def __enter__(self):
        return self.start()

    def __exit__(self, *_):
        self.close()


@dataclass(frozen=True)
class RelayRule:
    chunk_size: int = 1024
    delay_s: float = 0.0
    bytes_per_second: float | None = None
    corrupt_offset: int | None = None
    xor_mask: int = 1
    drop_after: int | None = None
    max_bytes: int = MAX_SCRIPT_BYTES

    def __post_init__(self):
        _integer(self.chunk_size, "chunk_size", minimum=1)
        _integer(self.max_bytes, "max_bytes", minimum=1)
        if self.chunk_size > 65536 or self.max_bytes > MAX_SCRIPT_BYTES:
            raise ValueError("relay bounds exceed helper limits")
        _number(self.delay_s, "delay_s")
        if self.bytes_per_second is not None:
            _number(self.bytes_per_second, "bytes_per_second", positive=True)
        if self.corrupt_offset is not None:
            _integer(self.corrupt_offset, "corrupt_offset")
            if self.corrupt_offset >= self.max_bytes or (self.drop_after is not None and self.corrupt_offset >= self.drop_after):
                raise ValueError("corruption must occur before the drop/byte bound")
        _integer(self.xor_mask, "xor_mask", minimum=1)
        if self.xor_mask > 255:
            raise ValueError("xor_mask must fit one byte")
        if self.drop_after is not None:
            _integer(self.drop_after, "drop_after")
            if self.drop_after > self.max_bytes:
                raise ValueError("drop trigger exceeds byte budget")


class SocketFaultProxy:
    """Loopback-only, one-session, bidirectional proxy with bounded relay work.

    Rules operate independently per direction. Delayed writes may change stream
    chunking; logs retain actual recv/send boundaries. This does not claim OS-level
    packet shaping. Upstream must be an explicitly supplied owned test endpoint.
    """
    def __init__(self, upstream, trace, *, outbound=RelayRule(), inbound=RelayRule(), timeout=10.0):
        if (not isinstance(upstream, tuple) or len(upstream) != 2 or upstream[0] != "127.0.0.1"
                or type(upstream[1]) is not int or not 1 <= upstream[1] <= 65535):
            raise ValueError("proxy upstream must be an explicit loopback test endpoint")
        if not isinstance(outbound, RelayRule) or not isinstance(inbound, RelayRule):
            raise ValueError("typed relay rules required")
        self.upstream, self.trace = upstream, trace
        self.rules = (outbound, inbound)
        self.timeout = _number(timeout, "timeout", positive=True)
        self._stop = threading.Event()
        self._sockets = []
        self._relays = []
        self._thread = None
        self.error = None
        self._error_lock = threading.Lock()
        self._triggered = set()
        self._eof = set()
        self._completed = False

    def start(self):
        if self._thread is not None:
            raise RuntimeError("fault proxy cannot be reused")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(0.05)
        except BaseException:
            listener.close()
            raise
        self._sockets.append(listener)
        self.address = listener.getsockname()
        self._deadline = time.monotonic() + self.timeout
        self.trace.emit("proxy_listening", endpoint=list(self.address), upstream=list(self.upstream), timeout=self.timeout)
        self._thread = threading.Thread(target=self._run, name="acceptance-fault-proxy", daemon=False)
        self._thread.start()
        return self

    def _check(self):
        if self._stop.is_set():
            raise InterruptedError("owned proxy stopped")
        if time.monotonic() >= self._deadline:
            raise TimeoutError("proxy deadline expired")

    def _pause(self, seconds):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            self._check()
            self._stop.wait(min(0.05, until - time.monotonic()))

    def _relay(self, source, destination, rule, direction):
        observed, forwarded, started = 0, 0, time.monotonic()
        try:
            while True:
                self._check()
                if rule.drop_after is not None and forwarded == rule.drop_after:
                    self.trace.emit("fault_triggered", fault="proxy_drop", direction=direction, offset=forwarded)
                    self._triggered.add((direction, "drop"))
                    self._stop.set()
                    self._close_sockets()
                    return
                budget = rule.max_bytes - observed
                try:
                    data = source.recv(min(rule.chunk_size, budget) if budget > 0 else 1)
                except socket.timeout:
                    continue
                self.trace.bytes("proxy_read", data, direction=direction, stream_offset=observed, **_endpoint(source))
                if not data:
                    self._eof.add(direction)
                    try:
                        destination.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass
                    return
                if budget <= 0:
                    raise ValueError("relay byte budget exceeded")
                if rule.corrupt_offset is not None and observed <= rule.corrupt_offset < observed + len(data):
                    original = data
                    data = corrupt_byte(data, rule.corrupt_offset - observed, rule.xor_mask)
                    self.trace.emit("fault_triggered", fault="proxy_corruption", direction=direction,
                                    offset=rule.corrupt_offset, xor_mask=rule.xor_mask,
                                    before_sha256=hashlib.sha256(original).hexdigest(),
                                    after_sha256=hashlib.sha256(data).hexdigest())
                    self._triggered.add((direction, "corruption"))
                observed += len(data)
                if rule.drop_after is not None:
                    data = data[:max(0, rule.drop_after - forwarded)]
                self._pause(rule.delay_s)
                offset = 0
                while offset < len(data):
                    self._check()
                    try:
                        count = destination.send(data[offset:])
                    except socket.timeout:
                        continue
                    if count <= 0:
                        raise ConnectionError("zero proxy socket write")
                    self.trace.bytes("proxy_write", data[offset:offset + count], direction=direction,
                                     stream_offset=forwarded, **_endpoint(destination))
                    offset += count
                    forwarded += count
                    if rule.bytes_per_second:
                        self._pause(max(0, started + forwarded / rule.bytes_per_second - time.monotonic()))
        except BaseException as exc:
            if self._stop.is_set() and isinstance(exc, (OSError, InterruptedError)):
                self.trace.emit("relay_cancelled", direction=direction, reason=str(exc))
            else:
                with self._error_lock:
                    if self.error is None:
                        self.error = exc
                self.trace.emit("relay_failed", direction=direction, error=type(exc).__name__, reason=str(exc))
                self._stop.set()
                self._close_sockets()
        finally:
            self.trace.emit("relay_exited", direction=direction, bytes_observed=observed, bytes_forwarded=forwarded)

    def _run(self):
        try:
            while True:
                self._check()
                try:
                    client, _ = self._sockets[0].accept()
                    break
                except socket.timeout:
                    continue
            self._sockets.append(client)
            upstream = socket.create_connection(self.upstream, timeout=min(1, self.timeout))
            self._sockets.append(upstream)
            for sock in (client, upstream):
                sock.settimeout(0.05)
            self.trace.emit("proxy_connected", client=_endpoint(client), upstream=_endpoint(upstream))
            for source, destination, rule, direction in [
                (client, upstream, self.rules[0], "outbound"),
                (upstream, client, self.rules[1], "inbound"),
            ]:
                self.trace.emit("relay_plan", direction=direction, rule=rule.__dict__)
                thread = threading.Thread(target=self._relay, args=(source, destination, rule, direction),
                                          name=f"acceptance-relay-{direction}", daemon=False)
                self._relays.append(thread)
                thread.start()
            for thread in self._relays:
                thread.join(max(0, self._deadline - time.monotonic()) + 0.2)
            if any(thread.is_alive() for thread in self._relays):
                raise TimeoutError("proxy relay did not finish")
            self._completed = (self._eof == {"outbound", "inbound"}
                               or any(fault == "drop" for _, fault in self._triggered))
        except BaseException as exc:
            if not (self._stop.is_set() and isinstance(exc, (OSError, InterruptedError))):
                with self._error_lock:
                    if self.error is None:
                        self.error = exc
                self.trace.emit("proxy_failed", error=type(exc).__name__, reason=str(exc))
        finally:
            self._stop.set()
            self._close_sockets()
            for thread in self._relays:
                thread.join(1)
            self.trace.emit("proxy_exited", live_relays=sum(thread.is_alive() for thread in self._relays))

    def _close_sockets(self):
        for sock in tuple(self._sockets):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

    @property
    def alive(self):
        return ((self._thread is not None and self._thread.is_alive())
                or any(thread.is_alive() for thread in self._relays))

    def wait(self, timeout=None):
        if self._thread is None:
            raise RuntimeError("proxy has not started")
        self._thread.join(self.timeout + 2 if timeout is None else _number(timeout, "wait timeout", positive=True))
        if self.alive:
            raise TimeoutError("proxy did not exit within wait bound")
        if self.error is not None:
            raise RuntimeError(f"proxy failed: {self.error}") from self.error
        if not self._completed:
            raise RuntimeError("proxy stopped before both EOFs or a declared drop")
        expected = {(direction, fault) for direction, rule in zip(("outbound", "inbound"), self.rules)
                    for fault, configured in (("drop", rule.drop_after), ("corruption", rule.corrupt_offset))
                    if configured is not None}
        if expected != self._triggered:
            raise AssertionError(f"untriggered proxy faults: {sorted(expected - self._triggered)}")

    def close(self):
        self._stop.set()
        self._close_sockets()
        if self._thread is not None:
            self._thread.join(3)
            if self.alive:
                raise TimeoutError("owned proxy threads did not stop")

    def __enter__(self):
        return self.start()

    def __exit__(self, *_):
        self.close()


@dataclass(frozen=True)
class StorageFault:
    operation: str
    call: int = 1
    after_bytes: int = 0
    error_number: int = errno.EIO

    def __post_init__(self):
        if self.operation not in {"read", "write", "replace", "assembly.read", "assembly.write", "assembly.replace"}:
            raise ValueError("unknown storage fault operation")
        _integer(self.call, "call", minimum=1)
        _integer(self.after_bytes, "after_bytes")
        _integer(self.error_number, "error_number", minimum=1)
        if self.after_bytes > MAX_SCRIPT_BYTES or (self.operation.endswith("replace") and self.after_bytes):
            raise ValueError("invalid partial-operation byte bound")


class StorageFaults:
    """Module-local open/replace adapter for one newly created owned directory.

    A test can inject ``adapter.open`` into a specific storage module and replace
    that module's ``os`` binding with an adapter exposing ``replace``. Never patch
    ``builtins.open`` or global ``os.replace``. ``phase('assembly')`` selects
    assembly-specific fault points. Inputs and partial files are retained.
    """
    def __init__(self, root, trace, faults=()):
        self.root = _not_redirected(root).resolve()
        if self.root.exists():
            raise FileExistsError("storage fault root must be freshly owned")
        self.faults = tuple(faults)
        if any(not isinstance(fault, StorageFault) for fault in self.faults):
            raise ValueError("typed storage faults required")
        keys = [(fault.operation, fault.call) for fault in self.faults]
        if len(set(keys)) != len(keys):
            raise ValueError("ambiguous storage fault trigger")
        self.root.mkdir()
        self.trace = trace
        self._counts = {}
        self._lock = threading.Lock()
        self._phase = threading.local()
        self.open_handles = 0
        self.triggered = []
        trace.emit("storage_owned", root=str(self.root), faults=[fault.__dict__ for fault in self.faults])

    def owned_path(self, path):
        path = Path(path)
        if not path.is_absolute():
            path = self.root / path
        path = _not_redirected(path)
        resolved = path.resolve()
        if resolved == self.root or self.root not in resolved.parents:
            raise ValueError("fault operation must stay inside the owned storage root")
        if path.exists() and path.is_file() and path.stat().st_nlink != 1:
            raise ValueError("hard-linked files are not exclusively owned")
        return path

    @contextmanager
    def phase(self, name):
        if name not in ("normal", "assembly"):
            raise ValueError("unknown storage phase")
        previous = getattr(self._phase, "name", "normal")
        self._phase.name = name
        try:
            yield self
        finally:
            self._phase.name = previous

    def _trigger(self, operation, path):
        phase = getattr(self._phase, "name", "normal")
        key = operation if phase == "normal" else f"{phase}.{operation}"
        with self._lock:
            count = self._counts[key] = self._counts.get(key, 0) + 1
            self.trace.emit("storage_operation", operation=key, call=count, path=str(path))
            fault = next((item for item in self.faults if (item.operation, item.call) == (key, count)), None)
            if fault is not None:
                self.triggered.append((key, count))
                self.trace.emit("fault_triggered", fault="storage", operation=key, call=count,
                                path=str(path), after_bytes=fault.after_bytes, errno=fault.error_number)
            return fault

    def open(self, file, mode="rb", *args, **kwargs):
        path = self.owned_path(file)
        if "b" not in mode:
            raise ValueError("storage injection supports explicit binary streams only")
        handle = open(path, mode, *args, **kwargs)
        return self._wrap(path, handle, mode)

    def _wrap(self, path, handle, mode):
        with self._lock:
            self.open_handles += 1
        self.trace.emit("storage_open", path=str(path), mode=mode, descriptor=handle.fileno())
        return _StorageStream(self, path, handle)

    def temporary_file(self, *, dir, suffix=".tmp", delete=False, **kwargs):
        directory = Path(dir)
        if directory.resolve() != self.root:
            directory = self.owned_path(directory)
        if delete is not False or kwargs:
            raise ValueError("fault temporary files require explicit delete=False and default binary mode")
        handle = NamedTemporaryFile(dir=directory, suffix=suffix, delete=False)
        return self._wrap(self.owned_path(handle.name), handle, "w+b")

    def path(self, value):
        return _StoragePath(self, value)

    def bind_module(self, monkeypatch, module):
        """Patch only an explicitly supplied storage module's I/O bindings.

        Intended for pytest-scoped FileStore integration tests. All paths passed
        through these seams remain owned. Other modules and global libraries
        are unchanged. Hashing still uses the real implementation.
        """
        monkeypatch.setattr(module, "open", self.open, raising=False)
        monkeypatch.setattr(module, "NamedTemporaryFile", self.temporary_file)
        monkeypatch.setattr(module, "Path", self.path)

    def replace(self, source, destination):
        source, destination = self.owned_path(source), self.owned_path(destination)
        fault = self._trigger("replace", destination)
        if fault:
            raise OSError(fault.error_number, "predeclared owned storage replace fault", str(destination))
        os.replace(source, destination)
        self.trace.emit("storage_replaced", source=str(source), destination=str(destination))

    def assert_finished(self):
        if self.open_handles:
            raise AssertionError(f"{self.open_handles} fault-adapter handles remain open")
        expected = {(fault.operation, fault.call) for fault in self.faults}
        if set(self.triggered) != expected:
            raise AssertionError(f"untriggered storage faults: {sorted(expected - set(self.triggered))}")


class _StorageStream:
    def __init__(self, adapter, path, handle):
        self.adapter, self.path, self.handle = adapter, path, handle
        self.closed = False

    def read(self, size=-1):
        fault = self.adapter._trigger("read", self.path)
        if fault:
            count = fault.after_bytes if size < 0 else min(size, fault.after_bytes)
            data = self.handle.read(count)
            self.adapter.trace.bytes("storage_partial_read", data, path=str(self.path))
            raise OSError(fault.error_number, "predeclared owned storage read fault", str(self.path))
        data = self.handle.read(size)
        self.adapter.trace.bytes("storage_read", data, path=str(self.path))
        return data

    def write(self, data):
        fault = self.adapter._trigger("write", self.path)
        if fault:
            partial = data[:fault.after_bytes]
            count = self.handle.write(partial)
            self.handle.flush()
            self.adapter.trace.bytes("storage_partial_write", bytes(partial[:count]), path=str(self.path))
            raise OSError(fault.error_number, "predeclared owned storage write fault", str(self.path))
        count = self.handle.write(data)
        self.adapter.trace.bytes("storage_write", bytes(data[:count]), path=str(self.path))
        return count

    def close(self):
        if not self.closed:
            self.handle.close()
            self.closed = True
            with self.adapter._lock:
                self.adapter.open_handles -= 1
            self.adapter.trace.emit("storage_closed", path=str(self.path))

    def __getattr__(self, name):
        return getattr(self.handle, name)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class _StoragePath:
    """Module-local Path facade; only replace/unlink and construction differ."""
    def __init__(self, adapter, path):
        self.adapter = adapter
        raw = Path(path)
        self.path = adapter.root if raw.resolve() == adapter.root else adapter.owned_path(raw)

    def __fspath__(self):
        return str(self.path)

    def __str__(self):
        return str(self.path)

    def __truediv__(self, child):
        return _StoragePath(self.adapter, self.path / child)

    @property
    def parent(self):
        return _StoragePath(self.adapter, self.path.parent)

    def replace(self, destination):
        self.adapter.replace(self.path, destination)
        return _StoragePath(self.adapter, destination)

    def unlink(self, *, missing_ok=False):
        path = self.adapter.owned_path(self.path)
        if path.exists():
            # Record actual bytes before product cleanup removes an owned temp.
            with open(path, "rb") as stream:
                offset = 0
                while data := stream.read(65536):
                    self.adapter.trace.bytes("storage_cleanup_bytes", data, path=str(path), offset=offset)
                    offset += len(data)
            self.adapter.trace.emit("storage_cleanup", path=str(path))
        path.unlink(missing_ok=missing_ok)

    def __getattr__(self, name):
        return getattr(self.path, name)
