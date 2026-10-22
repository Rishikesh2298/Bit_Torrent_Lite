"""Project storage and protocol boundaries for the single-owner scheduler.

Worker threads call publish/received/sent/disconnected. Only the coordinator
owner calls drain and tick. Register a connection only after handshake validation.
The send callable must enqueue without calling the coordinator synchronously.
"""
from queue import Queue, Empty, Full
import hashlib
import time
import threading

from bittorrent_lite.networking import messages as msg
from bittorrent_lite.common import events as ev


class MonotonicClock:
    def now(self):
        return time.monotonic()


class FileStoreAdapter:
    def __init__(self, store):
        self.store = store
        self.last_verification = None

    def verified_bitfield(self):
        if self.store.source_path is not None:
            self.store.validate_source()
        return [self.store.has_piece(i) for i in range(self.store.metadata.num_pieces)]

    def verify_and_store(self, index, data):
        self.last_verification = None
        try:
            result = self.store.verify_and_store(index, data)
        except OSError as exc:
            self.last_verification = {"outcome": "local_io_error",
                                      "error_type": type(exc).__name__}
            raise
        if result:
            outcome = "stored"
        elif len(data) != self.store.metadata.expected_piece_size(index):
            outcome = "length_mismatch"
        elif hashlib.sha256(data).hexdigest() != self.store.metadata.piece_hashes[index]:
            outcome = "hash_mismatch"
        else:
            # A false result alone does not establish provider corruption.
            outcome = "store_rejected_unclassified"
        self.last_verification = {"outcome": outcome, "bytes": len(data)}
        return result

    def assemble_file(self, output_path):
        return self.store.assemble_file(output_path)


