"""
Piece Picker — Prabhat's Module

Implements the RAREST-FIRST piece selection algorithm.

Concept:
    Maintain a count of how many peers have each piece.
    When selecting a piece to download, choose the piece that:
    1. I do NOT already have
    2. At least one connected peer DOES have
    3. Has the LOWEST availability count (rarest)
    4. Is NOT already being requested

    If there's a tie, break randomly (to spread load).

Why rarest-first?
    If everyone downloads the most common pieces first, the rare pieces
    risk becoming unavailable if the only peer(s) holding them disconnect.
    Rarest-first ensures piece diversity in the swarm, making the system
    more resilient and efficient.

Example:
    My bitfield:     [T, T, F, F, F]   (I have pieces 0 and 1)
    Availability:    [5, 4, 1, 3, 2]   (counts from all connected peers)
    Already requested: {4}

    Candidates: pieces 2, 3 (piece 4 is already requested)
    Piece 2 has availability=1 (rarest) → select piece 2

Interface:
    PiecePicker.update_availability(peer_id, bitfield) -> None
    PiecePicker.peer_has_piece(peer_id, piece_index) -> None
    PiecePicker.peer_disconnected(peer_id, bitfield) -> None
    PiecePicker.pick_piece(my_bitfield, peer_bitfield, requested) -> int | None
    PiecePicker.get_availability() -> list[int]    (for debugging/experiments)
"""

import threading


class PiecePicker:
    """
    Rarest-first piece selection.

    Maintains a global availability counter and provides piece
    selection based on swarm-wide piece distribution.
    """

    def __init__(self, num_pieces: int):
        """
        Initialize piece picker.

        Args:
            num_pieces: Total number of pieces in the torrent.
        """
        self.num_pieces = num_pieces
        # availability[i] = number of connected peers that have piece i
        self.availability: list[int] = [0] * num_pieces
        self._lock = threading.Lock()

    def update_availability(self, peer_id: str, bitfield: list[bool]) -> None:
        """
        Update availability counts when a new peer's bitfield is received.

        For each piece the peer has, increment the counter.

        Args:
            peer_id: The peer whose bitfield was received.
            bitfield: The peer's bitfield (list of bools).
        """
        # TODO: Prabhat — implement this
        raise NotImplementedError

    def peer_has_piece(self, peer_id: str, piece_index: int) -> None:
        """
        Update availability when a HAVE message is received.

        Increment availability[piece_index] by 1.

        Args:
            peer_id: The peer that sent the HAVE.
            piece_index: The piece they now have.
        """
        # TODO: Prabhat — implement this
        raise NotImplementedError

    def peer_disconnected(self, peer_id: str, bitfield: list[bool]) -> None:
        """
        Update availability when a peer disconnects.

        Decrement counts for all pieces the peer had.

        Args:
            peer_id: The peer that disconnected.
            bitfield: The peer's last known bitfield.
        """
        # TODO: Prabhat — implement this
        raise NotImplementedError

    def pick_piece(self, my_bitfield: list[bool], peer_bitfield: list[bool],
                   requested_pieces: set[int] | None = None) -> int | None:
        """
        Select the next piece to request using rarest-first.

        Algorithm:
        1. Find candidate pieces: I don't have AND peer has AND not requested
        2. Among candidates, find the one with minimum availability
        3. If tie, choose randomly
        4. Return the piece index, or None if no valid candidate

        Args:
            my_bitfield: My current piece ownership.
            peer_bitfield: The specific peer's piece ownership.
            requested_pieces: Set of piece indices already being requested.

        Returns:
            Index of the piece to request, or None if nothing available.
        """
        # TODO: Prabhat — implement this
        raise NotImplementedError

    def get_availability(self) -> list[int]:
        """Return a copy of the current availability counts (for debugging)."""
        with self._lock:
            return self.availability.copy()
