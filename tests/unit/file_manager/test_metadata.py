import hashlib

import pytest

from bittorrent_lite.config import PROTOCOL_VERSION
from bittorrent_lite.file_manager.metadata import (
    create_metadata,
    save_metadata,
    load_metadata
)


def test_create_metadata(tmp_path):
    file_path = tmp_path / "sample.txt"

    data = b"ABCDEFGHIJKLM"
    file_path.write_bytes(data)

    metadata = create_metadata(
        str(file_path),
        piece_size=5
    )

    assert metadata.format_version == PROTOCOL_VERSION
    assert metadata.filename == "sample.txt"
    assert metadata.file_size == 13
    assert metadata.piece_size == 5
    assert metadata.num_pieces == 3

    assert len(metadata.piece_hashes) == 3

    assert metadata.file_sha256 == hashlib.sha256(data).hexdigest()


def test_metadata_save_and_load(tmp_path):
    file_path = tmp_path / "sample.txt"
    metadata_path = tmp_path / "sample.torrent.json"

    file_path.write_bytes(b"ABCDEFGHIJKLM")

    metadata = create_metadata(
        str(file_path),
        piece_size=5
    )

    save_metadata(metadata, str(metadata_path))

    loaded_metadata, file_id = load_metadata(
        str(metadata_path)
    )

    assert loaded_metadata == metadata
    assert len(file_id) == 64


def test_empty_file_rejected(tmp_path):
    file_path = tmp_path / "empty.txt"
    file_path.write_bytes(b"")

    with pytest.raises(ValueError):
        create_metadata(str(file_path))


def test_invalid_piece_size(tmp_path):
    file_path = tmp_path / "sample.txt"
    file_path.write_bytes(b"hello")

    with pytest.raises(ValueError):
        create_metadata(str(file_path), 0)