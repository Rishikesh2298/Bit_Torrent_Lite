"""
Tracker State — Debargha's Module

In-memory data structure that stores the swarm's state.
The tracker_server.py handles HTTP; this module handles the data.

Interface:
    TrackerState.register_peer(peer_id, ip, port) -> None
    TrackerState.update_peer(peer_id) -> None
    TrackerState.get_peer_list(exclude_peer_id) -> list[PeerInfo]
    TrackerState.remove_stale_peers(timeout_seconds) -> list[str]
    TrackerState.remove_peer(peer_id) -> None

Data model:
    Internally stores a dict:
    {
        "peer-001": {"ip": "127.0.0.1", "port": 9001, "last_seen": <timestamp>},
        "peer-002": {"ip": "127.0.0.1", "port": 9002, "last_seen": <timestamp>},
        ...
    }

Thread safety:
    Multiple peers may announce simultaneously (tracker handles concurrent HTTP).
    ALL methods that read or modify the peer dict MUST be protected by a lock.

Stale peer cleanup:
    A background thread should periodically call remove_stale_peers().
    If a peer hasn't announced within TRACKER_PEER_TIMEOUT seconds, remove it.
"""

import threading
import time
import math
from bittorrent_lite.types import PeerRecord as PeerInfo


class TrackerState:
    """
    Thread-safe in-memory storage for swarm membership.

    Attributes:
        _peers: Dict mapping peer_id -> peer record dict.
        _lock: Threading lock for safe concurrent access.
    """

    def __init__(self):
        """Initialize empty swarm state with a lock."""
        self._peers: dict = {}
        self._lock = threading.Lock()

    def register_peer(self, peer_id: str, ip: str, port: int) -> None:
        """
        Register a new peer or update an existing peer's last_seen time.

        Args:
            peer_id: Unique peer identifier.
            ip: Peer's IP address.
            port: Peer's listening port.
        """
        with self._lock:
            self._peers[peer_id] = {
                "ip": ip,
                "port": port,
                "last_seen": time.monotonic(),
            }

    def update_peer(self, peer_id: str) -> None:
        """
        Update a peer's last_seen timestamp (heartbeat).

        Args:
            peer_id: Peer to update.

        Raises:
            KeyError: If peer_id is not registered.
        """
        with self._lock:
            self._peers[peer_id]["last_seen"] = time.monotonic()

    def get_peer_list(self, exclude_peer_id: str = "") -> list[PeerInfo]:
        """
        Get list of all active peers, optionally excluding one.

        Args:
            exclude_peer_id: Peer to exclude (typically the requesting peer).

        Returns:
            List of PeerInfo for all other peers.
        """
        with self._lock:
            return [
                PeerInfo(peer_id=peer_id, ip=record["ip"], port=record["port"])
                for peer_id, record in self._peers.items()
                if peer_id != exclude_peer_id
            ]

    def remove_stale_peers(self, timeout_seconds: int) -> list[str]:
        """
        Remove peers that haven't announced within the timeout.

        Args:
            timeout_seconds: Max seconds since last_seen before removal.

        Returns:
            List of peer_ids that were removed.

        Raises:
            ValueError: If the timeout is not finite and nonnegative.
        """
        if (type(timeout_seconds) not in (int, float)
                or timeout_seconds < 0
                or (isinstance(timeout_seconds, float) and not math.isfinite(timeout_seconds))):
            raise ValueError("timeout_seconds must be finite and nonnegative")
        with self._lock:
            now = time.monotonic()
            stale = [
                peer_id for peer_id, record in self._peers.items()
                if now - record["last_seen"] > timeout_seconds
            ]
            for peer_id in stale:
                del self._peers[peer_id]
            return stale

    def remove_peer(self, peer_id: str) -> None:
        """
        Explicitly remove a peer (e.g., when it announces departure).

        Args:
            peer_id: Peer to remove.
        """
        with self._lock:
            self._peers.pop(peer_id, None)

    def peer_count(self) -> int:
        """Return the number of currently registered peers."""
        with self._lock:
            return len(self._peers)
