"""Real TCP/discovery backend joining the four members' existing components."""
import queue
import threading
import time
from urllib.parse import urlsplit

from bittorrent_lite.application.runtime import Candidate, Session
from bittorrent_lite.common.config import HANDSHAKE_TIMEOUT, MAX_CONNECTIONS
from bittorrent_lite.discovery.tracker_client import DiscoveryWorker, PeersDiscovered, PEER_ID_RE
from bittorrent_lite.networking.network import PeerNetwork
from bittorrent_lite.networking.runtime_connection import RuntimeConnection


def validate_network_inputs(args, metadata):
    """Validate local network configuration without creating sockets or workers."""
    if not PEER_ID_RE.fullmatch(args.peer_id):
        raise ValueError('network peer ID must use 1-32 letters, digits, underscores or hyphens')
    url = urlsplit(args.tracker)
    if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
        raise ValueError('tracker must be an HTTP(S) URL without credentials')
    if url.port is not None and not 1 <= url.port <= 65535:
        raise ValueError('tracker port must be between 1 and 65535')
    if metadata.piece_size > 65536:
        raise ValueError('network piece size cannot exceed 65536 bytes')


class NetworkBackend:
    def __init__(self, args, metadata, file_id):
        validate_network_inputs(args, metadata)
        self.args, self.metadata, self.file_id = args, metadata, file_id
        self.runtime = None
        self.discovery = None
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._connections = {}
        self._next_id = 1
        self._local = threading.local()
        self._attempts = queue.Queue(maxsize=MAX_CONNECTIONS)
        self._events = queue.Queue(maxsize=32)
        self._threads = []
        self.network = PeerNetwork(host=getattr(args, 'host', '0.0.0.0'), port=args.port,
                                   connection_factory=self._connection)

    def _connection(self, sock, message_callback, disconnect_callback, piece_handler):
        with self._lock:
            if self._stop.is_set() or sum(not c.closed for c in self._connections.values()) >= MAX_CONNECTIONS:
                sock.close()
                raise ConnectionError('backend stopped or connection limit reached')
            connection = RuntimeConnection(
                sock, peer_id=self.args.peer_id, file_id=self.file_id,
                bitfield=self.runtime.advertised_bitfield, ready=self._ready,
                event=self._event, disconnected=disconnect_callback,
                expected_peer=getattr(self._local, 'peer_id', None))
            connection.connection_id = self._next_id
            self._next_id += 1
            self._connections[connection.connection_id] = connection
            return connection

    def _ready(self, connection):
        self.runtime.publish_session(Session(
            connection.connection_id, connection.remote_peer_id, tuple(connection.remote_bitfield),
            connection.send, connection.withdraw, lambda reason: connection.close(),
            tuple(connection.local_bitfield), connection.activate))

    def _event(self, connection, kind, message):
        bridge, cid = self.runtime.bridge, connection.connection_id
        if kind == 'disconnected':
            bridge.disconnected(cid)
        else:
            getattr(bridge, kind)(cid, message)

    def start(self, runtime):
        self.runtime = runtime
        self.network.start()
        self.discovery = DiscoveryWorker(self.args.tracker, self.file_id, self.args.peer_id,
                                         self.network.bound_port, self._events, http_timeout=1)
        for target, name in ((self._supervise, 'backend-events'), (self._connect_loop, 'backend-connect')):
            thread = threading.Thread(target=target, name=name, daemon=True)
            self._threads.append(thread)
            thread.start()
        self.discovery.start()

    def connect(self, candidate):
        if self._stop.is_set():
            return False
        try:
            self._attempts.put_nowait(candidate)
            return True
        except queue.Full:
            return False

    def _connect_loop(self):
        while not self._stop.is_set():
            try:
                candidate = self._attempts.get(timeout=.1)
            except queue.Empty:
                continue
            self._local.peer_id = candidate.peer_id
            try:
                self.network.connect(candidate.ip, candidate.port, timeout=.5)
            except (OSError, ValueError) as exc:
                self.runtime.publish_tracker_error(f'connect {candidate.peer_id}: {exc}')

    def _supervise(self):
        pending = None
        try:
            while not self._stop.wait(.05):
                try:
                    event = self._events.get_nowait()
                    if isinstance(event, PeersDiscovered):
                        pending = tuple(Candidate(p.peer_id, p.ip, p.port) for p in event.peers[:128])
                    else:
                        self.runtime.publish_tracker_error(f'{event.category}: {event.detail}')
                except queue.Empty:
                    pass
                if pending is not None and self.runtime.publish_candidates(pending):
                    pending = None
                with self._lock:
                    for cid, connection in list(self._connections.items()):
                        if not connection.bitfield_received and time.monotonic() - connection.created_at > HANDSHAKE_TIMEOUT:
                            connection.close()
                        if connection.closed and not connection.workers_alive():
                            del self._connections[cid]
        finally:
            self.network.stop()

    def completed(self):
        self.discovery.mark_completed()

    def stop(self):
        self._stop.set()
        if self.discovery is not None:
            self.discovery.stop(join_timeout=0)
        with self._lock:
            for connection in self._connections.values():
                connection.close()
        if not self._threads:
            self.network.stop()

    def join(self, timeout):
        deadline = time.monotonic() + timeout
        for thread in self._threads:
            thread.join(max(0, deadline - time.monotonic()))
        if self.discovery is not None:
            self.discovery.stop(join_timeout=max(0, deadline - time.monotonic()))
        with self._lock:
            connections = list(self._connections.values())
        for connection in connections:
            connection.close()
            connection.join(max(0, deadline - time.monotonic()))
        return (not any(t.is_alive() for t in self._threads)
                and not any(c.workers_alive() for c in connections)
                and (self.discovery is None or not self.discovery.is_alive()))
