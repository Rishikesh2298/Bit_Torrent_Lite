"""
BitTorrent-Lite Piece Picker.

Supports both:

1. Stateful API:
       picker.pick_piece()

2. Compatibility API:
       picker.pick_piece(owned, remote, reserved)

The compatibility API uses bitfields for owned/remote.
"""

from __future__ import annotations

import random
import threading
from collections.abc import Iterable
from typing import Dict, Optional, Set


class _PieceSetView(set):
    """Set-like view that is also callable as local_pieces()."""

    def __call__(self):
        return set(self)


class _AvailabilityView(list):
    """Availability snapshot supporting availability(index)."""

    def __call__(self, index: int) -> int:
        if isinstance(index, bool) or not isinstance(index, int):
            raise ValueError("piece index must be an integer")

        if index < 0 or index >= len(self):
            raise ValueError("piece index out of range")

        return self[index]


class PiecePicker:
    def __init__(
        self,
        piece_count: int,
        local_pieces: Optional[Iterable[int]] = None,
        seed: Optional[int] = None,
    ) -> None:

        if isinstance(piece_count, bool) or not isinstance(piece_count, int):
            raise ValueError("piece_count must be an integer")

        if piece_count <= 0:
            raise ValueError("piece_count must be positive")

        self.piece_count = piece_count
        self._seed = seed

        self._local_pieces: Set[int] = set()
        self._reserved: Set[int] = set()

        # peer_id -> pieces advertised by that peer
        self._peer_pieces: Dict[str, Set[int]] = {}

        # piece_index -> number of peers advertising that piece
        self._availability = [0] * piece_count

        self._lock = threading.RLock()

        if local_pieces is not None:
            self._local_pieces = self._validate_piece_indices(
                local_pieces
            )

    # ================================================================
    # Validation
    # ================================================================

    def _validate_piece_index(self, piece_index: int) -> int:
        if isinstance(piece_index, bool):
            raise ValueError("piece index must be an integer")

        if not isinstance(piece_index, int):
            raise ValueError("piece index must be an integer")

        if piece_index < 0 or piece_index >= self.piece_count:
            raise ValueError(
                f"piece index {piece_index} out of range"
            )

        return piece_index

    def _validate_piece_indices(
        self,
        pieces: Iterable[int],
    ) -> Set[int]:
        if isinstance(pieces, (str, bytes, bytearray)):
            raise ValueError("pieces must be an iterable of integers")

        try:
            values = list(pieces)
        except TypeError as exc:
            raise ValueError(
                "pieces must be an iterable of integers"
            ) from exc

        result = set()

        for piece in values:
            result.add(self._validate_piece_index(piece))

        return result

    def _validate_bitfield(
        self,
        bits: Iterable[int],
    ) -> list[int]:
        if isinstance(bits, (str, bytes, bytearray)):
            raise ValueError("invalid bitfield")

        try:
            values = list(bits)
        except TypeError as exc:
            raise ValueError("invalid bitfield") from exc

        if len(values) != self.piece_count:
            raise ValueError(
                f"bitfield must contain exactly {self.piece_count} entries"
            )

        result = []

        for value in values:
            if isinstance(value, bool):
                value = int(value)

            if value not in (0, 1):
                raise ValueError(
                    "bitfield values must be 0 or 1"
                )

            result.append(int(value))

        return result

    def _bitfield_to_set(
        self,
        bits: Iterable[int],
    ) -> Set[int]:
        values = self._validate_bitfield(bits)

        return {
            index
            for index, bit in enumerate(values)
            if bit == 1
        }

    # ================================================================
    # Properties
    # ================================================================

    @property
    def local_pieces(self):
        with self._lock:
            return _PieceSetView(self._local_pieces)

    @property
    def availability(self):
        with self._lock:
            return _AvailabilityView(self._availability)

    def get_availability(
        self,
        piece_index: Optional[int] = None,
    ):
        if piece_index is None:
            with self._lock:
                return list(self._availability)

        self._validate_piece_index(piece_index)

        with self._lock:
            return self._availability[piece_index]

    @property
    def reserved_pieces(self) -> Set[int]:
        with self._lock:
            return set(self._reserved)

    @property
    def reserved_count(self) -> int:
        with self._lock:
            return len(self._reserved)

    @property
    def completed_count(self) -> int:
        with self._lock:
            return len(self._local_pieces)

    @property
    def remaining_count(self) -> int:
        with self._lock:
            return self.piece_count - len(self._local_pieces)

    @property
    def is_complete(self) -> bool:
        return self.remaining_count == 0

    @property
    def complete(self) -> bool:
        return self.is_complete

    # ================================================================
    # Availability management
    # ================================================================

    def _recalculate_availability(self) -> None:
        self._availability = [0] * self.piece_count

        for pieces in self._peer_pieces.values():
            for piece in pieces:
                self._availability[piece] += 1

    def update_availability(
        self,
        peer_id: str,
        bits: Iterable[int],
    ) -> None:
        pieces = self._bitfield_to_set(bits)

        with self._lock:
            self._peer_pieces[peer_id] = pieces
            self._recalculate_availability()

    def update_peer(
        self,
        peer_id: str,
        pieces: Iterable[int],
    ) -> None:
        values = list(pieces)

        # A full-length 0/1 sequence is a bitfield.
        if (
            len(values) == self.piece_count
            and all(
                value in (0, 1, False, True)
                for value in values
            )
        ):
            self.update_availability(peer_id, values)
            return

        piece_set = self._validate_piece_indices(values)

        with self._lock:
            self._peer_pieces[peer_id] = piece_set
            self._recalculate_availability()

    def add_peer(
        self,
        peer_id: str,
        pieces: Optional[Iterable[int]] = None,
    ) -> None:
        with self._lock:
            if pieces is None:
                self._peer_pieces.setdefault(peer_id, set())

            else:
                values = list(pieces)

                if (
                    len(values) == self.piece_count
                    and all(
                        value in (0, 1, False, True)
                        for value in values
                    )
                ):
                    self._peer_pieces[peer_id] = (
                        self._bitfield_to_set(values)
                    )
                else:
                    self._peer_pieces[peer_id] = (
                        self._validate_piece_indices(values)
                    )

            self._recalculate_availability()

    def remove_peer(self, peer_id: str) -> None:
        with self._lock:
            self._peer_pieces.pop(peer_id, None)
            self._recalculate_availability()

    def peer_disconnected(
        self,
        peer_id: str,
        bits: Optional[Iterable[int]] = None,
    ) -> None:
        # `bits` is retained for compatibility with the older API.
        # The stored peer snapshot is authoritative.
        with self._lock:
            self._peer_pieces.pop(peer_id, None)
            self._recalculate_availability()

    # ================================================================
    # HAVE handling
    # ================================================================

    def peer_has_piece(
        self,
        peer_id: str,
        piece_index: int,
    ) -> bool:
        self._validate_piece_index(piece_index)

        with self._lock:
            if peer_id not in self._peer_pieces:
                raise ValueError(
                    "HAVE requires an initial neighbor snapshot"
                )

            pieces = self._peer_pieces[peer_id]

            # Duplicate HAVE is idempotent.
            if piece_index in pieces:
                return True

            pieces.add(piece_index)
            self._availability[piece_index] += 1

            return True

    def add_peer_piece(
        self,
        peer_id: str,
        piece_index: int,
    ) -> None:
        self.peer_has_piece(peer_id, piece_index)

    def remove_peer_piece(
        self,
        peer_id: str,
        piece_index: int,
    ) -> None:
        self._validate_piece_index(piece_index)

        with self._lock:
            pieces = self._peer_pieces.get(peer_id)

            if pieces is None:
                return

            if piece_index in pieces:
                pieces.remove(piece_index)

                self._availability[piece_index] = max(
                    0,
                    self._availability[piece_index] - 1,
                )

    def peers_for_piece(
        self,
        piece_index: int,
    ) -> Set[str]:
        self._validate_piece_index(piece_index)

        with self._lock:
            return {
                peer_id
                for peer_id, pieces in self._peer_pieces.items()
                if piece_index in pieces
            }

    # ================================================================
    # Local pieces
    # ================================================================

    def add_local_piece(self, piece_index: int) -> None:
        self._validate_piece_index(piece_index)

        with self._lock:
            self._local_pieces.add(piece_index)
            self._reserved.discard(piece_index)

    def remove_local_piece(self, piece_index: int) -> None:
        self._validate_piece_index(piece_index)

        with self._lock:
            self._local_pieces.discard(piece_index)

    def piece_completed(self, piece_index: int) -> None:
        self.add_local_piece(piece_index)

    # ================================================================
    # Reservation
    # ================================================================

    def reserve(self, piece_index: int) -> bool:
        self._validate_piece_index(piece_index)

        with self._lock:
            if piece_index in self._local_pieces:
                return False

            if piece_index in self._reserved:
                return False

            self._reserved.add(piece_index)
            return True

    def release(self, piece_index: int) -> bool:
        self._validate_piece_index(piece_index)

        with self._lock:
            if piece_index not in self._reserved:
                return False

            self._reserved.remove(piece_index)
            return True

    def is_reserved(self, piece_index: int) -> bool:
        self._validate_piece_index(piece_index)

        with self._lock:
            return piece_index in self._reserved

    # ================================================================
    # Stateful rarest-first
    # ================================================================

    def _available_candidates(self) -> list[int]:
        return [
            piece
            for piece in range(self.piece_count)
            if piece not in self._local_pieces
            and piece not in self._reserved
            and self._availability[piece] > 0
        ]

    def _choose_stateful_rarest(
        self,
        candidates: list[int],
    ) -> Optional[int]:
        if not candidates:
            return None

        minimum = min(
            self._availability[piece]
            for piece in candidates
        )

        rarest = [
            piece
            for piece in candidates
            if self._availability[piece] == minimum
        ]

        # Stateful/legacy picker behavior is deterministic:
        # choose the smallest piece index on a tie.
        return min(rarest)

    # ================================================================
    # Compatibility picker
    # ================================================================

    def _pick_from_bitfields(
        self,
        owned,
        remote,
        reserved=None,
    ) -> Optional[int]:

        owned_bits = self._validate_bitfield(owned)
        remote_bits = self._validate_bitfield(remote)

        if reserved is None:
            reserved_set: Set[int] = set()
        else:
            reserved_set = self._validate_piece_indices(reserved)

        candidates = []

        for piece in range(self.piece_count):

            if owned_bits[piece] == 1:
                continue

            if remote_bits[piece] == 0:
                continue

            if piece in reserved_set:
                continue

            candidates.append(piece)

        if not candidates:
            return None

        # If the supplied remote peer is not part of our registered
        # neighbor state, the explicit remote bitfield is still enough
        # to make these pieces eligible.
        #
        # If availability information exists, use it for rarest-first.
        known = [
            piece
            for piece in candidates
            if self._availability[piece] > 0
        ]

        if known:
            minimum = min(
                self._availability[piece]
                for piece in known
            )

            rarest = [
                piece
                for piece in known
                if self._availability[piece] == minimum
            ]

            # A remote bitfield may contain a piece whose global
            # availability is zero only because that source was supplied
            # directly by the caller. Those pieces remain valid, but a
            # known rarest piece takes priority when availability exists.
            candidates = rarest

        else:
            candidates = candidates

        # Compatibility contract uses random tie-breaking.
        return random.choice(candidates)

    # ================================================================
    # Main picker
    # ================================================================

    def pick_piece(
        self,
        owned=None,
        remote=None,
        reserved=None,
    ) -> Optional[int]:

        with self._lock:

            # Compatibility API.
            if owned is not None or remote is not None:

                if owned is None or remote is None:
                    raise TypeError(
                        "owned and remote must be provided together"
                    )

                return self._pick_from_bitfields(
                    owned,
                    remote,
                    reserved,
                )

            # Stateful API.
            candidates = self._available_candidates()

            selected = self._choose_stateful_rarest(candidates)

            if selected is None:
                return None

            self._reserved.add(selected)

            return selected

    def pick_pieces(
        self,
        count: int,
    ) -> list[int]:

        if isinstance(count, bool) or not isinstance(count, int):
            raise ValueError("count must be an integer")

        if count < 0:
            raise ValueError("count must be non-negative")

        result = []

        with self._lock:
            for _ in range(count):
                piece = self.pick_piece()

                if piece is None:
                    break

                result.append(piece)

        return result

    # ================================================================
    # Clear/reset
    # ================================================================

    def clear(self) -> None:
        """
        Clear peer availability and reservations.

        Local pieces are preserved.
        """
        with self._lock:
            self._peer_pieces.clear()
            self._reserved.clear()
            self._availability = [0] * self.piece_count

    def reset(self) -> None:
        """
        Clear all picker state including local pieces.
        """
        with self._lock:
            self._peer_pieces.clear()
            self._reserved.clear()
            self._local_pieces.clear()
            self._availability = [0] * self.piece_count

    # ================================================================
    # Miscellaneous
    # ================================================================

    def __len__(self) -> int:
        return self.piece_count