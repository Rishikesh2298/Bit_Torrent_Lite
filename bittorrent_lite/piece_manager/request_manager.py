"""Request manager for BitTorrent-Lite.

Maintains a pipelined set of outstanding piece requests.

Version 1 requirement:
    Maximum pipeline window = 4 requests.

The RequestManager does not:
- read TCP data
- parse protocol frames
- choose pieces using rarest-first

It only manages outstanding requests and determines
when another request may be issued.
"""

from __future__ import annotations

import threading
from typing import Optional

from bittorrent_lite.protocol.messages import (
    Piece,
    Reject,
    Request,
)


DEFAULT_PIPELINE_WINDOW = 4


class RequestManager:
    """
    Manage outstanding piece requests.

    Each request is identified by request_id.

    A request remains outstanding until the corresponding
    PIECE or REJECT is received.
    """

    def __init__(
        self,
        pipeline_window: int = DEFAULT_PIPELINE_WINDOW,
    ):
        if not isinstance(
            pipeline_window,
            int,
        ):
            raise TypeError(
                "pipeline_window must be an integer"
            )

        if pipeline_window <= 0:
            raise ValueError(
                "pipeline_window must be greater than 0"
            )

        self.pipeline_window = pipeline_window

        self._next_request_id = 1

        self._outstanding: dict[
            int,
            int,
        ] = {}

        self._completed: set[int] = set()

        self._rejected: set[int] = set()

        self._lock = threading.RLock()

    # =========================================================
    # Request creation
    # =========================================================

    def create_request(self, piece_index: int) -> Optional["Request"]:
        """Create a new REQUEST if the pipeline has space.

        Returns:
            Request if a slot is available, None if the pipeline is full.
        """
        if not isinstance(piece_index, int):
            raise TypeError("piece_index must be an integer")
        if piece_index < 0:
            raise ValueError("piece_index cannot be negative")

        with self._lock:
            if len(self._outstanding) >= self.pipeline_window:
                return None

            request_id = self._next_request_id
            self._next_request_id += 1
            self._outstanding[request_id] = piece_index
            return Request(request_id=request_id, piece_index=piece_index)

    # =========================================================
    # Completion
    # =========================================================

    def handle_piece(self, piece: "Piece") -> bool:
        """Mark a request as completed.

        Returns True if the PIECE matched an outstanding request.
        """
        with self._lock:
            request_id = piece.request_id
            if request_id not in self._outstanding:
                return False
            if self._outstanding[request_id] != piece.piece_index:
                return False
            del self._outstanding[request_id]
            self._completed.add(request_id)
            return True

    # =========================================================
    # Rejection
    # =========================================================

    def handle_reject(self, reject: "Reject") -> bool:
        """Remove a rejected request from the outstanding pipeline.

        Returns True if the request was actually outstanding.
        """
        with self._lock:
            request_id = reject.request_id
            if request_id not in self._outstanding:
                return False
            del self._outstanding[request_id]
            self._rejected.add(request_id)
            return True

    # =========================================================
    # Queries
    # =========================================================

    @property
    def outstanding_count(self) -> int:
        with self._lock:
            return len(self._outstanding)

    @property
    def available_slots(self) -> int:
        with self._lock:
            return self.pipeline_window - len(self._outstanding)

    @property
    def completed_count(self) -> int:
        with self._lock:
            return len(self._completed)

    @property
    def rejected_count(self) -> int:
        with self._lock:
            return len(self._rejected)

    def is_outstanding(self, request_id: int) -> bool:
        with self._lock:
            return request_id in self._outstanding

    def piece_for_request(self, request_id: int) -> Optional[int]:
        with self._lock:
            return self._outstanding.get(request_id)

    def outstanding_requests(self) -> dict[int, int]:
        """Return a snapshot of outstanding request_id -> piece_index."""
        with self._lock:
            return dict(self._outstanding)

    # =========================================================
    # Reset / clear
    # =========================================================

    def clear(self) -> None:
        """Clear all outstanding requests."""
        with self._lock:
            self._outstanding.clear()

    def reset(self) -> None:
        """Reset all request state."""
        with self._lock:
            self._next_request_id = 1
            self._outstanding.clear()
            self._completed.clear()
            self._rejected.clear()