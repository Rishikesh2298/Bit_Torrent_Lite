"""Owner-thread peer orchestration, independent of socket/tracker implementations."""
from dataclasses import dataclass
from pathlib import Path
from queue import Queue, Empty, Full
from typing import Protocol, Callable
import math
import threading
import time

from bittorrent_lite.scheduler.adapters import SchedulerBridge
from bittorrent_lite.scheduler.models import SchedulerConfig
from recovery_policy import RecoveryConfig
from upload_service import UploadConfig


@dataclass(frozen=True)
class RuntimeConfig:
    strategy: str = "rarest-first"
    window: int = 4
    seed: int = 0
    free_rider: bool = False
    upload_workers: int = 0
    tick_interval: float = .1
    shutdown_timeout: float = 5.0
    retry_interval: float = 5.0
    event_batch: int = 128

    def __post_init__(self):
        self.scheduler_config()
        if type(self.free_rider) is not bool:
            raise ValueError("free_rider must be a boolean")
        UploadConfig(workers=self.upload_workers)
        for name in ("tick_interval", "shutdown_timeout", "retry_interval"):
            value = getattr(self, name)
            if (type(value) not in (int, float) or not math.isfinite(value) or value <= 0):
                raise ValueError(f"{name} must be finite and positive")
        if self.tick_interval > .1:
            raise ValueError("tick_interval must be at most 100 ms")
        if type(self.event_batch) is not int or not 1 <= self.event_batch <= 128:
            raise ValueError("event_batch must be between 1 and 128")

    def scheduler_config(self):
        return SchedulerConfig(request_window=self.window, recovery_seed=self.seed,
                               recovery=RecoveryConfig(strategy=self.strategy,
                                                       endgame_enabled=False, max_copies=1))


@dataclass(frozen=True)
class Candidate:
    peer_id: str
    ip: str
    port: int


@dataclass(frozen=True)
class Session:
    """Backend has validated handshake/identity and exchanged initial bitfields."""
    connection_id: int
    peer_id: str
    bitfield: tuple
    send: Callable
    withdraw: Callable
    close: Callable
    local_bitfield: tuple | None = None


class Backend(Protocol):
    """All commands enqueue promptly; only join may wait, within its timeout."""
    def start(self, runtime: "PeerRuntime") -> None: ...
    def connect(self, candidate: Candidate) -> bool: ...
    def completed(self) -> None: ...
    def stop(self) -> None: ...
    def join(self, timeout: float) -> bool: ...


