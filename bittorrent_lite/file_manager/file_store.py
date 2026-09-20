"""
File Store — Rishikesh's Module

Disk-backed piece storage and retrieval.
Replaces the old in-memory dict from PeerState.

Interface:
    FileStore(metadata, file_id, pieces_dir, source_path)
    read_piece(index) -> bytes
    verify_and_store(index, data) -> bool
    has_piece(index) -> bool
    get_bitfield() -> list[int]
    assemble_file(output_path) -> bool
    validate_source() -> None
"""

import os
from pathlib import Path

from bittorrent_lite.types import TorrentMetadata
from bittorrent_lite.config import DEFAULT_PIECES_DIR


class FileStore:
    """
    Manages reading and writing pieces to/from disk.
    For seeders, it reads directly from the source file.
    For downloaders, it stores verified pieces in pieces_dir.
    """

    def __init__(self, metadata: TorrentMetadata, file_id: str,
                 pieces_dir: str = DEFAULT_PIECES_DIR,
                 source_path: str | None = None):
        """
        Initialize the file store.

        Args:
            metadata: The torrent metadata.
            file_id: The unique file identifier (info_hash).
            pieces_dir: Where to store downloaded pieces.
            source_path: If seeding, the path to the complete source file.
        """
        self.metadata = metadata
        self.file_id = file_id
        self.pieces_dir = Path(pieces_dir) / self.file_id
        self.source_path = Path(source_path) if source_path else None
        
        # In-memory track of what we have on disk
        self._bitfield: list[int] = [0] * metadata.num_pieces
        self._lock = None  # TODO: Add threading.Lock

    def read_piece(self, index: int) -> bytes:
        """
        Read piece bytes from disk (either from source file or piece file).
        Raises IndexError if invalid, or FileNotFoundError if not owned.
        """
        # TODO: Rishikesh — implement this
        raise NotImplementedError

    def verify_and_store(self, index: int, data: bytes) -> bool:
        """
        Verify the piece hash and store it to disk if valid.
        Never marks HAVE or writes to disk if the hash fails.
        """
        # TODO: Rishikesh — implement this
        raise NotImplementedError

    def has_piece(self, index: int) -> bool:
        """Return True if this piece is verified and stored."""
        # TODO: Rishikesh — implement this
        raise NotImplementedError

    def get_bitfield(self) -> list[int]:
        """Return a copy of the current piece ownership."""
        # TODO: Rishikesh — implement this
        raise NotImplementedError

    def assemble_file(self, output_path: str) -> bool:
        """
        Concatenate all piece files into the final file.
        Truncates padding in the last piece, verifies whole-file hash.
        """
        # TODO: Rishikesh — implement this
        raise NotImplementedError

    def validate_source(self) -> None:
        """
        For seeders: verify the entire source_path against all piece hashes.
        Updates the bitfield to all 1s if valid. Raises error if invalid.
        """
        # TODO: Rishikesh — implement this
        raise NotImplementedError
