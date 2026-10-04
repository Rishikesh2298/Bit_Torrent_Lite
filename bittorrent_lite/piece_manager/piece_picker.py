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

import random
import threading


class PiecePicker:
    """
    Rarest-first piece selection.

    Counts distinct connected neighbors' advertisements. Permission and
    request-window checks belong to the coordinator before calling pick_piece.
    """

    def __init__(self, num_pieces: int):
        """
        Initialize piece picker.

        Args:
            num_pieces: Total number of pieces in the torrent.
        """
        if type(num_pieces) is not int or num_pieces < 0:
            raise ValueError("num_pieces must be a nonnegative integer")
        self.num_pieces = num_pieces
        # availability[i] = number of connected peers that have piece i
        self.availability: list[int] = [0] * num_pieces
        self._peer_bitfields: dict[str, list[bool]] = {}
        self._lock = threading.Lock()

    def _check_bitfield(self, bitfield: list[bool]) -> None:
        if len(bitfield) != self.num_pieces:
            raise ValueError("bitfield length must match the piece count")
        if any(type(bit) not in (int, bool) or bit not in (0, 1)
               for bit in bitfield):
            raise ValueError("bitfield entries must be zero or one")

    def _recount(self) -> None:
        """Recompute neighborhood counts while holding the picker lock."""
        self.availability = [
            sum(bits[index] for bits in self._peer_bitfields.values())
            for index in range(self.num_pieces)
        ]

    def update_availability(self, peer_id: str, bitfield: list[bool]) -> None:
        """
        Update availability counts when a new peer's bitfield is received.

        Replace this neighbor's snapshot; repeated advertisements are idempotent.

        Args:
            peer_id: The peer whose bitfield was received.
            bitfield: The peer's bitfield (list of bools).
        """
        self._check_bitfield(bitfield)
        with self._lock:
            self._peer_bitfields[peer_id] = list(bitfield)
            self._recount()

    def peer_has_piece(self, peer_id: str, piece_index: int) -> None:
        """
        Update availability when a HAVE message is received.

        Mark the piece in this known neighbor's snapshot, counting it once.

        Args:
            peer_id: The peer that sent the HAVE.
            piece_index: The piece they now have.
        """
        if type(piece_index) is not int or not 0 <= piece_index < self.num_pieces:
            raise ValueError("piece index is out of range")
        with self._lock:
            if peer_id not in self._peer_bitfields:
                raise ValueError("HAVE requires a known neighbor bitfield")
            self._peer_bitfields[peer_id][piece_index] = 1
            self._recount()

    def peer_disconnected(self, peer_id: str, bitfield: list[bool]) -> None:
        """
        Update availability when a peer disconnects.

        Remove the stored snapshot once; repeated disconnects are harmless.

        Args:
            peer_id: The peer that disconnected.
            bitfield: Legacy caller snapshot; the stored snapshot is authoritative.
        """
        with self._lock:
            self._peer_bitfields.pop(peer_id, None)
            self._recount()

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
        self._check_bitfield(my_bitfield)
        self._check_bitfield(peer_bitfield)
        reserved = requested_pieces if requested_pieces is not None else set()
        with self._lock:
            candidates = [
                index for index in range(self.num_pieces)
                if not my_bitfield[index] and peer_bitfield[index]
                and index not in reserved and self.availability[index] > 0
            ]
            if not candidates:
                return None
            minimum = min(self.availability[index] for index in candidates)
            return random.choice([
                index for index in candidates
                if self.availability[index] == minimum
            ])

    def get_availability(self) -> list[int]:
        """Return a copy of the current availability counts (for debugging)."""
        with self._lock:
            return self.availability.copy()
