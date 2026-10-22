"""Owner-thread integration of bounded uploads and acknowledged choke policy."""
from collections import deque
from dataclasses import asdict
from queue import Full
import threading

from choking_policy import Config as ChokingConfig, PeerInfo, Policy
from upload_service import (UploadService, UploadConfig, UploadRequest, Manifest,
                            PieceMeta, DataOutput)
from bittorrent_lite.protocol import messages as msg
from .upload_policy import ProjectUploadPolicy


class FileStoreUploadSource:
    """Fresh bounded reads without mutating FileStore's owner-thread bitfield.

    Downloaded pieces are atomically replaced by FileStore; seed files must
    remain immutable. UploadService independently verifies length and hash.
    """
    def __init__(self, store):
        self.manifest = Manifest(tuple(
            PieceMeta(i, store.metadata.expected_piece_size(i), digest)
            for i, digest in enumerate(store.metadata.piece_hashes)))
        self._source = store.source_path
        self._root = store.pieces_dir.resolve()
        self._piece_size = store.metadata.piece_size

    def __call__(self, index):
        if type(index) is not int or not 0 <= index < len(self.manifest.pieces):
            raise ValueError("invalid piece index")
        length = self.manifest.pieces[index].length
        if self._source is not None:
            with open(self._source, "rb") as stream:
                stream.seek(index * self._piece_size)
                return stream.read(length)
        path = self._root / f"{index}.piece"
        if path.is_symlink() or path.resolve().parent != self._root:
            raise ValueError("piece path must stay inside storage")
        with open(path, "rb") as stream:
            return stream.read(length + 1)


