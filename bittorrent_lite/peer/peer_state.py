"""
Peer State — Shared Module (primarily Anik + Prabhat)

Holds all state for a single peer process.
This is the central data store that other modules read from and write to.

Thread safety:
    Multiple connection threads will access this state concurrently.
    A lock protects the mutable fields.

This module does NOT implement protocol logic — it is a data container.
"""

import threading
from bittorrent_lite.types import (
    TorrentMetadata, Bitfield, PeerInfo, ConnectionState,
    create_empty_bitfield, create_full_bitfield
)


class PeerState:
    """
    Complete state for one peer in the swarm.

    Created once when a peer process starts. Shared (by reference)
    among all connection handler threads within that peer.
    """

    def __init__(self, peer_id: str, port: int, metadata: TorrentMetadata,
                 is_seeder: bool = False):
        """
        Initialize peer state.

        Args:
            peer_id: This peer's unique identifier.
            port: This peer's listening port.
            metadata: Torrent metadata (loaded from .torrent.json).
            is_seeder: If True, start with all pieces owned.
        """
        self.peer_id = peer_id
        self.port = port
        self.metadata = metadata

        # My bitfield: which pieces I own
        if is_seeder:
            self.bitfield: Bitfield = create_full_bitfield(metadata.num_pieces)
        else:
            self.bitfield: Bitfield = create_empty_bitfield(metadata.num_pieces)

        # Piece data store: piece_index -> bytes
        # For a seeder, this is populated from the original file.
        # For a leecher, pieces are added as they're downloaded and verified.
        self.pieces: dict[int, bytes] = {}

        # Connected peers and their state
        # peer_id -> ConnectionState (the 4 boolean flags)
        self.connection_states: dict[str, ConnectionState] = {}

        # Known peer bitfields (what pieces each connected peer has)
        # peer_id -> Bitfield
        self.peer_bitfields: dict[str, Bitfield] = {}

        # Lock for thread-safe access
        self.lock = threading.Lock()

    def have_piece(self, piece_index: int) -> bool:
        """Check if I own a specific piece."""
        with self.lock:
            return self.bitfield[piece_index]

    def add_piece(self, piece_index: int, data: bytes) -> None:
        """
        Record that I now own a piece (after successful hash verification).

        Args:
            piece_index: Index of the piece.
            data: Verified piece data.
        """
        with self.lock:
            self.bitfield[piece_index] = True
            self.pieces[piece_index] = data

    def get_piece(self, piece_index: int) -> bytes | None:
        """Get piece data by index, or None if not owned."""
        with self.lock:
            return self.pieces.get(piece_index)

    def set_peer_bitfield(self, peer_id: str, bitfield: Bitfield) -> None:
        """Store a remote peer's bitfield (received via BITFIELD message)."""
        with self.lock:
            self.peer_bitfields[peer_id] = bitfield

    def update_peer_has_piece(self, peer_id: str, piece_index: int) -> None:
        """Update: remote peer now has this piece (received via HAVE message)."""
        with self.lock:
            if peer_id in self.peer_bitfields:
                self.peer_bitfields[peer_id][piece_index] = True

    def remove_peer(self, peer_id: str) -> None:
        """Clean up state when a peer disconnects."""
        with self.lock:
            self.peer_bitfields.pop(peer_id, None)
            self.connection_states.pop(peer_id, None)

    def completed_pieces_count(self) -> int:
        """Return how many pieces I currently own."""
        with self.lock:
            return sum(self.bitfield)

    def is_complete(self) -> bool:
        """Return True if I have all pieces."""
        with self.lock:
            return all(self.bitfield)
