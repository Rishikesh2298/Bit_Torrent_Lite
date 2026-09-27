import pytest

from bittorrent_lite.file_manager.file_store import FileStore
from bittorrent_lite.file_manager.metadata import create_metadata


def create_test_metadata(tmp_path):
    file_path = tmp_path / "source.txt"

    data = b"ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    file_path.write_bytes(data)

    metadata = create_metadata(
        str(file_path),
        piece_size=5
    )

    return file_path, metadata


def test_seeder_validate_source(tmp_path):
    file_path, metadata = create_test_metadata(tmp_path)

    store = FileStore(
        metadata,
        "test-file-id",
        pieces_dir=str(tmp_path / "pieces"),
        source_path=str(file_path)
    )

    store.validate_source()

    assert store.get_bitfield() == [1] * metadata.num_pieces


def test_seeder_read_piece(tmp_path):
    file_path, metadata = create_test_metadata(tmp_path)

    store = FileStore(
        metadata,
        "test-file-id",
        source_path=str(file_path)
    )

    store.validate_source()

    assert store.read_piece(0) == b"ABCDE"
    assert store.read_piece(1) == b"FGHIJ"


def test_downloader_starts_empty(tmp_path):
    file_path, metadata = create_test_metadata(tmp_path)

    store = FileStore(
        metadata,
        "test-file-id",
        pieces_dir=str(tmp_path / "pieces")
    )

    assert store.get_bitfield() == [0] * metadata.num_pieces


def test_valid_piece_is_stored(tmp_path):
    file_path, metadata = create_test_metadata(tmp_path)

    store = FileStore(
        metadata,
        "test-file-id",
        pieces_dir=str(tmp_path / "pieces")
    )

    result = store.verify_and_store(
        0,
        b"ABCDE"
    )

    assert result is True
    assert store.has_piece(0) is True
    assert store.get_bitfield()[0] == 1
    assert store.read_piece(0) == b"ABCDE"


def test_corrupt_piece_is_rejected(tmp_path):
    file_path, metadata = create_test_metadata(tmp_path)

    store = FileStore(
        metadata,
        "test-file-id",
        pieces_dir=str(tmp_path / "pieces")
    )

    result = store.verify_and_store(
        0,
        b"WRONG"
    )

    assert result is False
    assert store.has_piece(0) is False
    assert store.get_bitfield()[0] == 0


def test_wrong_piece_size_is_rejected(tmp_path):
    file_path, metadata = create_test_metadata(tmp_path)

    store = FileStore(
        metadata,
        "test-file-id",
        pieces_dir=str(tmp_path / "pieces")
    )

    result = store.verify_and_store(
        0,
        b"ABC"
    )

    assert result is False
    assert store.has_piece(0) is False


def test_invalid_piece_index(tmp_path):
    file_path, metadata = create_test_metadata(tmp_path)

    store = FileStore(
        metadata,
        "test-file-id",
        pieces_dir=str(tmp_path / "pieces")
    )

    with pytest.raises(IndexError):
        store.read_piece(-1)

    with pytest.raises(IndexError):
        store.read_piece(metadata.num_pieces)


def test_assemble_file(tmp_path):
    file_path, metadata = create_test_metadata(tmp_path)

    store = FileStore(
        metadata,
        "test-file-id",
        pieces_dir=str(tmp_path / "pieces")
    )

    pieces = [
        b"ABCDE",
        b"FGHIJ",
        b"KLMNO",
        b"PQRST",
        b"UVWXY",
        b"Z"
    ]

    for index, data in enumerate(pieces):
        assert store.verify_and_store(index, data) is True

    output_path = tmp_path / "output.txt"

    assert store.assemble_file(str(output_path)) is True

    assert output_path.read_bytes() == file_path.read_bytes()


def test_invalid_source_is_rejected(tmp_path):
    file_path, metadata = create_test_metadata(tmp_path)

    file_path.write_bytes(b"CORRUPTED DATA")

    store = FileStore(
        metadata,
        "test-file-id",
        source_path=str(file_path)
    )

    with pytest.raises(ValueError):
        store.validate_source()