class PeerRuntime:
    def __init__(self, peer_id, store, output_path, backend: Backend, *,
                 config=None, clock=None, emit=None):
        if not isinstance(peer_id, str) or not 1 <= len(peer_id) <= 128:
            raise ValueError("invalid peer ID")
        self.config = config or RuntimeConfig()
        self.peer_id = peer_id
        self.store = store
        self.file_id = store.file_id
        self.output_path = Path(output_path)
        self.backend = backend
        self.bridge = SchedulerBridge(clock)
        self.coordinator = self.bridge.create_coordinator(
            store, scheduler_config=self.config.scheduler_config(),
            upload_config=UploadConfig(workers=self.config.upload_workers))
        if self.config.free_rider:
            self.coordinator.uploads.set_upload_enabled(False)
        self._emit = emit or (lambda record: None)
        self._owner = threading.get_ident()
        self._controls = Queue(maxsize=32)
        self._stop = threading.Event()
        self._publish_lock = threading.Lock()
        self._started = False
        self._closed = False
        self._start_time = None
        self._completion_seconds = None
        self._last_status = None
        self._candidates = ()
        self._attempts = {}
        self._advertised = tuple(self.coordinator.snapshot()["local_bitfield"])
        self.shutdown_errors = []

    def _check(self):
        if threading.get_ident() != self._owner:
            raise RuntimeError("runtime mutation requires its owner thread")

    @property
    def advertised_bitfield(self):
        """Immutable ownership snapshot for a backend's initial BITFIELD."""
        return self._advertised

    def _publish(self, kind, value):
        with self._publish_lock:
            if self._stop.is_set():
                return False
            try:
                self._controls.put_nowait((kind, value))
                return True
            except Full:
                return False

    def publish_candidates(self, candidates):
        """Worker-safe bounded discovery snapshot; caller retries on False."""
        candidates = tuple(candidates)
        if len(candidates) > 128:
            raise ValueError("at most 128 discovery candidates")
        for p in candidates:
            if (not isinstance(p, Candidate) or not isinstance(p.peer_id, str)
                    or not 1 <= len(p.peer_id) <= 128 or not isinstance(p.ip, str)
                    or not p.ip or type(p.port) is not int or not 1 <= p.port <= 65535):
                raise ValueError("invalid discovery candidate")
        return self._publish("candidates", candidates)

    def publish_session(self, session):
        """Worker-safe admission after handshake; rejected sessions are closed."""
        if not isinstance(session, Session):
            raise ValueError("expected Session")
        if not all(callable(x) for x in (session.send, session.withdraw, session.close)):
            raise ValueError("session callbacks must be callable")
        # Copy the remote advertisement before crossing the thread boundary.
        copied = Session(session.connection_id, session.peer_id, tuple(session.bitfield),
                         session.send, session.withdraw, session.close,
                         tuple(session.local_bitfield) if session.local_bitfield is not None else None)
        if not self._publish("session", copied):
            copied.close("runtime unavailable or control queue full")
            return False
        return True

    def publish_tracker_error(self, message):
        return self._publish("tracker_error", str(message)[:512])

    def _record(self, event, **fields):
        self._emit({"event": event, "peer_id": self.peer_id,
                    "at": self.bridge.clock.now(), **fields})

    def start(self):
        self._check()
        if self._closed:
            raise RuntimeError("runtime is closed")
        if self._started:
            return
        self._started = True
        self._start_time = self.bridge.clock.now()
        self.backend.start(self)
        self._record("START", file_id=self.file_id, strategy=self.config.strategy,
                     window=self.config.window, seed=self.config.seed,
                     free_rider=self.config.free_rider)

    def _admit(self, session):
        snap = self.coordinator.snapshot()
        active = [n["peer_id"] for n in snap["neighbors"].values() if n["active"]]
        if (type(session.connection_id) is not int or session.connection_id <= 0
                or not isinstance(session.peer_id, str) or not 1 <= len(session.peer_id) <= 128
                or session.peer_id == self.peer_id or session.peer_id in active
                or len(active) >= 10 or len(session.bitfield) != self.store.metadata.num_pieces
                or any(type(b) not in (bool, int) or b not in (0, 1) for b in session.bitfield)
                or (session.local_bitfield is not None and (
                    len(session.local_bitfield) != self.store.metadata.num_pieces
                    or any(type(b) not in (bool, int) or b not in (0, 1) for b in session.local_bitfield)))):
            session.close("invalid or duplicate active session")
            return
        try:
            self.bridge.register(session.connection_id, session.peer_id, session.send,
                                 withdraw=session.withdraw, close=session.close)
        except ValueError:
            session.close("connection ID already used")
            return
        from bittorrent_lite.protocol.messages import BitfieldMsg
        self.bridge.received(session.connection_id, BitfieldMsg(list(session.bitfield)))
        self.bridge.drain(self.coordinator, self.config.event_batch)
        # Reconcile pieces acquired between the backend's initial BITFIELD and
        # owner-thread admission. Without its snapshot, redundant HAVE is safe.
        initial = session.local_bitfield or (False,) * self.store.metadata.num_pieces
        for index, have in enumerate(self.coordinator.snapshot()["local_bitfield"]):
            if have and not initial[index]:
                if not self.bridge.send_have(session.connection_id, index):
                    self.bridge.close_connection(session.connection_id, "initial HAVE queue full")
                    break
        self._record("CONNECTED", connection_id=session.connection_id, remote=session.peer_id)

    def step(self):
        self._check()
        if not self._started:
            raise RuntimeError("start the runtime before stepping")
        if self._closed or self._stop.is_set():
            return self.status()
        for _ in range(32):
            try:
                kind, value = self._controls.get_nowait()
            except Empty:
                break
            if kind == "session":
                self._admit(value)
            elif kind == "candidates":
                self._candidates = value
                ids = {p.peer_id for p in value}
                self._attempts = {p: t for p, t in self._attempts.items() if p in ids}
            else:
                self._record("TRACKER_ERROR", message=value)
        self.bridge.drain(self.coordinator, self.config.event_batch)
        expired = self.coordinator.tick()
        for request in expired:
            self._record("REQUEST_EXPIRED", connection_id=request.connection_id,
                         request_id=request.request_id, piece=request.piece_index,
                         reason=request.kind)
        snap = self.coordinator.snapshot()
        if snap["ready_to_assemble"] and not snap["complete"] and not snap["paused"]:
            if self.coordinator.finalize_download(str(self.output_path)):
                self._completion_seconds = self.bridge.clock.now() - self._start_time
                self._record("COMPLETE", completion_seconds=self._completion_seconds)
                # Discovery failures must not undo a completed download.
                try:
                    self.backend.completed()
                except OSError as exc:
                    self._record("TRACKER_ERROR", message=str(exc))
        snap = self.coordinator.snapshot()
        self._advertised = tuple(snap["local_bitfield"])
        active = {n["peer_id"] for n in snap["neighbors"].values() if n["active"]}
        now = self.bridge.clock.now()
        pending = sum(now - t < self.config.retry_interval
                      for p, t in self._attempts.items() if p not in active)
        for candidate in self._candidates:
            if (len(active) + pending >= 10 or candidate.peer_id in active
                    or self.peer_id >= candidate.peer_id
                    or now - self._attempts.get(candidate.peer_id, -float("inf"))
                    < self.config.retry_interval):
                continue
            self._attempts[candidate.peer_id] = now
            try:
                if self.backend.connect(candidate):
                    pending += 1
            except OSError as exc:
                self._record("CONNECT_FAILED", remote=candidate.peer_id, message=str(exc))
        status = self.status()
        if status["state"] != self._last_status:
            self._record("STATUS", **status)
            self._last_status = status["state"]
        return status

    def status(self):
        self._check()
        snap = self.coordinator.snapshot()
        state = ("STOPPED" if self._closed else "ERROR" if snap["paused"]
                 else "SEEDING" if snap["complete"] else "STALLED" if snap["stalled"]
                 else "DOWNLOADING")
        return {"state": state, "owned": snap["owned"], "total": snap["total"],
                "verified_download_bytes": snap["verified_download_bytes"],
                "uploaded_payload_bytes": snap["uploads"]["service"]["sent_bytes"],
                "completion_seconds": self._completion_seconds,
                "storage_error": snap["storage_error"], "recovery_error": snap["recovery_error"]}

    def request_stop(self):
        """Worker/signal-safe; cleanup happens on the owner thread."""
        self._stop.set()

    def run(self):
        self._check()
        try:
            self.start()
            while not self._stop.is_set():
                self.step()
                self._stop.wait(self.config.tick_interval)
        finally:
            self.shutdown()

    def shutdown(self):
        self._check()
        if self._closed:
            self.reap_shutdown()
            return tuple(self.shutdown_errors)
        with self._publish_lock:
            self._stop.set()
            self._closed = True
        deadline = time.monotonic() + self.config.shutdown_timeout
        try:
            self.backend.stop()
        except Exception as exc:
            self.shutdown_errors.append(f"backend stop: {exc}")
        self.shutdown_errors.extend(self.bridge.shutdown())
        while True:
            try:
                kind, value = self._controls.get_nowait()
            except Empty:
                break
            if kind == "session":
                try:
                    value.close("shutdown before admission")
                except Exception as exc:
                    self.shutdown_errors.append(f"unadmitted close: {exc}")
        self.coordinator.shutdown()
        try:
            if not self.backend.join(max(0, deadline - time.monotonic())):
                self.shutdown_errors.append("backend workers did not stop before deadline")
        except Exception as exc:
            self.shutdown_errors.append(f"backend join: {exc}")
        service = self.coordinator.uploads.service
        service.tick()  # harvest finished reads even when backend join used the deadline
        while service.snapshot().active_jobs and time.monotonic() < deadline:
            service.tick()
            threading.Event().wait(min(.01, max(0, deadline - time.monotonic())))
        if service.snapshot().active_jobs:
            self.shutdown_errors.append("upload reads still running after shutdown deadline")
        else:
            service.shutdown(wait=True)
        self._record("STOPPED", errors=list(self.shutdown_errors), **self.status())
        return tuple(self.shutdown_errors)

    def reap_shutdown(self):
        """Nonblocking cleanup after a provider outlives the shutdown deadline."""
        self._check()
        if not self._closed:
            raise RuntimeError("shutdown has not begun")
        service = self.coordinator.uploads.service
        service.tick()
        if service.snapshot().active_jobs:
            return False
        service.shutdown(wait=True)
        return True
