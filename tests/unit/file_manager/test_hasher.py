import hashlib

from bittorrent_lite.file_manager.hasher import (
    hash_piece,
    verify_piece,
    hash_file
)


def test_hash_piece():
    data = b"hello"

    expected = hashlib.sha256(data).hexdigest()

    assert hash_piece(data) == expected


def test_verify_piece_valid():
    data = b"hello"

    expected = hashlib.sha256(data).hexdigest()

    assert verify_piece(data, expected) is True


def test_verify_piece_invalid():
    data = b"hello"

    expected = hashlib.sha256(b"HELLO").hexdigest()

    assert verify_piece(data, expected) is False


def test_hash_file(tmp_path):
    file_path = tmp_path / "test.txt"
    data = b"Hello BitTorrent Lite"

    file_path.write_bytes(data)

    expected = hashlib.sha256(data).hexdigest()

    assert hash_file(str(file_path)) == expected