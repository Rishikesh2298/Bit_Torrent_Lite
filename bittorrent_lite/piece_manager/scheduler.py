
"""
Download scheduler for BitTorrent-Lite.

Responsibilities:
- Maintain peer piece availability.
- Select rarest pieces.
- Send requests through PeerConnection.
- Track outstanding scheduler requests.
- Handle completed, rejected, and failed requests.
- Release reservations when peers disconnect.
- Integrate HAVE messages with PiecePicker.
"""

from __future__ import annotations

import threading
from typing import Any, Optional

from bittorrent_lite.peer.connection import PeerConnection
from bittorrent_lite.piece_manager.piece_picker import PiecePicker


class DownloadScheduler:
    def __init__(
        self,
        piece_count: int,
        *,
        local_pieces: Optional[list[int]] = None,
        auto_pipeline: bool = True,
    ) -> None:
        if isinstance(piece_count, bool) or not isinstance(piece_count, int):
            raise TypeError("piece_count must be an integer")
        if piece_count <= 0:
            raise ValueError("piece_count must be positive")

        self.piece_picker = PiecePicker(
            piece_count=piece_count,
            local_pieces=local_pieces,
        )
        self._connections: dict[Any, PeerConnection] = {}
        self._requests: dict[int, tuple[Any, int]] = {}
        self._lock = threading.RLock()
        self.auto_pipeline = auto_pipeline

    def add_peer(
        self,
        peer_id: Any,
        connection: PeerConnection,
        pieces: Optional[list[int]] = None,
        *,
        attach_callbacks: bool = True,
    ) -> None:
        with self._lock:
            self._connections[peer_id] = connection

            # Register the peer first, then add advertised piece indices.
            self.piece_picker.add_peer(peer_id)

            if pieces is not None:
                for piece_index in pieces:
                    self.piece_picker.add_peer_piece(
                        peer_id,
                        piece_index,
                    )

            if attach_callbacks:
                self._attach_callbacks(peer_id, connection)

    def remove_peer(self, peer_id: Any) -> None:
        with self._lock:
            self._connections.pop(peer_id, None)
            self.piece_picker.remove_peer(peer_id)

            stale_ids = [
                request_id
                for request_id, (request_peer, _) in self._requests.items()
                if request_peer == peer_id
            ]

            for request_id in stale_ids:
                _, piece_index = self._requests.pop(request_id)
                self.piece_picker.release(piece_index)

    def peer_count(self) -> int:
        with self._lock:
            return len(self._connections)

    def update_peer_pieces(
        self,
        peer_id: Any,
        pieces: list[int],
    ) -> None:
        with self._lock:
            self.piece_picker.remove_peer(peer_id)
            self.piece_picker.add_peer(peer_id)

            for piece_index in pieces:
                self.piece_picker.add_peer_piece(
                    peer_id,
                    piece_index,
                )

    def add_peer_piece(self, peer_id: Any, piece_index: int) -> None:
        with self._lock:
            self.piece_picker.add_peer_piece(peer_id, piece_index)

    def remove_peer_piece(self, peer_id: Any, piece_index: int) -> None:
        with self._lock:
            self.piece_picker.remove_peer_piece(peer_id, piece_index)

    def _attach_callbacks(self, peer_id: Any, connection: PeerConnection) -> None:
        callbacks = getattr(connection, "callbacks", None)

        if not isinstance(callbacks, dict):
            return

        old_piece = callbacks.get("on_piece")
        old_reject = callbacks.get("on_reject")
        old_have = callbacks.get("on_have")

        def on_piece(conn, message):
            if old_piece is not None:
                self._invoke_callback(old_piece, conn, message)

            self.piece_received(message.request_id, message.piece_index)

            if self.auto_pipeline:
                self.fill_pipeline()

        def on_reject(conn, message):
            if old_reject is not None:
                self._invoke_callback(old_reject, conn, message)

            self.request_rejected(message.request_id)

            if self.auto_pipeline:
                self.fill_pipeline()

        def on_have(conn, message):
            if old_have is not None:
                self._invoke_callback(old_have, conn, message)

            self.add_peer_piece(peer_id, message.piece_index)

            if self.auto_pipeline:
                self.fill_pipeline()

        callbacks["on_piece"] = on_piece
        callbacks["on_reject"] = on_reject
        callbacks["on_have"] = on_have

    @staticmethod
    def _invoke_callback(callback, connection, message) -> None:
        try:
            callback(connection, message)
        except TypeError as first_error:
            try:
                callback(message)
            except TypeError:
                raise first_error

    def _find_peer_for_piece(self, piece_index: int) -> Optional[Any]:
        for peer_id in self.piece_picker.peers_for_piece(piece_index):
            if peer_id in self._connections:
                return peer_id

        return None

    def schedule_one(self) -> Optional[int]:
        with self._lock:
            piece_index = self.piece_picker.pick_piece()

            if piece_index is None:
                return None

            peer_id = self._find_peer_for_piece(piece_index)

            if peer_id is None:
                self.piece_picker.release(piece_index)
                return None

            connection = self._connections[peer_id]

            try:
                request = connection.send_request(piece_index)
            except (ConnectionError, OSError, StopIteration):
                self.piece_picker.release(piece_index)
                return None

            if request is None:
                self.piece_picker.release(piece_index)
                return None

            request_id = getattr(request, "request_id", None)

            if request_id is None:
                self.piece_picker.release(piece_index)
                return None

            self._requests[request_id] = (peer_id, piece_index)

            return piece_index

    def fill_pipeline(self) -> list[int]:
        scheduled: list[int] = []

        while True:
            piece_index = self.schedule_one()

            if piece_index is None:
                break

            scheduled.append(piece_index)

        return scheduled

    def piece_received(self, request_id: int, piece_index: int) -> bool:
        with self._lock:
            info = self._requests.get(request_id)

            if info is None:
                return False

            _, expected_piece = info

            if expected_piece != piece_index:
                return False

            self._requests.pop(request_id)
            self.piece_picker.piece_completed(piece_index)

            return True

    def request_rejected(self, request_id: int) -> bool:
        with self._lock:
            info = self._requests.pop(request_id, None)

            if info is None:
                return False

            _, piece_index = info
            self.piece_picker.release(piece_index)

            return True

    def request_failed(self, request_id: int) -> bool:
        return self.request_rejected(request_id)

    @property
    def is_complete(self) -> bool:
        return self.piece_picker.is_complete

    @property
    def completed_count(self) -> int:
        return self.piece_picker.completed_count

    @property
    def remaining_count(self) -> int:
        return self.piece_picker.remaining_count

    @property
    def outstanding_request_count(self) -> int:
        with self._lock:
            total = 0

            for connection in self._connections.values():
                try:
                    total += connection.outstanding_request_count
                except (AttributeError, TypeError):
                    pass

            return total

    def pending_requests(self) -> dict[int, tuple[Any, int]]:
        with self._lock:
            return dict(self._requests)

    def local_pieces(self) -> set[int]:
        return set(self.piece_picker.local_pieces)

    def reserved_pieces(self) -> set[int]:
        return set(self.piece_picker.reserved_pieces)

    def reset(self) -> None:
        with self._lock:
            self._requests.clear()
            self.piece_picker.reset()
