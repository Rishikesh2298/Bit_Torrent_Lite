"""
Simplified choking / unchoking manager for BitTorrent-Lite.

Responsibilities:
- Track peer interested state.
- Track peer choking state.
- Choke / unchoke peers.
- Track download performance.
- Select preferred peers.
- Support a simple optimistic unchoke.
- Provide state required for the free-rider experiment.

This module does not:
- Parse TCP data.
- Implement protocol messages.
- Select pieces.
- Read/write files.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class PeerChokeState:
    peer_id: Any
    interested: bool = False
    choked: bool = True
    downloaded_bytes: int = 0
    uploaded_bytes: int = 0
    last_update: float = 0.0

    @property
    def download_rate(self) -> float:
        """
        Approximate download rate.

        Returns bytes/second over the lifetime of the tracked state.
        """
        if self.last_update <= 0:
            return 0.0

        elapsed = time.monotonic() - self.last_update

        if elapsed <= 0:
            return 0.0

        return self.downloaded_bytes / elapsed


class ChokingManager:
    """
    Simplified BitTorrent choking manager.

    The manager maintains peer state and selects a limited number of
    preferred peers.

    By default:
        max_unchoked = 4

    This matches the simplified BitTorrent-Lite design and keeps the
    choking policy independent from the networking layer.
    """

    def __init__(
        self,
        *,
        max_unchoked: int = 4,
        optimistic_unchoke: bool = True,
    ):
        if not isinstance(max_unchoked, int):
            raise TypeError(
                "max_unchoked must be an integer"
            )

        if max_unchoked <= 0:
            raise ValueError(
                "max_unchoked must be positive"
            )

        self.max_unchoked = max_unchoked
        self.optimistic_unchoke = optimistic_unchoke

        self._peers: dict[Any, PeerChokeState] = {}
        self._lock = threading.RLock()

        self._optimistic_peer: Optional[Any] = None

    # ------------------------------------------------------------------
    # Peer management
    # ------------------------------------------------------------------

    def add_peer(
        self,
        peer_id: Any,
        *,
        interested: bool = False,
        choked: bool = True,
    ) -> None:
        with self._lock:
            if peer_id in self._peers:
                return

            self._peers[peer_id] = PeerChokeState(
                peer_id=peer_id,
                interested=interested,
                choked=choked,
                last_update=time.monotonic(),
            )

    def remove_peer(
        self,
        peer_id: Any,
    ) -> bool:
        with self._lock:
            if peer_id not in self._peers:
                return False

            self._peers.pop(peer_id)

            if self._optimistic_peer == peer_id:
                self._optimistic_peer = None

            return True

    def has_peer(
        self,
        peer_id: Any,
    ) -> bool:
        with self._lock:
            return peer_id in self._peers

    def peer_count(self) -> int:
        with self._lock:
            return len(self._peers)

    # ------------------------------------------------------------------
    # Interest state
    # ------------------------------------------------------------------

    def set_interested(
        self,
        peer_id: Any,
        interested: bool,
    ) -> None:
        with self._lock:
            self._require_peer(peer_id)

            self._peers[
                peer_id
            ].interested = bool(interested)

    def is_interested(
        self,
        peer_id: Any,
    ) -> bool:
        with self._lock:
            self._require_peer(peer_id)

            return self._peers[
                peer_id
            ].interested

    # ------------------------------------------------------------------
    # Choke state
    # ------------------------------------------------------------------

    def choke(
        self,
        peer_id: Any,
    ) -> None:
        with self._lock:
            self._require_peer(peer_id)

            self._peers[
                peer_id
            ].choked = True

            if self._optimistic_peer == peer_id:
                self._optimistic_peer = None

    def unchoke(
        self,
        peer_id: Any,
    ) -> None:
        with self._lock:
            self._require_peer(peer_id)

            self._peers[
                peer_id
            ].choked = False

    def is_choked(
        self,
        peer_id: Any,
    ) -> bool:
        with self._lock:
            self._require_peer(peer_id)

            return self._peers[
                peer_id
            ].choked

    # ------------------------------------------------------------------
    # Transfer statistics
    # ------------------------------------------------------------------

    def record_download(
        self,
        peer_id: Any,
        byte_count: int,
    ) -> None:
        if not isinstance(byte_count, int):
            raise TypeError(
                "byte_count must be an integer"
            )

        if byte_count < 0:
            raise ValueError(
                "byte_count cannot be negative"
            )

        with self._lock:
            self._require_peer(peer_id)

            self._peers[
                peer_id
            ].downloaded_bytes += byte_count

    def record_upload(
        self,
        peer_id: Any,
        byte_count: int,
    ) -> None:
        if not isinstance(byte_count, int):
            raise TypeError(
                "byte_count must be an integer"
            )

        if byte_count < 0:
            raise ValueError(
                "byte_count cannot be negative"
            )

        with self._lock:
            self._require_peer(peer_id)

            self._peers[
                peer_id
            ].uploaded_bytes += byte_count

    def downloaded_bytes(
        self,
        peer_id: Any,
    ) -> int:
        with self._lock:
            self._require_peer(peer_id)

            return self._peers[
                peer_id
            ].downloaded_bytes

    def uploaded_bytes(
        self,
        peer_id: Any,
    ) -> int:
        with self._lock:
            self._require_peer(peer_id)

            return self._peers[
                peer_id
            ].uploaded_bytes

    # ------------------------------------------------------------------
    # Preferred peer selection
    # ------------------------------------------------------------------

    def select_preferred_peers(
        self,
    ) -> list[Any]:
        """
        Select up to max_unchoked interested peers.

        Peers are ranked primarily by the amount of data they have
        downloaded from us.

        Higher download contribution receives preference.

        The optimistic peer, if present, is preserved when possible.
        """
        with self._lock:
            interested = [
                peer
                for peer in self._peers.values()
                if peer.interested
            ]

            interested.sort(
                key=lambda peer: (
                    peer.downloaded_bytes,
                    peer.peer_id,
                ),
                reverse=True,
            )

            selected = [
                peer.peer_id
                for peer in interested[
                    : self.max_unchoked
                ]
            ]

            if (
                self._optimistic_peer is not None
                and self._optimistic_peer in self._peers
                and self._optimistic_peer not in selected
                and len(selected) < self.max_unchoked
            ):
                selected.append(
                    self._optimistic_peer
                )

            return selected

    def apply_choking_policy(self) -> list[Any]:
        """
        Apply the preferred-peer policy.

        Returns the peer IDs that are unchoked.
        """
        with self._lock:
            selected = set(
                self.select_preferred_peers()
            )

            for peer_id, state in self._peers.items():
                if peer_id in selected:
                    state.choked = False
                else:
                    state.choked = True

            return list(selected)

    # ------------------------------------------------------------------
    # Optimistic unchoking
    # ------------------------------------------------------------------

    def set_optimistic_peer(
        self,
        peer_id: Optional[Any],
    ) -> None:
        with self._lock:
            if peer_id is not None:
                self._require_peer(peer_id)

            self._optimistic_peer = peer_id

    def optimistic_peer(
        self,
    ) -> Optional[Any]:
        with self._lock:
            return self._optimistic_peer

    def clear_optimistic_peer(
        self,
    ) -> None:
        with self._lock:
            self._optimistic_peer = None

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def unchoked_peers(self) -> list[Any]:
        with self._lock:
            return [
                peer_id
                for peer_id, state in self._peers.items()
                if not state.choked
            ]

    def choked_peers(self) -> list[Any]:
        with self._lock:
            return [
                peer_id
                for peer_id, state in self._peers.items()
                if state.choked
            ]

    def interested_peers(self) -> list[Any]:
        with self._lock:
            return [
                peer_id
                for peer_id, state in self._peers.items()
                if state.interested
            ]

    def peer_state(
        self,
        peer_id: Any,
    ) -> PeerChokeState:
        with self._lock:
            self._require_peer(peer_id)

            state = self._peers[
                peer_id
            ]

            return PeerChokeState(
                peer_id=state.peer_id,
                interested=state.interested,
                choked=state.choked,
                downloaded_bytes=state.downloaded_bytes,
                uploaded_bytes=state.uploaded_bytes,
                last_update=state.last_update,
            )

    def states(self) -> dict[Any, PeerChokeState]:
        with self._lock:
            return {
                peer_id: self.peer_state(peer_id)
                for peer_id in self._peers
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_peer(
        self,
        peer_id: Any,
    ) -> None:
        if peer_id not in self._peers:
            raise KeyError(
                f"Unknown peer: {peer_id!r}"
            )

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        with self._lock:
            self._peers.clear()
            self._optimistic_peer = None