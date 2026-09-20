"""
Tracker State — Debargha's Module

In-memory data structure that stores the swarm's state.
The tracker_server.py handles HTTP; this module handles the data.

Interface:
    TrackerState.register_peer(peer_id, ip, port) -> None
    TrackerState.update_peer(peer_id, bitfield) -> None
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
from bittorrent_lite.types import PeerInfo


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
        # TODO: Debargha — implement this
        raise NotImplementedError

    def update_peer(self, peer_id: str) -> None:
        """
        Update a peer's last_seen timestamp (heartbeat).

        Args:
            peer_id: Peer to update.

        Raises:
            KeyError: If peer_id is not registered.
        """
        # TODO: Debargha — implement this
        raise NotImplementedError

    def get_peer_list(self, exclude_peer_id: str = "") -> list[PeerInfo]:
        """
        Get list of all active peers, optionally excluding one.

        Args:
            exclude_peer_id: Peer to exclude (typically the requesting peer).

        Returns:
            List of PeerInfo for all other peers.
        """
        # TODO: Debargha — implement this
        raise NotImplementedError

    def remove_stale_peers(self, timeout_seconds: int) -> list[str]:
        """
        Remove peers that haven't announced within the timeout.

        Args:
            timeout_seconds: Max seconds since last_seen before removal.

        Returns:
            List of peer_ids that were removed.
        """
        # TODO: Debargha — implement this
        raise NotImplementedError

    def remove_peer(self, peer_id: str) -> None:
        """
        Explicitly remove a peer (e.g., when it announces departure).

        Args:
            peer_id: Peer to remove.
        """
        # TODO: Debargha — implement this
        raise NotImplementedError

    def peer_count(self) -> int:
        """Return the number of currently registered peers."""
        # TODO: Debargha — implement this
        raise NotImplementedError