class UploadController:
    """send(cid, message) enqueues; callbacks must carry the same message object.

    False/OSError/Full means nothing was queued. All other results mean queued.
    A send completion means the entire frame was written; partial/unknown writes
    must close the connection and call disconnect, never report success.
    """
    def __init__(self, store, send, clock, *, upload_config=None, choking_config=None,
                 withdraw=None, close=None):
        source = FileStoreUploadSource(store)
        self._num_pieces = len(source.manifest.pieces)
        self.policy = ProjectUploadPolicy(choking_config)
        self.service = UploadService(source.manifest, source, upload_config or UploadConfig())
        self._send = send
        self._clock = clock
        self._withdraw = withdraw or (lambda cid, message: False)
        self._close = close or (lambda cid, reason: None)
        self._owner = threading.get_ident()
        self._peers = {}  # connection -> policy peer identity
        self._last_request = {}  # active connection -> greatest admitted/seen request ID
        self._jobs = {}  # job -> (connection, wire request, piece)
        self._keys = {}  # exact wire identity -> job
        self._cancelled = set()  # reading jobs awaiting worker completion
        self._messages = {}  # id(message) -> (message, connection, kind, handle)
        self._problems = deque(maxlen=128)
        self._closed = False

    def _check(self):
        if threading.get_ident() != self._owner:
            raise RuntimeError("UploadController requires its owner thread")

    def connect(self, cid, peer_id):
        self._check()
        if type(cid) is not int or cid <= 0 or cid in self._peers:
            raise ValueError("invalid or duplicate connection")
        self.policy.connect(PeerInfo(peer_id), self._clock.now())
        self._peers[cid] = peer_id
        self._last_request[cid] = 0

    def interested(self, cid, interested):
        self._check()
        if cid in self._peers and not self._closed:
            self.policy.set_interested(self._peers[cid], interested, self._clock.now())

    def contribution(self, cid, byte_count):
        self._check()
        if cid in self._peers and not self._closed:
            self.policy.record_contribution(self._peers[cid], byte_count, self._clock.now())

    def set_seeder(self, value):
        self._check()
        if not self._closed:
            self.policy.set_seeder(value, self._clock.now())

    def set_upload_enabled(self, value):
        self._check()
        self.policy.set_upload_enabled(value, self._clock.now())
        self.tick()

    def _enqueue(self, cid, message):
        try:
            return self._send(cid, message) is not False
        except (OSError, Full):
            return False

    def _tracked_send(self, cid, message, kind, handle):
        self._messages[id(message)] = (message, cid, kind, handle)
        if not self._enqueue(cid, message):
            self.completed(cid, message, False)

    def _forget_job(self, job):
        key = self._jobs.pop(job, None)
        if key is not None:
            self._keys.pop(key, None)
        self._cancelled.discard(job)

    def _cancel_job(self, job):
        result = self.service.cancel(job)
        if result == "cancelled":
            # A cancelled worker keeps reservations until harvested. No private
            # service state is read: repeat cancellation is idempotent.
            if self.service.cancel(job) == "unknown_job":
                self._forget_job(job)
            else:
                self._cancelled.add(job)
        return result

    def request(self, cid, request_id, piece):
        self._check()
        if cid not in self._peers or self._closed:
            return
        if (type(request_id) is not int or request_id <= 0 or type(piece) is not int
                or not 0 <= piece < self._num_pieces):
            self._problems.append("invalid upload request identity")
            self._close(cid, "invalid upload request identity")
            self.disconnect(cid)
            return
        key = (cid, request_id, piece)
        if key in self._keys:
            return  # retransmission must not reject an already active request
        if request_id <= self._last_request[cid]:
            self._close(cid, "reused upload request ID")
            self.disconnect(cid)
            return
        self._last_request[cid] = request_id
        state = self.policy.snapshot(self._clock.now())
        peer = next(p for p in state.peers if p.peer_id == self._peers[cid])
        allowed = state.upload_enabled and peer.interested and peer.desired and peer.confirmed
        result = self.service.submit(UploadRequest(str(cid), piece), permitted=allowed)
        if not result.accepted:
            reason = ("choked" if not allowed else
                      "busy" if result.reason in ("peer_limit", "global_limit", "duplicate")
                      else "unavailable")
            self._enqueue(cid, msg.Reject(request_id, piece, reason))
            return
        self._jobs[result.job_id] = key
        self._keys[key] = result.job_id

    def cancel(self, cid, request_id, piece):
        self._check()
        if any(type(v) is not int for v in (cid, request_id, piece)):
            return
        job = self._keys.get((cid, request_id, piece))
        if job is not None:
            self._cancel_with_transport(job)

    def _cancel_with_transport(self, job):
        result = self._cancel_job(job)
        if result == "too_late":
            for _, (message, conn, kind, handle) in list(self._messages.items()):
                if kind == "job" and handle == job and self._withdraw(conn, message):
                    self.completed(conn, message, False)
                    return "cancelled"
        return result

    def tick(self, max_dispatch=8):
        self._check()
        if type(max_dispatch) is not int:
            raise TypeError("max_dispatch must be an integer")
        if max_dispatch <= 0:
            raise ValueError("max_dispatch must be positive")
        decision = self.policy.tick(self._clock.now())
        permitted = {p.peer_id for p in decision.state.peers
                     if p.interested and p.desired and p.confirmed}
        for job, (cid, rid, piece) in list(self._jobs.items()):
            if self._peers.get(cid) not in permitted:
                if job in self._cancelled:
                    continue
                result = self._cancel_with_transport(job)
                if result == "cancelled":
                    self._enqueue(cid, msg.Reject(rid, piece, "choked"))
        reverse = {pid: cid for cid, pid in self._peers.items()}
        for intent in decision.intents:
            message = msg.Unchoke() if intent.allow else msg.Choke()
            self._tracked_send(reverse[intent.peer_id], message, "permission", intent.token)
        self.service.tick(max_dispatch)
        for job in list(self._cancelled):
            if self.service.cancel(job) == "unknown_job":
                self._forget_job(job)
        for output in self.service.poll_outputs():
            cid, rid, piece = self._jobs[output.job_id]
            message = (msg.Piece(rid, piece, output.data) if isinstance(output, DataOutput)
                       else msg.Reject(rid, piece, "unavailable"))
            self._tracked_send(cid, message, "job", output.job_id)

    def completed(self, cid, message, applied):
        self._check()
        entry = self._messages.get(id(message))
        if entry is None or entry[0] is not message or entry[1] != cid:
            return
        if type(applied) is not bool:
            raise ValueError("applied must be a bool")
        _, _, kind, handle = self._messages.pop(id(message))
        if kind == "permission":
            self.policy.acknowledge(handle, applied, self._clock.now())
        else:
            if applied and isinstance(message, msg.Piece):
                self.service.mark_sent(handle, len(message.payload))
            else:
                self.service.mark_failed(handle)
            self._forget_job(handle)

    def disconnect(self, cid):
        self._check()
        pid = self._peers.pop(cid, None)
        if pid is None:
            return
        self.policy.disconnect(pid, self._clock.now())
        self._last_request.pop(cid, None)
        for identity, (message, conn, kind, handle) in list(self._messages.items()):
            if conn == cid:
                if kind == "job":
                    self.service.mark_failed(handle)
                    self._forget_job(handle)
                del self._messages[identity]
        for job, key in list(self._jobs.items()):
            if key[0] == cid:
                self._cancel_job(job)

    def snapshot(self):
        self._check()
        return {"service": asdict(self.service.snapshot()),
                "policy": asdict(self.policy.snapshot(self._clock.now())),
                "tracked_jobs": len(self._jobs), "pending_sends": len(self._messages),
                "problems": list(self._problems)}

    def shutdown(self, wait=True):
        """Close upload jobs; tick/ack still drive permission-denial handshake."""
        self._check()
        if type(wait) is not bool:
            raise ValueError("wait must be a bool")
        self._closed = True
        self.policy.shutdown(self._clock.now())
        self.service.shutdown(wait=wait)
        self._jobs.clear()
        self._keys.clear()
        self._cancelled.clear()
        self._messages = {k: v for k, v in self._messages.items() if v[2] == "permission"}
        self.tick()
