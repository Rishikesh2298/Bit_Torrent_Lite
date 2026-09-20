"""
File Splitter — Rishikesh's Module

Splits a file into fixed-size pieces for distribution.
Each piece is yielded as a (index, bytes) tuple.
The last piece may be smaller than PIECE_SIZE.

Interface:
    split_file(file_path, piece_size) -> Generator[(int, bytes)]

Example:
    A 100 KiB file with PIECE_SIZE=64 KiB produces 2 pieces:
    - Piece 0: 64 KiB
    - Piece 1: 36 KiB  (remainder)

    A 128 KiB file with PIECE_SIZE=64 KiB produces 2 pieces:
    - Piece 0: 64 KiB
    - Piece 1: 64 KiB  (exact multiple — no short last piece)

Edge cases to handle:
    - Empty file (0 bytes) → raise ValueError (rejected in v1)
    - File size is exact multiple of piece_size → no short last piece
    - Very large file → generator avoids loading entire file into memory
    - File does not exist → raise FileNotFoundError
    - piece_size <= 0 → raise ValueError
"""

from typing import Generator

from bittorrent_lite.config import PIECE_SIZE


def split_file(file_path: str, piece_size: int = PIECE_SIZE) -> Generator[tuple[int, bytes], None, None]:
    """
    Split a file into fixed-size pieces, yielding (index, data) tuples.

    This is a generator — it reads one piece at a time from disk,
    avoiding loading the entire file into memory.

    Args:
        file_path: Path to the file to split.
        piece_size: Size of each piece in bytes (default from config).

    Yields:
        (piece_index, piece_bytes) tuples in order from 0 to N-1.
        The last piece may be shorter than piece_size.

    Raises:
        FileNotFoundError: If file_path does not exist.
        ValueError: If piece_size <= 0 or file is empty (zero bytes).
    """
    # TODO: Rishikesh — implement this
    raise NotImplementedError("split_file not yet implemented")
