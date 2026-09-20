"""
Torrent Metadata — Rishikesh's Module

Creates, saves, and loads the .torrent.json metadata file.
This is the BitTorrent-Lite equivalent of a .torrent file.

The `file_id` is the SHA-256 of the exact bytes of the metadata file.
This prevents circular hashing issues and JSON reserialization ambiguity.

Interface:
    create_metadata(file_path, piece_size) -> TorrentMetadata
    save_metadata(metadata, output_path) -> None
    load_metadata(metadata_path) -> tuple[TorrentMetadata, str]
    validate_metadata(metadata, file_id) -> None
"""

import json
from pathlib import Path

from bittorrent_lite.types import TorrentMetadata
from bittorrent_lite.config import PIECE_SIZE, PROTOCOL_VERSION


def create_metadata(file_path: str, piece_size: int = PIECE_SIZE) -> TorrentMetadata:
    """
    Create torrent metadata for a file.

    1. Validates the file exists and is not empty.
    2. Hashes the entire file.
    3. Splits the file into pieces and hashes each piece.
    4. Returns the populated TorrentMetadata object.
    """
    # TODO: Rishikesh — implement this
    raise NotImplementedError("create_metadata not yet implemented")


def save_metadata(metadata: TorrentMetadata, output_path: str) -> None:
    """
    Serialize metadata to a JSON file.

    IMPORTANT: For deterministic hashing, the JSON must be canonical.
    Use `json.dump(..., sort_keys=True, separators=(',', ':'))`
    so that every peer produces the exact same file bytes.
    """
    # TODO: Rishikesh — implement this
    raise NotImplementedError("save_metadata not yet implemented")


def load_metadata(metadata_path: str) -> tuple[TorrentMetadata, str]:
    """
    Load metadata from a JSON file and compute its file_id.

    1. Reads the raw bytes of the file.
    2. Computes file_id = SHA-256(raw_bytes).
    3. Parses the JSON into a TorrentMetadata object.
    4. Validates the fields (e.g., hash list matches piece count).
    
    Returns:
        (metadata, file_id)
    """
    # TODO: Rishikesh — implement this
    raise NotImplementedError("load_metadata not yet implemented")


def validate_metadata(metadata: TorrentMetadata, file_id: str) -> None:
    """
    Verify metadata invariants.

    - piece_size must be > 0
    - file_size must be > 0
    - format_version must be known
    - num_pieces must exactly match len(piece_hashes)
    - num_pieces must match ceil(file_size / piece_size)
    """
    # TODO: Rishikesh — implement this
    raise NotImplementedError("validate_metadata not yet implemented")
