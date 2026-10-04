"""
BitTorrent-Lite: Shared Data Types

These dataclasses and enums define the contracts between modules.
All modules import from here — no module defines its own
incompatible version of these structures.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field


class PieceState(enum.Enum):
    """Lifecycle of a piece from the local peer's perspective."""

    MISSING = "MISSING"
    REQUESTED = "REQUESTED"
    VERIFYING = "VERIFYING"
    HAVE = "HAVE"


@dataclass
class TorrentMetadata:
    """
    Complete metadata for a torrent.

    The file_id is not stored inside the JSON.
    It is the SHA-256 of the exact metadata-file bytes
    and is computed at load time.
    """

    format_version: int
    filename: str
    file_size: int
    piece_size: int
    piece_hashes: list[str]
    file_sha256: str

    @property
    def num_pieces(self) -> int:
        """Return the number of pieces from the piece hash list."""
        return len(self.piece_hashes)

    def expected_piece_size(self, index: int) -> int:
        """Return the expected byte length of a piece."""

        if type(index) is not int or index < 0 or index >= self.num_pieces:
            raise IndexError(
                f"Piece index {index} out of range "
                f"[0, {self.num_pieces})"
            )

        if index < self.num_pieces - 1:
            return self.piece_size

        remainder = self.file_size % self.piece_size

        if remainder != 0:
            return remainder

        return self.piece_size


@dataclass
class PeerRecord:
    """Identity and network location of a peer."""

    peer_id: str
    ip: str
    port: int


Bitfield = list[int]


def create_empty_bitfield(num_pieces: int) -> Bitfield:
    """Create a bitfield with all pieces marked as not-owned."""

    return [0] * num_pieces


def create_full_bitfield(num_pieces: int) -> Bitfield:
    """Create a bitfield with all pieces marked as owned."""

    return [1] * num_pieces


def count_pieces(bitfield: Bitfield) -> int:
    """Return the number of pieces owned."""

    return sum(bitfield)


def has_all_pieces(bitfield: Bitfield) -> bool:
    """Return True if all pieces are owned."""

    return all(piece == 1 for piece in bitfield)


@dataclass
class NeighborInfo:
    """
    Per-connection state for one remote peer.
    """

    connection_id: str
    peer_id: str
    bitfield: Bitfield = field(default_factory=list)

    am_choking: bool = True
    am_interested: bool = False
    peer_choking: bool = True
    peer_interested: bool = False

    def can_download(self) -> bool:
        """Return whether downloading is currently allowed."""

        return self.am_interested and not self.peer_choking

    def can_upload(self) -> bool:
        """Return whether uploading is currently allowed."""

        return self.peer_interested and not self.am_choking


@dataclass
class PendingRequest:
    """
    A single outstanding piece request.
    """

    request_id: int
    piece_index: int
    connection_id: str

    send_time: float = 0.0
    deadline: float = 0.0

    def is_expired(self) -> bool:
        """Return whether this request has exceeded its deadline."""

        if self.deadline > 0:
            return time.monotonic() > self.deadline

        return False
