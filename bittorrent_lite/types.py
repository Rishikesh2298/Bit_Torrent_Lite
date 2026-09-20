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
from typing import Optional


# ──────────────────────────────────────────────
# Piece State Enum
# ──────────────────────────────────────────────

class PieceState(enum.Enum):
    """Lifecycle of a piece from the local peer's perspective."""
    MISSING = "MISSING"         # Not yet obtained
    REQUESTED = "REQUESTED"     # A REQUEST has been sent for this piece
    VERIFYING = "VERIFYING"     # Bytes received, hash check in progress
    HAVE = "HAVE"               # Verified and stored on disk


# ──────────────────────────────────────────────
# Metadata Types (produced by file_manager, consumed everywhere)
# ──────────────────────────────────────────────

@dataclass
class TorrentMetadata:
    """
    Complete metadata for a torrent.

    Analogous to a .torrent file in real BitTorrent.
    Contains everything a peer needs to know about the file
    and its pieces (excluding actual file data).

    The ``file_id`` is NOT stored inside the JSON.  It is the SHA-256
    of the exact metadata-file bytes and is computed at load time.
    """
    format_version: int            # Start with 1
    filename: str                  # Display name only; never an arbitrary output path
    file_size: int                 # Exact number of source bytes
    piece_size: int                # Default 65 536 bytes (64 KiB)
    piece_hashes: list[str]        # Ordered list of lowercase SHA-256 hex strings
    file_sha256: str               # SHA-256 of the entire original file

    @property
    def num_pieces(self) -> int:
        """Derive piece count from the hash list length."""
        return len(self.piece_hashes)

    def expected_piece_size(self, index: int) -> int:
        """Return the expected byte length of piece *index*.

        The last piece contains only the remaining bytes; all others
        are exactly ``piece_size`` bytes.
        """
        if index < 0 or index >= self.num_pieces:
            raise IndexError(f"Piece index {index} out of range [0, {self.num_pieces})")
        if index < self.num_pieces - 1:
            return self.piece_size
        # Last piece: remainder (file_size may be an exact multiple)
        remainder = self.file_size % self.piece_size
        return remainder if remainder != 0 else self.piece_size


# ──────────────────────────────────────────────
# Peer Identity / Discovery
# ──────────────────────────────────────────────

@dataclass
class PeerRecord:
    """
    Identity and network location of a peer in the swarm.
    Returned by the tracker during peer discovery.
    """
    peer_id: str       # Human-readable identifier, e.g., "peer-001"
    ip: str            # IPv4 address
    port: int          # Listening port


# ──────────────────────────────────────────────
# Bitfield Helpers
# ──────────────────────────────────────────────
# A Bitfield is a list of 0/1 integers (matching the JSON wire format).

Bitfield = list[int]


def create_empty_bitfield(num_pieces: int) -> Bitfield:
    """Create a bitfield with all pieces marked as not-owned."""
    return [0] * num_pieces


def create_full_bitfield(num_pieces: int) -> Bitfield:
    """Create a bitfield with all pieces marked as owned (for seeders)."""
    return [1] * num_pieces


def count_pieces(bitfield: Bitfield) -> int:
    """Return the number of pieces owned (1 values)."""
    return sum(bitfield)


def has_all_pieces(bitfield: Bitfield) -> bool:
    """Return True if all pieces are owned."""
    return all(p == 1 for p in bitfield)


# ──────────────────────────────────────────────
# Per-Connection / Neighbor State
# ──────────────────────────────────────────────

@dataclass
class NeighborInfo:
    """
    Per-connection state for one remote peer, owned by the Coordinator.

    The four boolean flags control data-transfer eligibility:
    - Download allowed when: am_interested=True AND peer_choking=False
    - Upload allowed when:   peer_interested=True AND am_choking=False
    """
    connection_id: str                  # Unique ID for this connection instance
    peer_id: str                        # Remote peer identifier
    bitfield: Bitfield = field(default_factory=list)
    am_choking: bool = True             # I am choking the remote peer (won't upload)
    am_interested: bool = False         # I am interested in the remote peer's pieces
    peer_choking: bool = True           # Remote peer is choking me (won't upload to me)
    peer_interested: bool = False       # Remote peer is interested in my pieces

    def can_download(self) -> bool:
        """Can I download from this peer right now?"""
        return self.am_interested and not self.peer_choking

    def can_upload(self) -> bool:
        """Can I upload to this peer right now?"""
        return self.peer_interested and not self.am_choking


# ──────────────────────────────────────────────
# Pending Request Tracking
# ──────────────────────────────────────────────

@dataclass
class PendingRequest:
    """
    A single outstanding piece request issued by the Coordinator.
    """
    request_id: int           # Monotonically increasing per connection+direction
    piece_index: int          # Which piece was requested
    connection_id: str        # Over which connection
    send_time: float = 0.0   # Monotonic time when the writer confirmed REQUEST sent
    deadline: float = 0.0     # Monotonic time after which the request is timed out

    def is_expired(self) -> bool:
        """Check if this request has exceeded its deadline."""
        return time.monotonic() > self.deadline if self.deadline > 0 else False
