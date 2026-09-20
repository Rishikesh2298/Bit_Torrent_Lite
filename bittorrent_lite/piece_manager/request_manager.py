"""
Request Manager — Prabhat's Module

Tracks outstanding piece requests to prevent duplicates,
enforce pipelining limits, and detect timeouts.

Concept:
    When a peer sends a REQUEST for piece 7 to peer-003:
    - Record: {piece_index=7, peer_id="peer-003", timestamp=now()}
    - This prevents requesting piece 7 from another peer simultaneously
    - If peer-003 doesn't respond within REQUEST_TIMEOUT, the request
      can be cancelled and re-issued to a different peer

Pipelining:
    Initially: MAX_OUTSTANDING_REQUESTS = 1 (one request at a time)
    Later:     MAX_OUTSTANDING_REQUESTS = 5 (5 concurrent requests)

Interface:
    RequestManager.add_request(piece_index, peer_id) -> bool
    RequestManager.complete_request(piece_index) -> None
    RequestManager.cancel_request(piece_index) -> None
    RequestManager.get_timed_out_requests(timeout) -> list[int]
    RequestManager.is_requested(piece_index) -> bool
    RequestManager.can_request_more() -> bool
    RequestManager.outstanding_count() -> int
"""

import threading
import time

from bittorrent_lite.config import MAX_OUTSTANDING_REQUESTS, REQUEST_TIMEOUT


class RequestManager:
    """
    Tracks outstanding piece requests with timeout detection.

    Thread-safe: multiple connection threads may check/modify requests.
    """

    def __init__(self, max_outstanding: int = MAX_OUTSTANDING_REQUESTS):
        """
        Initialize request manager.

        Args:
            max_outstanding: Maximum concurrent outstanding requests.
        """
        self.max_outstanding = max_outstanding
        # piece_index -> {"peer_id": str, "timestamp": float}
        self._requests: dict[int, dict] = {}
        self._lock = threading.Lock()

    def add_request(self, piece_index: int, peer_id: str) -> bool:
        """
        Record a new outstanding request.

        Args:
            piece_index: The piece being requested.
            peer_id: The peer the request was sent to.

        Returns:
            True if the request was recorded, False if already requested
            or at the pipelining limit.
        """
        # TODO: Prabhat — implement this
        raise NotImplementedError

    def complete_request(self, piece_index: int) -> None:
        """
        Remove a request after successfully receiving the piece.

        Args:
            piece_index: The piece that was received.
        """
        # TODO: Prabhat — implement this
        raise NotImplementedError

    def cancel_request(self, piece_index: int) -> None:
        """
        Cancel an outstanding request (timeout, peer disconnect, etc.).

        Args:
            piece_index: The piece request to cancel.
        """
        # TODO: Prabhat — implement this
        raise NotImplementedError

    def get_timed_out_requests(self, timeout_seconds: float = REQUEST_TIMEOUT) -> list[int]:
        """
        Find requests that have been outstanding longer than the timeout.

        Args:
            timeout_seconds: Max seconds before a request is considered timed out.

        Returns:
            List of piece indices with timed-out requests.
        """
        # TODO: Prabhat — implement this
        raise NotImplementedError

    def is_requested(self, piece_index: int) -> bool:
        """Check if a piece is currently being requested."""
        # TODO: Prabhat — implement this
        raise NotImplementedError

    def can_request_more(self) -> bool:
        """Check if we're below the pipelining limit."""
        # TODO: Prabhat — implement this
        raise NotImplementedError

    def outstanding_count(self) -> int:
        """Return the number of currently outstanding requests."""
        # TODO: Prabhat — implement this
        raise NotImplementedError

    def get_request_peer(self, piece_index: int) -> str | None:
        """Return the peer_id a piece was requested from, or None."""
        # TODO: Prabhat — implement this
        raise NotImplementedError
