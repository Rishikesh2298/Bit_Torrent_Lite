"""
Tests for File Manager module (Rishikesh's module).

These tests validate:
    - File splitting produces correct number of pieces
    - Piece sizes are correct (last piece may be smaller)
    - Hash generation is deterministic
    - Hash verification works for correct and corrupted data
    - Metadata creation/save/load round-trips correctly
    - File assembly produces byte-identical output
"""

import os
import tempfile
import pytest

# These imports will work once the modules are implemented:
# from bittorrent_lite.file_manager.splitter import split_file
# from bittorrent_lite.file_manager.hasher import hash_piece, verify_piece
# from bittorrent_lite.file_manager.metadata import create_metadata, save_metadata, load_metadata
# from bittorrent_lite.file_manager.assembler import assemble_file
# from bittorrent_lite.config import PIECE_SIZE


class TestSplitter:
    """Tests for file splitting."""

    def test_split_known_file(self):
        """A 1.5MB file with 512KB pieces should produce 3 pieces."""
        # TODO: Create a temp file of known size, split it, verify piece count
        pytest.skip("Not yet implemented")

    def test_split_exact_multiple(self):
        """File size is exact multiple of piece_size → no short last piece."""
        pytest.skip("Not yet implemented")

    def test_split_last_piece_smaller(self):
        """File size is NOT a multiple → last piece is smaller."""
        pytest.skip("Not yet implemented")

    def test_split_empty_file(self):
        """Empty file should produce 0 pieces (or 1 empty piece — decide)."""
        pytest.skip("Not yet implemented")

    def test_split_file_not_found(self):
        """Non-existent file should raise FileNotFoundError."""
        pytest.skip("Not yet implemented")

    def test_split_invalid_piece_size(self):
        """piece_size <= 0 should raise ValueError."""
        pytest.skip("Not yet implemented")

    def test_split_reassemble_identity(self):
        """split → concatenate pieces → should equal original file bytes."""
        pytest.skip("Not yet implemented")


class TestHasher:
    """Tests for piece hashing."""

    def test_hash_deterministic(self):
        """Same data should always produce the same hash."""
        pytest.skip("Not yet implemented")

    def test_hash_different_data(self):
        """Different data should produce different hashes."""
        pytest.skip("Not yet implemented")

    def test_verify_correct(self):
        """verify_piece should return True for matching data and hash."""
        pytest.skip("Not yet implemented")

    def test_verify_corrupted(self):
        """verify_piece should return False for corrupted data."""
        pytest.skip("Not yet implemented")

    def test_hash_empty_data(self):
        """Hashing empty bytes should not crash."""
        pytest.skip("Not yet implemented")


class TestMetadata:
    """Tests for metadata creation/serialization."""

    def test_create_metadata(self):
        """create_metadata should produce correct TorrentMetadata."""
        pytest.skip("Not yet implemented")

    def test_save_load_roundtrip(self):
        """save → load should produce identical metadata."""
        pytest.skip("Not yet implemented")

    def test_info_hash_deterministic(self):
        """Same metadata should always produce the same info_hash."""
        pytest.skip("Not yet implemented")

    def test_load_nonexistent_file(self):
        """Loading from non-existent path should raise FileNotFoundError."""
        pytest.skip("Not yet implemented")


class TestAssembler:
    """Tests for file reconstruction."""

    def test_assemble_complete(self):
        """Given all pieces, assembly should produce the original file."""
        pytest.skip("Not yet implemented")

    def test_assemble_missing_piece(self):
        """Missing piece should raise ValueError."""
        pytest.skip("Not yet implemented")

    def test_assemble_verify_hashes(self):
        """Assembled file should pass hash verification."""
        pytest.skip("Not yet implemented")
