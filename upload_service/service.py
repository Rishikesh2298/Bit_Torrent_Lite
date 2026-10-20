"""Bounded, fair, whole-piece upload scheduler.

Threading model: every public method must be called from the thread that
constructed the service. Worker threads (``workers=2``) only run the source
callable via :func:`_execute`; they never touch queues, counters or records.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import logging
import threading
from collections import OrderedDict, deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Optional

from .models import (
    Admission,
    DataOutput,
    JobState,
    Manifest,
    Output,
    PieceMeta,
    RejectOutput,
    Snapshot,
    UploadConfig,
    UploadRequest,
)

__all__ = ["UploadService"]

_log = logging.getLogger("upload_service")


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _execute(source: Callable[[int], bytes], meta: PieceMeta) -> tuple[Optional[bytes], Optional[str]]:
    """Read and verify one piece. Pure with respect to service state."""
    try:
        data = source(meta.index)
    except Exception:  # ordinary provider failures only; BaseException propagates
        _log.debug("source error for piece %d", meta.index, exc_info=True)
        return None, "source_error"
    if type(data) is not bytes:
        return None, "invalid_source_data"
    if len(data) != meta.length:
        return None, "length_mismatch"
    if hashlib.sha256(data).hexdigest() != meta.sha256:
        return None, "hash_mismatch"
    return data, None


@dataclass(eq=False)
class _Job:
    job_id: int
    peer_id: str
    piece: int
    length: int
    state: JobState = JobState.QUEUED
    cancelled: bool = False
    future: Optional[Future] = None
    output: Optional[Output] = None
    is_data: bool = False
    data_len: int = 0
    holds_slot: bool = False
    out_reserved: int = 0
    read_reserved: int = 0


class UploadService:
    def __init__(
        self,
        manifest: Manifest,
        source: Callable[[int], bytes],
        config: UploadConfig = UploadConfig(),
    ) -> None:
        if not isinstance(manifest, Manifest):
            raise TypeError("manifest must be a Manifest")
        if not callable(source):
            raise TypeError("source must be callable")
        if not isinstance(config, UploadConfig):
            raise TypeError("config must be an UploadConfig")
        largest = manifest.max_length
        if largest > config.max_piece_length:
            raise ValueError("manifest contains a piece larger than max_piece_length")
        if config.max_output_bytes < largest:
            raise ValueError("max_output_bytes cannot hold the largest manifest piece")
        if config.max_read_bytes < largest:
            raise ValueError("max_read_bytes cannot hold the largest manifest piece")

        self._manifest = manifest
        self._source = source
        self._cfg = config
        self._owner = threading.get_ident()
        self._executor: Optional[ThreadPoolExecutor] = (
            ThreadPoolExecutor(max_workers=2, thread_name_prefix="upload-read")
            if config.workers == 2
            else None
        )

        self._next_id = 1
        self._jobs: dict[int, _Job] = {}
        self._keys: dict[tuple[str, int], int] = {}
        self._peer_counts: dict[str, int] = {}
        self._peer_queues: dict[str, deque[_Job]] = {}
        self._rr: deque[str] = deque()
        self._running: dict[int, _Job] = {}
        self._outbox: OrderedDict[int, _Job] = OrderedDict()

        self._out_slots = 0
        self._out_bytes = 0
        self._read_bytes = 0
        self._sent_bytes = 0
        self._sent_pieces = 0
        self._failed_sends = 0
        self._cancelled = 0
        self._rejected = 0
        self._source_failures = 0
        self._closed = False

    # ------------------------------------------------------------------ helpers
    def _check_thread(self) -> None:
        if threading.get_ident() != self._owner:
            raise RuntimeError("UploadService may only be used from its constructing thread")

    def _deny(self, reason: str) -> Admission:
        self._rejected += 1
        return Admission(False, None, reason)

    def _release(self, job: _Job) -> None:
        """Drop a job and every reservation it still holds."""
        self._jobs.pop(job.job_id, None)
        key = (job.peer_id, job.piece)
        if self._keys.get(key) == job.job_id:
            del self._keys[key]
        remaining = self._peer_counts.get(job.peer_id, 0) - 1
        if remaining > 0:
            self._peer_counts[job.peer_id] = remaining
        else:
            self._peer_counts.pop(job.peer_id, None)
        if job.holds_slot:
            self._out_slots -= 1
            job.holds_slot = False
        self._out_bytes -= job.out_reserved
        job.out_reserved = 0
        self._read_bytes -= job.read_reserved
        job.read_reserved = 0
        job.output = None
        job.future = None

    def _dequeue(self, job: _Job) -> None:
        queue = self._peer_queues[job.peer_id]
        queue.remove(job)
        if not queue:
            del self._peer_queues[job.peer_id]
            self._rr.remove(job.peer_id)

    # ---------------------------------------------------------------- admission
    def submit(self, request: UploadRequest, permitted: bool) -> Admission:
        self._check_thread()
        if not isinstance(permitted, bool):
            raise TypeError("permitted must be a bool")
        if self._closed:
            return self._deny("closed")
        if not permitted:
            return self._deny("permission_denied")
        if (
            not isinstance(request, UploadRequest)
            or not isinstance(request.peer_id, str)
            or not 1 <= len(request.peer_id) <= 64
            or not _is_int(request.piece)
        ):
            return self._deny("invalid_request")
        if not 0 <= request.piece < len(self._manifest.pieces):
            return self._deny("unknown_piece")
        peer, piece = request.peer_id, request.piece
        if (peer, piece) in self._keys:
            return self._deny("duplicate")
        if self._peer_counts.get(peer, 0) >= self._cfg.max_jobs_per_peer:
            return self._deny("peer_limit")
        if len(self._jobs) >= self._cfg.max_jobs:
            return self._deny("global_limit")

        job = _Job(self._next_id, peer, piece, self._manifest.pieces[piece].length)
        self._next_id += 1
        self._jobs[job.job_id] = job
        self._keys[(peer, piece)] = job.job_id
        self._peer_counts[peer] = self._peer_counts.get(peer, 0) + 1
        queue = self._peer_queues.get(peer)
        if queue is None:
            queue = self._peer_queues[peer] = deque()
            self._rr.append(peer)
        queue.append(job)
        return Admission(True, job.job_id, None)

    # --------------------------------------------------------------- scheduling
    def tick(self, max_dispatch: int = 8) -> None:
        self._check_thread()
        if not _is_int(max_dispatch):
            raise TypeError("max_dispatch must be an integer")
        if max_dispatch <= 0:
            raise ValueError("max_dispatch must be positive")
        self._harvest()
        if self._closed:
            return
        self._dispatch(max_dispatch)

    def _affordable(self, length: int) -> bool:
        cfg = self._cfg
        return (
            self._out_slots < cfg.max_output_records
            and self._out_bytes + length <= cfg.max_output_bytes
            and self._read_bytes + length <= cfg.max_read_bytes
        )

    def _dispatch(self, budget: int) -> None:
        dispatched = 0
        while dispatched < budget and self._rr:
            if self._cfg.workers and len(self._running) >= self._cfg.workers:
                break
            chosen: Optional[_Job] = None
            # One pass: examine each queued peer at most once, preserving
            # their relative order when nobody can be served.
            for _ in range(len(self._rr)):
                peer = self._rr[0]
                head = self._peer_queues[peer][0]
                if self._affordable(head.length):
                    chosen = head
                    break
                self._rr.rotate(-1)
            if chosen is None:
                break  # nothing affordable now; do not spin
            peer = self._rr.popleft()
            queue = self._peer_queues[peer]
            queue.popleft()
            if queue:
                self._rr.append(peer)  # peer's turn consumed; go to the back
            else:
                del self._peer_queues[peer]
            self._start(chosen)
            dispatched += 1

    def _start(self, job: _Job) -> None:
        job.state = JobState.READING
        job.holds_slot = True
        self._out_slots += 1
        job.out_reserved = job.length
        self._out_bytes += job.length
        job.read_reserved = job.length
        self._read_bytes += job.length
        self._running[job.job_id] = job
        meta = self._manifest.pieces[job.piece]
        if self._executor is not None:
            job.future = self._executor.submit(_execute, self._source, meta)
            return
        try:
            data, reason = _execute(self._source, meta)
        except BaseException:
            self._complete(job, None, "source_error")
            raise
        self._complete(job, data, reason)

    def _harvest(self) -> None:
        pending: Optional[BaseException] = None
        for job in list(self._running.values()):
            fut = job.future
            if fut is None or not fut.done():
                continue
            exc = fut.exception()
            if exc is not None:  # BaseException escaped a worker; keep state sound
                self._complete(job, None, "source_error")
                pending = pending or exc
                continue
            data, reason = fut.result()
            self._complete(job, data, reason)
        if pending is not None:
            raise pending

    def _complete(self, job: _Job, data: Optional[bytes], reason: Optional[str]) -> None:
        self._running.pop(job.job_id, None)
        job.future = None
        self._read_bytes -= job.read_reserved
        job.read_reserved = 0
        if job.cancelled or self._closed:
            self._release(job)  # output suppressed; reservations end here
            return
        if reason is not None:
            self._out_bytes -= job.out_reserved  # rejection keeps only its slot
            job.out_reserved = 0
            job.output = RejectOutput(job.job_id, job.peer_id, reason)
            job.is_data = False
            self._source_failures += 1
        else:
            assert data is not None
            job.output = DataOutput(job.job_id, job.peer_id, job.piece, data)  # same bytes object
            job.is_data = True
            job.data_len = len(data)
        job.state = JobState.READY
        self._outbox[job.job_id] = job

    # ------------------------------------------------------------------- output
    def poll_outputs(self, limit: int = 16) -> tuple[Output, ...]:
        self._check_thread()
        if not _is_int(limit):
            raise TypeError("limit must be an integer")
        if limit <= 0:
            raise ValueError("limit must be positive")
        if self._closed:
            return ()
        out: list[Output] = []
        while self._outbox and len(out) < limit:
            _, job = self._outbox.popitem(last=False)
            job.state = JobState.DELIVERED
            assert job.output is not None
            out.append(job.output)
            job.output = None  # the caller now holds the record; reservations stay
        return tuple(out)

    def mark_sent(self, job_id: int, byte_count: int) -> str:
        self._check_thread()
        job = self._jobs.get(job_id) if _is_int(job_id) else None
        if self._closed or job is None:
            return "unknown_job"
        if job.state is not JobState.DELIVERED or not job.is_data:
            return "not_delivered"
        if not _is_int(byte_count) or byte_count != job.data_len:
            return "invalid_byte_count"
        self._sent_bytes += job.data_len
        self._sent_pieces += 1
        self._release(job)
        return "ok"

    def mark_failed(self, job_id: int) -> str:
        self._check_thread()
        job = self._jobs.get(job_id) if _is_int(job_id) else None
        if self._closed or job is None:
            return "unknown_job"
        if job.state is not JobState.DELIVERED:
            return "not_delivered"
        if job.is_data:
            self._failed_sends += 1
        self._release(job)
        return "ok"

    # ------------------------------------------------------------- cancellation
    def _cancel_job(self, job: _Job) -> tuple[str, bool]:
        """Return (result, newly_cancelled)."""
        if job.state is JobState.DELIVERED:
            return "too_late", False
        if job.state is JobState.READING:
            if job.cancelled:
                return "cancelled", False
            job.cancelled = True
            self._cancelled += 1
            key = (job.peer_id, job.piece)
            if self._keys.get(key) == job.job_id:
                del self._keys[key]  # a fresh request may be admitted meanwhile
            return "cancelled", True
        if job.state is JobState.QUEUED:
            self._dequeue(job)
        else:  # READY, undelivered
            self._outbox.pop(job.job_id, None)
        self._cancelled += 1
        self._release(job)
        return "cancelled", True

    def cancel(self, job_id: int) -> str:
        self._check_thread()
        job = self._jobs.get(job_id) if _is_int(job_id) else None
        if job is None:
            return "unknown_job"
        return self._cancel_job(job)[0]

    def cancel_peer(self, peer_id: str) -> int:
        self._check_thread()
        count = 0
        for job in [j for j in self._jobs.values() if j.peer_id == peer_id]:
            if self._cancel_job(job)[1]:
                count += 1
        return count

    # ----------------------------------------------------------------- snapshot
    def snapshot(self) -> Snapshot:
        self._check_thread()
        return Snapshot(
            active_jobs=len(self._jobs),
            queued_jobs=sum(len(q) for q in self._peer_queues.values()),
            reading_jobs=len(self._running),
            output_slots=self._out_slots,
            reserved_output_bytes=self._out_bytes,
            reserved_read_bytes=self._read_bytes,
            sent_bytes=self._sent_bytes,
            sent_pieces=self._sent_pieces,
            failed_sends=self._failed_sends,
            cancelled_jobs=self._cancelled,
            rejected_requests=self._rejected,
            source_failures=self._source_failures,
            closed=self._closed,
        )

    # ----------------------------------------------------------------- shutdown
    def shutdown(self, wait: bool = True) -> None:
        self._check_thread()
        if type(wait) is not bool:
            raise ValueError("wait must be a bool")
        if not self._closed:
            self._closed = True
            for job in list(self._jobs.values()):
                if job.state is JobState.READING:
                    self._cancel_job(job)  # flag + count once; kept until provider returns
                else:
                    self._cancelled += 1
                    self._release(job)
            self._peer_queues.clear()
            self._rr.clear()
            self._outbox.clear()
        if wait:
            futures = [j.future for j in self._running.values() if j.future is not None]
            if futures:
                concurrent.futures.wait(futures)
            self._harvest()
            if self._executor is not None:
                self._executor.shutdown(wait=True)
        elif self._executor is not None:
            self._executor.shutdown(wait=False)
