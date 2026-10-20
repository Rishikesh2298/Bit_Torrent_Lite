"""File management acceptance tests replacing the original skipped scenarios."""
import hashlib

import pytest

from bittorrent_lite.file_manager.splitter import split_file
from bittorrent_lite.file_manager.hasher import hash_piece, verify_piece
from bittorrent_lite.file_manager.metadata import create_metadata, save_metadata, load_metadata
from bittorrent_lite.file_manager.file_store import FileStore


def source(tmp_path, data=b'abcdefghij'):
    path = tmp_path / 'source.bin'
    path.write_bytes(data)
    return path


def stored(tmp_path, missing=None):
    path = source(tmp_path)
    metadata = create_metadata(str(path), 4)
    store = FileStore(metadata, 'acceptance', str(tmp_path / 'pieces'))
    for index, data in split_file(str(path), 4):
        if index != missing:
            assert store.verify_and_store(index, data)
    return path, store


class TestSplitter:
    def test_split_known_file(self, tmp_path):
        data = bytes(range(256)) * 6144
        parts = list(split_file(str(source(tmp_path, data)), 524288))
        assert [i for i, _ in parts] == [0, 1, 2]
        assert [len(p) for _, p in parts] == [524288] * 3
        assert b''.join(p for _, p in parts) == data

    def test_split_exact_multiple(self, tmp_path):
        assert list(split_file(str(source(tmp_path, b'abcdefgh')), 4)) == [(0, b'abcd'), (1, b'efgh')]

    def test_split_last_piece_smaller(self, tmp_path):
        assert list(split_file(str(source(tmp_path)), 4))[-1] == (2, b'ij')

    def test_split_empty_file(self, tmp_path):
        with pytest.raises(ValueError, match='empty'):
            list(split_file(str(source(tmp_path, b'')), 4))

    def test_split_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            list(split_file(str(tmp_path / 'absent'), 4))

    def test_split_invalid_piece_size(self, tmp_path):
        path = source(tmp_path)
        for size in (0, -1, True, 1.5):
            with pytest.raises(ValueError):
                list(split_file(str(path), size))

    def test_split_reassemble_identity(self, tmp_path):
        data = bytes(range(256)) * 37
        parts = list(split_file(str(source(tmp_path, data)), 113))
        assert b''.join(p for _, p in parts) == data
        assert [i for i, _ in parts] == list(range(len(parts)))


class TestHasher:
    def test_hash_deterministic(self):
        expected = 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'
        assert hash_piece(b'abc') == hash_piece(b'abc') == expected

    def test_hash_different_data(self):
        assert hash_piece(b'abc') != hash_piece(b'abd')

    def test_verify_correct(self):
        assert verify_piece(b'abc', hashlib.sha256(b'abc').hexdigest())

    def test_verify_corrupted(self):
        assert not verify_piece(b'abd', hashlib.sha256(b'abc').hexdigest())

    def test_hash_empty_data(self):
        assert hash_piece(b'') == 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'


class TestMetadata:
    def test_create_metadata(self, tmp_path):
        metadata = create_metadata(str(source(tmp_path)), 4)
        assert metadata.filename == 'source.bin'
        assert (metadata.file_size, metadata.piece_size, metadata.num_pieces) == (10, 4, 3)
        assert metadata.piece_hashes == [hashlib.sha256(p).hexdigest() for p in (b'abcd', b'efgh', b'ij')]
        assert metadata.file_sha256 == hashlib.sha256(b'abcdefghij').hexdigest()

    def test_save_load_roundtrip(self, tmp_path):
        original = create_metadata(str(source(tmp_path)), 4)
        path = tmp_path / 'metadata.json'
        save_metadata(original, str(path))
        restored, file_id = load_metadata(str(path))
        assert restored == original
        assert file_id == hashlib.sha256(path.read_bytes()).hexdigest()

    def test_info_hash_deterministic(self, tmp_path):
        metadata = create_metadata(str(source(tmp_path)), 4)
        a, b = tmp_path / 'a.json', tmp_path / 'b.json'
        save_metadata(metadata, str(a))
        save_metadata(metadata, str(b))
        assert a.read_bytes() == b.read_bytes()
        assert load_metadata(str(a))[1] == load_metadata(str(b))[1]

    def test_load_nonexistent_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_metadata(str(tmp_path / 'absent.json'))


class TestAssembler:
    def test_assemble_complete(self, tmp_path):
        path, store = stored(tmp_path)
        output = tmp_path / 'result.bin'
        assert store.assemble_file(str(output))
        assert output.read_bytes() == path.read_bytes()

    def test_assemble_missing_piece(self, tmp_path):
        _, store = stored(tmp_path, missing=1)
        output = tmp_path / 'result.bin'
        output.write_bytes(b'existing output')
        assert store.assemble_file(str(output)) is False
        assert output.read_bytes() == b'existing output'

    def test_assemble_verify_hashes(self, tmp_path):
        path, store = stored(tmp_path)
        output = tmp_path / 'result.bin'
        assert store.assemble_file(str(output))
        assert hashlib.sha256(output.read_bytes()).hexdigest() == store.metadata.file_sha256
        (store.pieces_dir / '1.piece').write_bytes(b'BAD!')
        assert store.assemble_file(str(output)) is False
        assert output.read_bytes() == path.read_bytes()
