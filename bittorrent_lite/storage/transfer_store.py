from __future__ import annotations

import hashlib
import math
from pathlib import Path


DEFAULT_PIECE_SIZE = 64 * 1024
MAX_FILE_SIZE = 64 * 1024 * 1024


class FileStore:
    """
    Handles file metadata, piece reads/writes, and SHA-256 verification.

    Networking code should use this class instead of directly accessing
    files on disk.
    """

    def __init__(
        self,
        path,
        piece_size=DEFAULT_PIECE_SIZE,
        piece_hashes=None,
    ):
        self.path = Path(path)
        self.piece_size = piece_size

        if self.piece_size <= 0:
            raise ValueError("piece_size must be greater than zero")

        self.piece_hashes = list(piece_hashes) if piece_hashes is not None else None

        if self.path.exists():
            if not self.path.is_file():
                raise ValueError("path must point to a file")

            self.file_size = self.path.stat().st_size

            if self.file_size > MAX_FILE_SIZE:
                raise ValueError("file exceeds maximum supported size")

        else:
            self.file_size = 0

    @property
    def piece_count(self):
        """Return the total number of pieces."""
        if self.file_size == 0:
            return 0

        return math.ceil(self.file_size / self.piece_size)

    def piece_length(self, piece_index):
        """Return the actual byte length of a piece."""
        self._validate_piece_index(piece_index)

        start = piece_index * self.piece_size
        remaining = self.file_size - start

        return min(self.piece_size, remaining)

    def read_piece(self, piece_index):
        """
        Read one complete piece from the file.

        The final piece may be smaller than piece_size.
        """
        self._validate_piece_index(piece_index)

        offset = piece_index * self.piece_size
        length = self.piece_length(piece_index)

        with self.path.open("rb") as file:
            file.seek(offset)
            data = file.read(length)

        if len(data) != length:
            raise IOError(
                f"could not read complete piece {piece_index}: "
                f"expected {length} bytes, got {len(data)}"
            )

        return data

    def write_piece(self, piece_index, data):
        """
        Write a piece at its correct file offset.

        This method supports creating a new destination file.
        """
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("piece data must be bytes-like")

        data = bytes(data)

        if piece_index < 0:
            raise ValueError("piece_index must be non-negative")

        if self.file_size == 0:
            raise ValueError("cannot write a piece when file size is unknown")

        self._validate_piece_index(piece_index)

        expected_length = self.piece_length(piece_index)

        if len(data) != expected_length:
            raise ValueError(
                f"invalid piece length: expected {expected_length}, "
                f"got {len(data)}"
            )

        self.path.parent.mkdir(parents=True, exist_ok=True)

        mode = "r+b" if self.path.exists() else "wb"

        with self.path.open(mode) as file:
            file.seek(piece_index * self.piece_size)
            file.write(data)
            file.flush()

    def calculate_piece_hash(self, piece_index):
        """Calculate SHA-256 for a single piece."""
        data = self.read_piece(piece_index)
        return hashlib.sha256(data).hexdigest()

    def calculate_file_hash(self):
        """Calculate SHA-256 for the complete file."""
        digest = hashlib.sha256()

        with self.path.open("rb") as file:
            while True:
                chunk = file.read(1024 * 1024)

                if not chunk:
                    break

                digest.update(chunk)

        return digest.hexdigest()

    def verify_piece(self, piece_index, data=None):
        """
        Verify a piece against the expected SHA-256 hash.

        If data is supplied, verify that data.
        Otherwise read the piece from disk.
        """
        if self.piece_hashes is None:
            raise ValueError("piece hashes are not configured")

        self._validate_piece_index(piece_index)

        if piece_index >= len(self.piece_hashes):
            raise ValueError("no expected hash exists for this piece")

        if data is None:
            data = self.read_piece(piece_index)

        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("piece data must be bytes-like")

        actual_hash = hashlib.sha256(bytes(data)).hexdigest()
        expected_hash = self.piece_hashes[piece_index]

        return actual_hash == expected_hash

    @staticmethod
    def calculate_piece_hashes(data, piece_size=DEFAULT_PIECE_SIZE):
        """
        Calculate SHA-256 hashes for all pieces of a bytes object.
        """
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("data must be bytes-like")

        if piece_size <= 0:
            raise ValueError("piece_size must be greater than zero")

        data = bytes(data)

        hashes = []

        for start in range(0, len(data), piece_size):
            piece = data[start:start + piece_size]
            hashes.append(hashlib.sha256(piece).hexdigest())

        return hashes

    @staticmethod
    def calculate_file_hash_from_bytes(data):
        """Calculate SHA-256 of a bytes object."""
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("data must be bytes-like")

        return hashlib.sha256(bytes(data)).hexdigest()

    def _validate_piece_index(self, piece_index):
        if not isinstance(piece_index, int):
            raise TypeError("piece_index must be an integer")

        if piece_index < 0:
            raise ValueError("piece_index must be non-negative")

        if piece_index >= self.piece_count:
            raise IndexError(
                f"piece_index {piece_index} is outside valid range "
                f"0..{self.piece_count - 1}"
            )