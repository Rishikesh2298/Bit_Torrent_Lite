"""Scheduler transport adapter; preserves PeerConnection's standalone API."""
from collections import deque
import queue
import socket
import threading
import time

from bittorrent_lite.common.config import PROTOCOL_VERSION
from bittorrent_lite.common import run_log
from bittorrent_lite.discovery.tracker_client import PEER_ID_RE
from bittorrent_lite.networking.connection import PeerConnection
from bittorrent_lite.networking.framing import send_message, recv_message
from bittorrent_lite.networking import messages as m


class _CountedSocket:
    """Count bytes actually supplied/returned by this frame's socket calls.

    A failed sendall exposes no partial-byte count. Its caller must leave the
    failed frame's transmitted bytes unknown, regardless of this accumulator.
    """
    def __init__(self, sock):
        self.sock = sock
        self.bytes = 0

    def sendall(self, data):
        self.sock.sendall(data)
        self.bytes += len(data)

    def recv(self, size):
        data = self.sock.recv(size)
        self.bytes += len(data)
        return data


class RuntimeConnection(PeerConnection):
    """One bounded writer; only the owner-thread scheduler makes policy decisions."""

    def __init__(self, sock, *, peer_id, file_id, bitfield, ready, event,
                 disconnected, expected_peer=None, capacity=64):
        super().__init__(sock, local_handshake=m.Handshake(PROTOCOL_VERSION, file_id, peer_id),
                         expected_file_id=file_id, expected_protocol_version=PROTOCOL_VERSION,
                         require_handshake=True, local_bitfield=list(bitfield),
                         on_disconnect=self._ended)
        self._writer_queue = queue.Queue(maxsize=capacity)
        self._handoff_lock = threading.RLock()
        self._pending = deque()
        self._active = False
        self._ready = ready
        self._event = event
        self._disconnected = disconnected
        self._expected_peer = expected_peer
        self._own_peer = peer_id
        self._capacity = capacity
        self.created_at = time.monotonic()

    def _frame_fields(self, message):
        def endpoint(method):
            try:
                return list(getattr(self.sock, method)())
            except (AttributeError, OSError, TypeError):
                return None
        return {"connection_id": getattr(self, "connection_id", None),
                "remote": self.remote_peer_id,
                "expected_remote": self._expected_peer,
                "local_endpoint": endpoint("getsockname"),
                "remote_endpoint": endpoint("getpeername"),
                "message_type": getattr(message, "type", None),
                "request_id": getattr(message, "request_id", None),
                "piece": getattr(message, "piece_index", None),
                "payload_bytes": (len(message.payload)
                                  if isinstance(message, m.Message) else None)}

    def _queue_sample(self, reason):
        run_log.emit("writer_queue", connection_id=getattr(self, "connection_id", None),
                     remote=self.remote_peer_id, reason=reason,
                     depth=self._writer_queue.qsize(), capacity=self._capacity)

    def activate(self):
        """Owner calls after bridge registration; preserve early event ordering."""
        with self._handoff_lock:
            self._active = True
            while self._pending:
                self._event(self, *self._pending.popleft())

    def _forward(self, kind, message=None):
        with self._handoff_lock:
            if self._active:
                self._event(self, kind, message)
            elif len(self._pending) < self._capacity:
                self._pending.append((kind, message))
            else:
                self._pending.clear()
                self._pending.append(('disconnected', None))
                self.close()

    def _ended(self, connection, reason=None):
        self._disconnected(self, reason)
        self._forward('disconnected')

    def _validate_handshake(self, handshake):
        super()._validate_handshake(handshake)
        if (self.handshake_received or not PEER_ID_RE.fullmatch(handshake.peer_id)
                or handshake.peer_id == self._own_peer
                or (self._expected_peer is not None and handshake.peer_id != self._expected_peer)):
            raise ValueError('invalid, duplicate or unexpected peer identity')

    def _send_local_bitfield_if_needed(self):
        with self._state_lock:
            if not self.bitfield_sent:
                self.bitfield_sent = True
                self.send(m.BitfieldMsg(list(self.local_bitfield)))

    def _dispatch_message(self, message):
        if isinstance(message, m.Handshake):
            self._handle_handshake(message)
            return
        if not self.handshake_complete:
            raise ValueError('message before handshake')
        if not self.bitfield_received:
            if not isinstance(message, m.BitfieldMsg) or len(message.pieces) != len(self.local_bitfield):
                raise ValueError('expected initial bitfield with metadata piece count')
            self.remote_bitfield = list(message.pieces)
            self.bitfield_received = True
            self._ready(self)
            return
        if isinstance(message, m.BitfieldMsg):
            raise ValueError('duplicate initial bitfield')
        if hasattr(message, 'piece_index') and not 0 <= message.piece_index < len(self.local_bitfield):
            raise ValueError('piece index outside metadata')
        self._forward('received', message)

    def send(self, message):
        with self._state_lock:
            if self._closed or not self._running:
                raise ConnectionError('transport is not running')
            if not isinstance(message, m.Handshake) and not self.handshake_complete:
                raise ConnectionError('send before handshake')
            self._writer_queue.put_nowait(message)
        self._queue_sample("enqueue")

    def withdraw(self, message):
        # Queue.get uses the same mutex: removal succeeds only before writer start.
        with self._writer_queue.mutex:
            for index, queued in enumerate(self._writer_queue.queue):
                if queued is message:
                    del self._writer_queue.queue[index]
                    self._writer_queue.not_full.notify()
                    removed = True
                    break
            else:
                removed = False
        if removed:
            self._queue_sample("withdraw")
        return removed

    def _reader_loop(self):
        """Keep the standalone reader's lifecycle, with actual byte provenance."""
        try:
            while self.running and not self.closed:
                counted = _CountedSocket(self.sock)
                try:
                    message = recv_message(counted)
                except socket.timeout:
                    continue
                except (EOFError, ConnectionError, OSError, ValueError) as exc:
                    run_log.emit("frame_receive_failed",
                                 connection_id=getattr(self, "connection_id", None),
                                 remote=self.remote_peer_id,
                                 received_bytes=counted.bytes,
                                 error_type=type(exc).__name__)
                    break
                if message is None:
                    break
                run_log.emit("frame_received", **self._frame_fields(message),
                             frame_bytes=counted.bytes, frame_complete=True)
                try:
                    self._dispatch_message(message)
                except (ValueError, TypeError, RuntimeError, ConnectionError) as exc:
                    run_log.emit("frame_rejected", **self._frame_fields(message),
                                 error_type=type(exc).__name__)
                    break
        finally:
            self.close()

    def _writer_loop(self):
        while not self.closed:
            try:
                message = self._writer_queue.get(timeout=.2)
            except queue.Empty:
                continue
            if message is None:
                break
            self._queue_sample("writer_start")
            counted = _CountedSocket(self.sock)
            try:
                send_message(counted, message)
            except (OSError, ValueError, TypeError) as exc:
                run_log.emit("frame_send_failed", **self._frame_fields(message),
                             frame_bytes=None, partial_bytes_known=False,
                             error_type=type(exc).__name__)
                self._forward('send_failed', message)
                self.close()
                break
            run_log.emit("frame_sent", **self._frame_fields(message),
                         frame_bytes=counted.bytes, frame_complete=True)
            if not isinstance(message, (m.Handshake, m.BitfieldMsg)):
                self._forward('sent', message)
            if isinstance(message, m.Piece):
                run_log.emit('piece_uploaded', piece=message.piece_index,
                             request_id=message.request_id,
                             connection_id=getattr(self, "connection_id", None),
                             bytes=len(message.payload), to=self.remote_peer_id)

    def workers_alive(self):
        return any(t is not None and t.is_alive() for t in (self._reader_thread, self._writer_thread))
