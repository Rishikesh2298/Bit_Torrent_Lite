import pytest

from bittorrent_lite.file_manager.splitter import split_file


def test_empty_file(tmp_path):
    file_path = tmp_path / "empty.txt"
    file_path.write_bytes(b"")

    with pytest.raises(ValueError):
        list(split_file(str(file_path), 10))


def test_file_not_found():
    with pytest.raises(FileNotFoundError):
        list(split_file("does_not_exist.txt", 10))


def test_invalid_piece_size(tmp_path):
    file_path = tmp_path / "test.txt"
    file_path.write_bytes(b"hello")

    with pytest.raises(ValueError):
        list(split_file(str(file_path), 0))


def test_file_smaller_than_piece_size(tmp_path):
    file_path = tmp_path / "test.txt"
    file_path.write_bytes(b"hello")

    pieces = list(split_file(str(file_path), 10))

    assert pieces == [
        (0, b"hello")
    ]


def test_exact_multiple(tmp_path):
    file_path = tmp_path / "test.txt"
    file_path.write_bytes(b"abcdefghijkl")

    pieces = list(split_file(str(file_path), 4))

    assert pieces == [
        (0, b"abcd"),
        (1, b"efgh"),
        (2, b"ijkl")
    ]


def test_last_piece_is_shorter(tmp_path):
    file_path = tmp_path / "test.txt"
    file_path.write_bytes(b"abcdefghij")

    pieces = list(split_file(str(file_path), 4))

    assert pieces == [
        (0, b"abcd"),
        (1, b"efgh"),
        (2, b"ij")
    ]