"""
Piece Hasher — Rishikesh's Module

Provides cryptographic hashing for piece integrity verification.

Interface:
    hash_piece(data) -> str             # compute SHA-256 hex digest of a piece
    verify_piece(data, expected) -> bool # compare computed hash to expected
    hash_file(file_path) -> str         # stream entire file through SHA-256

How it's used:
    1. During metadata creation: hash every piece to build the piece hash list
    2. During download: verify received piece data against expected hash from metadata
    3. During metadata creation: hash the entire file for file_sha256

Security note:
    SHA-256 is used because it's collision-resistant. If an attacker or
    network error corrupts a piece, the hash will (almost certainly) not match.
    A hash alone does NOT authenticate the sender — it only verifies content
    against trusted metadata.
"""

import hashlib

from bittorrent_lite.config import HASH_ALGORITHM


def hash_piece(data: bytes) -> str:
    """
    Compute the cryptographic hash of a piece.

    Args:
        data: Raw bytes of the piece.

    Returns:
        Lowercase hex digest string (e.g., "a3f2b8c1d4...").
    """
    # TODO: Rishikesh — implement using hashlib
    raise NotImplementedError("hash_piece not yet implemented")


def verify_piece(data: bytes, expected_hash: str) -> bool:
    """
    Verify that piece data matches its expected hash.

    Args:
        data: Raw bytes of the received piece.
        expected_hash: The expected lowercase hex digest from metadata.

    Returns:
        True if hash(data) == expected_hash, False otherwise.
    """
    # TODO: Rishikesh — implement this
    raise NotImplementedError("verify_piece not yet implemented")


def hash_file(file_path: str) -> str:
    """
    Compute the SHA-256 hash of an entire file by streaming.

    Reads the file in chunks to avoid loading it all into memory.

    Args:
        file_path: Path to the file.

    Returns:
        Lowercase hex digest string.

    Raises:
        FileNotFoundError: If file_path does not exist.
    """
    # TODO: Rishikesh — implement by streaming in 64 KiB chunks
    raise NotImplementedError("hash_file not yet implemented")
