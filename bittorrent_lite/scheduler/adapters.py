"""Project storage and protocol boundaries for the single-owner scheduler.

Worker threads call publish/received/sent/disconnected. Only the coordinator
owner calls drain and tick. Register a connection only after handshake validation.
The send callable must enqueue without calling the coordinator synchronously.
"""
from queue import Queue, Empty, Full
import time

from bittorrent_lite.protocol import messages as msg
from . import events as ev


class MonotonicClock:
    def now(self):
        return time.monotonic()


class FileStoreAdapter:
    def __init__(self, store):
        self.store = store

    def verified_bitfield(self):
        if self.store.source_path is not None:
            self.store.validate_source()
        return [self.store.has_piece(i) for i in range(self.store.metadata.num_pieces)]

    def verify_and_store(self, index, data):
        return self.store.verify_and_store(index, data)


class SchedulerBridge:
    def __init__(self, clock=None):
        self.clock = clock or MonotonicClock()
        self.events = Queue()
        self._senders = {}
        self._used_ids = set()

    def register(self, connection_id, peer_id, send):
        """Owner-thread operation; IDs cannot be reused after disconnect."""
        if connection_id in self._used_ids:
            raise ValueError("connection ID already used")
        self._used_ids.add(connection_id)
        self._senders[connection_id] = send
        self.publish(ev.ConnectionReady(connection_id, peer_id))

    def publish(self, event):
        self.events.put(event)

    def _send(self, connection_id, message):
        send = self._senders.get(connection_id)
        if send is None:
            return False
        try:
            # PeerConnection.send returns None on successful enqueue.
            return send(message) is not False
        except (OSError, Full):
            return False

    def send_request(self, connection_id, request_id, piece_index):
        return self._send(connection_id, msg.Request(request_id, piece_index))

    def send_interest(self, connection_id, interested):
        return self._send(connection_id, msg.Interested() if interested else msg.NotInterested())

    def send_have(self, connection_id, piece_index):
        return self._send(connection_id, msg.Have(piece_index))

    def received(self, connection_id, message):
        """Called by a receiver callback; copy mutable payloads before queueing."""
        if isinstance(message, msg.BitfieldMsg):
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
            raise ValueError("message is not a download-scheduler event")
        self.publish(event)

    def sent(self, connection_id, message):
        """Call only after the socket write succeeds, never after enqueue."""
        if isinstance(message, msg.Request):
            self.publish(ev.RequestSent(connection_id, message.request_id,
                                        message.piece_index, self.clock.now()))

    def send_failed(self, connection_id, message, reason=""):
        if isinstance(message, msg.Request):
            self.publish(ev.RequestSendFailed(connection_id, message.request_id,
                                              message.piece_index, reason))

    def disconnected(self, connection_id):
        self.publish(ev.Disconnected(connection_id))

    def drain(self, coordinator, limit=1000):
        """Process a bounded batch on the coordinator's owning thread."""
        count = 0
        while count < limit:
            try:
                event = self.events.get_nowait()
            except Empty:
                break
            if isinstance(event, ev.Disconnected):
                self._senders.pop(event.connection_id, None)
            coordinator.handle_event(event)
            count += 1
        return count
