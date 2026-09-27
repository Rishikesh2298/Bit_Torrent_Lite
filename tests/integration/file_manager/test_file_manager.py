import pytest

from bittorrent_lite.file_manager.file_store import FileStore
from bittorrent_lite.file_manager.metadata import (
    create_metadata,
    save_metadata,
    load_metadata
)


def test_complete_file_manager_workflow(tmp_path):

    source_path = tmp_path / "source.txt"
    metadata_path = tmp_path / "source.torrent.json"
    pieces_dir = tmp_path / "pieces"
    output_path = tmp_path / "reconstructed.txt"

    original_data = (
        b"BitTorrent-Lite File Manager Integration Test "
        b"ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    )

    source_path.write_bytes(original_data)

    metadata = create_metadata(
        str(source_path),
        piece_size=10
    )

    save_metadata(
        metadata,
        str(metadata_path)
    )

    loaded_metadata, file_id = load_metadata(
        str(metadata_path)
    )

    assert loaded_metadata == metadata
    assert len(file_id) == 64

    seeder = FileStore(
        loaded_metadata,
        file_id,
        pieces_dir=str(pieces_dir),
        source_path=str(source_path)
    )

    seeder.validate_source()

    assert seeder.get_bitfield() == [
        1
    ] * loaded_metadata.num_pieces

    downloader = FileStore(
        loaded_metadata,
        file_id,
        pieces_dir=str(pieces_dir)
    )

    for index in range(loaded_metadata.num_pieces):

        data = seeder.read_piece(index)

        assert downloader.verify_and_store(
            index,
            data
        ) is True

    assert downloader.get_bitfield() == [
        1
    ] * loaded_metadata.num_pieces

    assert downloader.assemble_file(
        str(output_path)
    ) is True

    reconstructed_data = output_path.read_bytes()

    assert reconstructed_data == original_data


def test_single_byte_file(tmp_path):

    source_path = tmp_path / "single_byte.txt"
    source_path.write_bytes(b"A")

    metadata = create_metadata(
        str(source_path),
        piece_size=10
    )

    assert metadata.num_pieces == 1
    assert metadata.expected_piece_size(0) == 1

    pieces_dir = tmp_path / "pieces"

    store = FileStore(
        metadata,
        "single-byte-id",
        pieces_dir=str(pieces_dir)
    )

    assert store.verify_and_store(0, b"A") is True
    assert store.get_bitfield() == [1]


def test_exact_piece_boundary(tmp_path):

    source_path = tmp_path / "exact.txt"
    source_path.write_bytes(b"ABCDEFGHIJ")

    metadata = create_metadata(
        str(source_path),
        piece_size=5
    )

    assert metadata.num_pieces == 2
    assert metadata.expected_piece_size(0) == 5
    assert metadata.expected_piece_size(1) == 5

    pieces_dir = tmp_path / "pieces"

    store = FileStore(
        metadata,
        "exact-id",
        pieces_dir=str(pieces_dir)
    )

    assert store.verify_and_store(0, b"ABCDE") is True
    assert store.verify_and_store(1, b"FGHIJ") is True

    assert store.get_bitfield() == [1, 1]


def test_one_byte_over_piece_boundary(tmp_path):

    source_path = tmp_path / "over_boundary.txt"
    source_path.write_bytes(b"ABCDEFGHIJK")

    metadata = create_metadata(
        str(source_path),
        piece_size=5
    )

    assert metadata.num_pieces == 3
    assert metadata.expected_piece_size(0) == 5
    assert metadata.expected_piece_size(1) == 5
    assert metadata.expected_piece_size(2) == 1

    pieces_dir = tmp_path / "pieces"

    store = FileStore(
        metadata,
        "boundary-id",
        pieces_dir=str(pieces_dir)
    )

    assert store.verify_and_store(0, b"ABCDE") is True
    assert store.verify_and_store(1, b"FGHIJ") is True
    assert store.verify_and_store(2, b"K") is True

    output_path = tmp_path / "output.txt"

    assert store.assemble_file(
        str(output_path)
    ) is True

    assert output_path.read_bytes() == b"ABCDEFGHIJK"


def test_wrong_last_piece_size_rejected(tmp_path):

    source_path = tmp_path / "source.txt"
    source_path.write_bytes(b"ABCDEFGHIJK")

    metadata = create_metadata(
        str(source_path),
        piece_size=5
    )

    store = FileStore(
        metadata,
        "wrong-last-piece-id",
        pieces_dir=str(tmp_path / "pieces")
    )

    assert store.verify_and_store(2, b"KL") is False
    assert store.has_piece(2) is False


def test_piece_index_boolean_rejected(tmp_path):

    source_path = tmp_path / "source.txt"
    source_path.write_bytes(b"ABCDEFGHIJ")

    metadata = create_metadata(
        str(source_path),
        piece_size=5
    )

    store = FileStore(
        metadata,
        "bool-index-id",
        pieces_dir=str(tmp_path / "pieces")
    )

    with pytest.raises(IndexError):
        store.read_piece(True)

    with pytest.raises(IndexError):
        store.read_piece(False)


def test_missing_piece_prevents_assembly(tmp_path):

    source_path = tmp_path / "source.txt"
    source_path.write_bytes(b"ABCDEFGHIJK")

    metadata = create_metadata(
        str(source_path),
        piece_size=5
    )

    store = FileStore(
        metadata,
        "missing-piece-id",
        pieces_dir=str(tmp_path / "pieces")
    )

    assert store.verify_and_store(0, b"ABCDE") is True
    assert store.verify_and_store(1, b"FGHIJ") is True

    output_path = tmp_path / "output.txt"

    assert store.assemble_file(
        str(output_path)
    ) is False


def test_corrupted_piece_is_rejected_during_read(tmp_path):

    source_path = tmp_path / "source.txt"
    source_path.write_bytes(b"ABCDEFGHIJ")

    metadata = create_metadata(
        str(source_path),
        piece_size=5
    )

    pieces_dir = tmp_path / "pieces"

    store = FileStore(
        metadata,
        "corruption-id",
        pieces_dir=str(pieces_dir)
    )

    assert store.verify_and_store(
        0,
        b"ABCDE"
    ) is True

    piece_path = pieces_dir / "corruption-id" / "0.piece"

    piece_path.write_bytes(b"XXXXX")

    with pytest.raises(ValueError):
        store.read_piece(0)


def test_metadata_change_produces_different_file_id(tmp_path):

    source_path = tmp_path / "source.txt"
    metadata_path = tmp_path / "source.torrent.json"

    source_path.write_bytes(b"ABCDEFGHIJ")

    metadata = create_metadata(
        str(source_path),
        piece_size=5
    )

    save_metadata(
        metadata,
        str(metadata_path)
    )

    _, original_file_id = load_metadata(
        str(metadata_path)
    )

    original_metadata_bytes = metadata_path.read_bytes()

    changed_metadata_bytes = original_metadata_bytes.replace(
        b'"filename":"source.txt"',
        b'"filename":"changed.txt"'
    )

    assert changed_metadata_bytes != original_metadata_bytes

    metadata_path.write_bytes(
        changed_metadata_bytes
    )

    _, changed_file_id = load_metadata(
        str(metadata_path)
    )

    assert changed_file_id != original_file_id