"""
Choking Manager — Prabhat's Module (P2 priority — implement after core works)

Decides which connected peers are choked/unchoked.

Concept:
    - By default, all peers start choked (we won't upload to them)
    - Periodically (every CHOKING_INTERVAL seconds), recalculate:
      - Unchoke the top-N peers who have uploaded the most to us (reciprocity)
      - Optionally: optimistic unchoke 1 random choked peer (give newcomers a chance)
    - Peers we choke will stop receiving PIECE responses from us
    - This incentivizes peers to upload (tit-for-tat)

Free-rider impact:
    A peer that never uploads will rarely be unchoked, so it
    downloads slowly. This is exactly what the experiment tests.

Interface:
    ChokingManager.recalculate(connections, upload_stats) -> dict[str, bool]
    ChokingManager.should_unchoke(peer_id) -> bool

THIS MODULE IS P2 PRIORITY.
Do NOT implement this before the core P2P transfer works.
"""

import threading
import random

from bittorrent_lite.config import UNCHOKE_SLOTS, OPTIMISTIC_UNCHOKE_INTERVAL


class ChokingManager:
    """
    Simplified choking/unchoking strategy.

    Unchokes the top-N peers by upload contribution,
    plus one optimistic unchoke slot.
    """

    def __init__(self, unchoke_slots: int = UNCHOKE_SLOTS):
        """
        Initialize choking manager.

        Args:
            unchoke_slots: Number of peers to unchoke simultaneously.
        """
        self.unchoke_slots = unchoke_slots
        self._unchoked_peers: set[str] = set()
        self._optimistic_peer: str | None = None
        self._lock = threading.Lock()

    def recalculate(self, peer_upload_rates: dict[str, float]) -> set[str]:
        """
        Recalculate which peers should be unchoked.

        Algorithm:
        1. Sort peers by upload rate (how much they've uploaded TO US)
        2. Unchoke the top unchoke_slots peers
        3. Randomly pick one additional peer for optimistic unchoking

        Args:
            peer_upload_rates: Dict of peer_id -> bytes/sec uploaded to us.

        Returns:
            Set of peer_ids that should be unchoked.
        """
        # TODO: Prabhat — implement this (P2 priority)
        raise NotImplementedError

    def get_unchoked_peers(self) -> set[str]:
        """Return the set of currently unchoked peer IDs."""
        with self._lock:
            return self._unchoked_peers.copy()

    def is_unchoked(self, peer_id: str) -> bool:
        """Check if a specific peer is currently unchoked."""
        with self._lock:
            return peer_id in self._unchoked_peers
