import hashlib

import pytest

from bittorrent_lite.file_store import (
    FileStore,
    DEFAULT_PIECE_SIZE,
)


def test_piece_count(tmp_path):
    file_path = tmp_path / "test.bin"

    data = b"A" * 100

    file_path.write_bytes(data)

    store = FileStore(
        file_path,
        piece_size=32,
    )

    assert store.file_size == 100
    assert store.piece_count == 4


def test_read_piece(tmp_path):
    file_path = tmp_path / "test.bin"

    data = b"abcdefghijklmnopqrstuvwxyz"

    file_path.write_bytes(data)

    store = FileStore(
        file_path,
        piece_size=10,
    )

    assert store.read_piece(0) == b"abcdefghij"
    assert store.read_piece(1) == b"klmnopqrst"
    assert store.read_piece(2) == b"uvwxyz"


def test_final_piece_can_be_smaller(tmp_path):
    file_path = tmp_path / "test.bin"

    data = b"123456789012345"

    file_path.write_bytes(data)

    store = FileStore(
        file_path,
        piece_size=10,
    )

    assert store.piece_count == 2
    assert store.piece_length(0) == 10
    assert store.piece_length(1) == 5
    assert store.read_piece(1) == b"12345"


def test_piece_hash(tmp_path):
    file_path = tmp_path / "test.bin"

    data = b"hello world"

    file_path.write_bytes(data)

    store = FileStore(
        file_path,
        piece_size=64,
    )

    expected = hashlib.sha256(data).hexdigest()

    assert store.calculate_piece_hash(0) == expected


def test_file_hash(tmp_path):
    file_path = tmp_path / "test.bin"

    data = b"BitTorrent Lite test file"

    file_path.write_bytes(data)

    store = FileStore(file_path)

    expected = hashlib.sha256(data).hexdigest()

    assert store.calculate_file_hash() == expected


def test_calculate_piece_hashes():
    data = b"abcdefghijklmnop"

    hashes = FileStore.calculate_piece_hashes(
        data,
        piece_size=4,
    )

    expected = [
        hashlib.sha256(b"abcd").hexdigest(),
        hashlib.sha256(b"efgh").hexdigest(),
        hashlib.sha256(b"ijkl").hexdigest(),
        hashlib.sha256(b"mnop").hexdigest(),
    ]

    assert hashes == expected


def test_verify_piece(tmp_path):
    file_path = tmp_path / "test.bin"

    data = b"abcdefgh"

    file_path.write_bytes(data)

    hashes = FileStore.calculate_piece_hashes(
        data,
        piece_size=4,
    )

    store = FileStore(
        file_path,
        piece_size=4,
        piece_hashes=hashes,
    )

    assert store.verify_piece(0, b"abcd")
    assert store.verify_piece(1, b"efgh")


def test_verify_piece_rejects_corrupted_data(tmp_path):
    file_path = tmp_path / "test.bin"

    data = b"abcdefgh"

    file_path.write_bytes(data)

    hashes = FileStore.calculate_piece_hashes(
        data,
        piece_size=4,
    )

    store = FileStore(
        file_path,
        piece_size=4,
        piece_hashes=hashes,
    )

    assert not store.verify_piece(0, b"abce")


def test_write_piece(tmp_path):
    file_path = tmp_path / "output.bin"

    original_data = b"abcdefgh"

    file_path.write_bytes(b"\x00" * len(original_data))

    store = FileStore(
        file_path,
        piece_size=4,
    )

    store.write_piece(0, b"abcd")
    store.write_piece(1, b"efgh")

    assert file_path.read_bytes() == original_data


def test_write_and_read_piece(tmp_path):
    file_path = tmp_path / "output.bin"

    data = b"abcdefghij"

    file_path.write_bytes(data)

    store = FileStore(
        file_path,
        piece_size=5,
    )

    store.write_piece(0, b"12345")
    store.write_piece(1, b"67890")

    assert store.read_piece(0) == b"12345"
    assert store.read_piece(1) == b"67890"


def test_invalid_piece_index(tmp_path):
    file_path = tmp_path / "test.bin"

    file_path.write_bytes(b"abcdefgh")

    store = FileStore(
        file_path,
        piece_size=4,
    )

    with pytest.raises(IndexError):
        store.read_piece(2)


def test_negative_piece_index(tmp_path):
    file_path = tmp_path / "test.bin"

    file_path.write_bytes(b"abcdefgh")

    store = FileStore(
        file_path,
        piece_size=4,
    )

    with pytest.raises(ValueError):
        store.read_piece(-1)


def test_invalid_piece_length(tmp_path):
    file_path = tmp_path / "test.bin"

    file_path.write_bytes(b"abcdefgh")

    store = FileStore(
        file_path,
        piece_size=4,
    )

    with pytest.raises(ValueError):
        store.write_piece(0, b"abc")


def test_invalid_piece_data_type(tmp_path):
    file_path = tmp_path / "test.bin"

    file_path.write_bytes(b"abcdefgh")

    store = FileStore(
        file_path,
        piece_size=4,
    )

    with pytest.raises(TypeError):
        store.write_piece(0, "abcd")


def test_file_size_limit(tmp_path):
    file_path = tmp_path / "test.bin"

    file_path.write_bytes(b"abcdefgh")

    store = FileStore(
        file_path,
        piece_size=4,
    )

    assert store.file_size == 8