class SchedulerBridge:
    def __init__(self, clock=None, *, event_capacity=128, observe=None):
        if type(event_capacity) is not int or event_capacity <= 0:
            raise ValueError("event_capacity must be a positive integer")
        self.clock = clock or MonotonicClock()
        self.events = Queue(maxsize=event_capacity)
        self._senders = {}
        self._used_ids = set()
        self._withdrawers = {}
        self._closers = {}
        self._requests = {}
        self._closed = set()
        self._dead_ids = set()
        self._lock = threading.RLock()
        self._stopping = False
        self._observe = observe
        self._store_adapter = None

    def _record(self, event, **fields):
        if self._observe is not None:
            self._observe(event, **fields)

    def register(self, connection_id, peer_id, send, *, withdraw=None, close=None):
        """Owner-thread operation; IDs cannot be reused after disconnect."""
        if self._stopping:
            raise RuntimeError("bridge is stopped")
        if connection_id in self._used_ids:
            raise ValueError("connection ID already used")
        self._used_ids.add(connection_id)
        self._senders[connection_id] = send
        self._withdrawers[connection_id] = withdraw
        self._closers[connection_id] = close
        self.publish(ev.ConnectionReady(connection_id, peer_id))

    def publish(self, event):
        if self._stopping:
            return False
        try:
            self.events.put_nowait(event)
            return True
        except Full:
            self.close_connection(event.connection_id, "event queue full")
            return False

    def close_connection(self, cid, reason):
        """Close transport and retain a flag even when the event queue is full."""
        with self._lock:
            if cid not in self._senders or cid in self._closed:
                return
            self._closed.add(cid)
            close = self._closers.get(cid)
        if close is not None:
            close(reason)

    def withdraw(self, cid, message):
        """True only if the exact queued frame was removed before writer start."""
        callback = self._withdrawers.get(cid)
        return callback is not None and callback(message) is True

    def withdraw_request(self, cid, rid, piece):
        with self._lock:
            message = self._requests.pop((cid, rid, piece), None)
        return message is not None and self.withdraw(cid, message)

    def create_coordinator(self, store, *, scheduler_config=None,
                           upload_config=None, choking_config=None):
        """Owner-thread factory joining downloads, uploads and choke policy."""
        from bittorrent_lite.scheduling.coordinator import Coordinator
        from bittorrent_lite.scheduling.uploads import UploadController
        uploads = UploadController(store, self._send, self.clock,
                                   upload_config=upload_config, choking_config=choking_config,
                                   withdraw=self.withdraw, close=self.close_connection)
        try:
            self._store_adapter = FileStoreAdapter(store)
            return Coordinator(store.metadata.num_pieces, self, self._store_adapter,
                               self.clock, scheduler_config, uploads=uploads)
        except BaseException:
            uploads.shutdown()
            raise

    def _send(self, connection_id, message):
        if self._stopping or connection_id in self._closed:
            return False
        send = self._senders.get(connection_id)
        if send is None:
            return False
        try:
            # PeerConnection.send returns None on successful enqueue.
            return send(message) is not False
        except (OSError, Full):
            return False

    def send_request(self, connection_id, request_id, piece_index):
        message = msg.Request(request_id, piece_index)
        key = (connection_id, request_id, piece_index)
        with self._lock:
            self._requests[key] = message
        accepted = self._send(connection_id, message)
        if not accepted:
            with self._lock:
                self._requests.pop(key, None)
        return accepted

    def send_interest(self, connection_id, interested):
        return self._send(connection_id, msg.Interested() if interested else msg.NotInterested())

    def send_have(self, connection_id, piece_index):
        return self._send(connection_id, msg.Have(piece_index))

    def send_cancel(self, connection_id, request_id, piece_index):
        return self._send(connection_id, msg.Cancel(request_id, piece_index))

    def received(self, connection_id, message):
        """Called by a receiver callback; copy mutable payloads before queueing."""
        if isinstance(message, msg.Request):
            event = ev.UploadRequested(connection_id, message.request_id, message.piece_index)
        elif isinstance(message, msg.Cancel):
            event = ev.UploadCancelled(connection_id, message.request_id, message.piece_index)
        elif isinstance(message, msg.BitfieldMsg):
            event = ev.BitfieldReceived(connection_id, tuple(message.pieces))
        elif isinstance(message, msg.Have):
            event = ev.HaveReceived(connection_id, message.piece_index)
        elif isinstance(message, msg.Piece):
            event = ev.PieceReceived(connection_id, message.request_id,
                                     message.piece_index, bytes(message.payload))
        elif isinstance(message, msg.Reject):
            event = ev.RejectReceived(connection_id, message.request_id, message.piece_index)
        elif isinstance(message, (msg.Interested, msg.NotInterested)):
            event = ev.PeerInterestChanged(connection_id, isinstance(message, msg.Interested))
        elif isinstance(message, (msg.Choke, msg.Unchoke)):
            event = (ev.ChokeReceived if isinstance(message, msg.Choke)
                     else ev.UnchokeReceived)(connection_id)
        else:
            raise ValueError("message is not a scheduler event")
        self.publish(event)

    def sent(self, connection_id, message):
        """Call only after the socket write succeeds, never after enqueue."""
        if isinstance(message, msg.Request):
            with self._lock:
                self._requests.pop((connection_id, message.request_id, message.piece_index), None)
            self.publish(ev.RequestSent(connection_id, message.request_id,
                                        message.piece_index, self.clock.now()))
        elif isinstance(message, (msg.Piece, msg.Reject, msg.Choke, msg.Unchoke)):
            self.publish(ev.UploadSendCompleted(connection_id, message, True))

    def send_failed(self, connection_id, message, reason=""):
        if isinstance(message, msg.Request):
            with self._lock:
                self._requests.pop((connection_id, message.request_id, message.piece_index), None)
            self.publish(ev.RequestSendFailed(connection_id, message.request_id,
                                              message.piece_index, reason))
        elif isinstance(message, (msg.Piece, msg.Reject, msg.Choke, msg.Unchoke)):
            self.publish(ev.UploadSendCompleted(connection_id, message, False))

    def disconnected(self, connection_id):
        self.publish(ev.Disconnected(connection_id))

    def record_snapshot(self, coordinator, *, reason):
        """Owner-thread sample after a mutation; never a claim of OS resources."""
        if self._observe is None:
            return
        snap = coordinator.snapshot()
        self._record("SCHEDULER_SNAPSHOT", reason=reason,
                     event_queue_depth=self.events.qsize(),
                     event_queue_capacity=self.events.maxsize,
                     connected_peers=sum(n["active"] for n in snap["neighbors"].values()),
                     neighbors=snap["neighbors"], pending=snap["pending"],
                     pipeline_counters=snap["pipeline_counters"],
                     uploads=snap["uploads"], owned=snap["owned"])

    def _handle_event(self, coordinator, event):
        piece = isinstance(event, ev.PieceReceived) and self._observe is not None
        before = coordinator.snapshot() if piece else None
        if piece and self._store_adapter is not None:
            self._store_adapter.last_verification = None
        coordinator.handle_event(event)
        if piece:
            after = coordinator.snapshot()
            attempted = (self._store_adapter.last_verification
                         if self._store_adapter is not None else None)
            fields = {"connection_id": event.connection_id,
                      "request_id": event.request_id, "piece": event.piece_index,
                      "remote": before["neighbors"].get(event.connection_id, {}).get("peer_id")}
            if attempted is not None:
                self._record("PIECE_VERIFICATION", **fields, **attempted)
            if (0 <= event.piece_index < len(after["local_bitfield"])
                    and not before["local_bitfield"][event.piece_index]
                    and after["local_bitfield"][event.piece_index]):
                self._record("PIECE_VERIFIED", **fields, bytes=len(event.data))
            elif attempted is None:
                self._record("PIECE_IGNORED", **fields, bytes=len(event.data),
                             reason="no_storage_verification")
        self.record_snapshot(coordinator, reason=type(event).__name__)

    def drain(self, coordinator, limit=1000):
        """Process a bounded batch on the coordinator's owning thread."""
        with self._lock:
            closed = set(self._closed)
        for cid in closed:
            self._forget_connection(cid)
            self._handle_event(coordinator, ev.Disconnected(cid))
        count = 0
        while count < limit:
            try:
                event = self.events.get_nowait()
            except Empty:
                break
            count += 1
            if isinstance(event, ev.Disconnected):
                self._forget_connection(event.connection_id)
            elif event.connection_id in self._dead_ids:
                continue
            self._handle_event(coordinator, event)
        return count

    def _forget_connection(self, cid):
        with self._lock:
            self._dead_ids.add(cid)
            self._senders.pop(cid, None)
            self._withdrawers.pop(cid, None)
            self._closers.pop(cid, None)
            self._closed.discard(cid)
            for key in list(self._requests):
                if key[0] == cid:
                    del self._requests[key]

    def shutdown(self):
        """Close all registered sessions, attempting every closer even on error."""
        self._stopping = True
        errors = []
        for cid in list(self._senders):
            try:
                self.close_connection(cid, "shutdown")
            except Exception as exc:
                errors.append(f"{cid}: {type(exc).__name__}: {exc}")
            finally:
                self._forget_connection(cid)
        while True:
            try:
                self.events.get_nowait()
            except Empty:
                break
        return errors
