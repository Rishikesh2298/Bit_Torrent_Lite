"""Isolated storage acceptance additions; no network or acceptance execution claim.

The literal limits come from the preserved R/G v1 contract. Generic helpers
remain exercised with small pieces; these tests do not redefine their API.
"""

import builtins
import errno
import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from bittorrent_lite.storage import file_store as store_module
from bittorrent_lite.storage import hashing, metadata, pieces
from bittorrent_lite.storage.file_store import FileStore


METADATA_LIMIT = 256 * 1024
PIECE_SIZE = 65536


@pytest.mark.parametrize('size, lengths', [
    (1, [1]), (65535, [65535]), (65536, [65536]),
    (65537, [65536, 1]), (131072, [65536, 65536]),
], ids=['one-byte', 'P-minus-1', 'P', 'P-plus-1', 'two-P'])
def test_original_partition_boundaries_use_literal_independent_lengths(tmp_path, size, lengths):
    data = hashlib.shake_256(b'original-boundary-fixture').digest(size)
    source = tmp_path / 'boundary.bin'
    source.write_bytes(data)
    generated = metadata.create_metadata(str(source))
    assert generated.file_size == size
    assert generated.num_pieces == len(lengths)
    assert [generated.expected_piece_size(i) for i in range(len(lengths))] == lengths
    offset, independent = 0, []
    for length in lengths:
        independent.append(hashlib.sha256(data[offset:offset + length]).hexdigest())
        offset += length
    assert offset == size
    assert generated.piece_hashes == independent
    assert generated.file_sha256 == hashlib.sha256(data).hexdigest()


def document_for(data, *, filename="fixture.bin", piece_size=PIECE_SIZE):
    """Build an oracle independently of project metadata/hash/partition helpers."""
    return {
        "format_version": 1,
        "filename": filename,
        "file_size": len(data),
        "piece_size": piece_size,
        "piece_hashes": [
            hashlib.sha256(data[offset:offset + piece_size]).hexdigest()
            for offset in range(0, len(data), piece_size)
        ],
        "file_sha256": hashlib.sha256(data).hexdigest(),
    }


def load_document(tmp_path, document, *, name="metadata.json"):
    path = tmp_path / name
    path.write_bytes(json.dumps(document, separators=(",", ":")).encode("utf-8"))
    loaded, file_id = metadata.load_metadata(str(path))
    return loaded, file_id, path


def populated_store(tmp_path, *, count=3):
    data = b"".join(hashlib.shake_256(f"piece-{i}".encode()).digest(23) for i in range(count))
    loaded, file_id, _ = load_document(tmp_path, document_for(data, piece_size=23))
    store = FileStore(loaded, file_id, str(tmp_path / "pieces"))
    for index in reversed(range(count)):
        assert store.verify_and_store(index, data[index * 23:(index + 1) * 23])
    return store, data


@pytest.mark.parametrize("size", [METADATA_LIMIT - 1, METADATA_LIMIT, METADATA_LIMIT + 1],
                         ids=["below-256kib", "at-256kib", "above-256kib"])
def test_metadata_input_byte_limit(tmp_path, size):
    raw = json.dumps(document_for(b"\x00\xff")).encode("utf-8")
    path = tmp_path / "bounded.json"
    raw += b" " * (size - len(raw))
    path.write_bytes(raw)
    if size > METADATA_LIMIT:
        with pytest.raises(ValueError, match="(?i)(metadata|size|limit|large|exceed)"):
            metadata.load_metadata(str(path))
    else:
        loaded, file_id = metadata.load_metadata(str(path))
        assert loaded.file_size == 2
        assert file_id == hashlib.sha256(raw).hexdigest()
    assert path.read_bytes() == raw


def test_metadata_read_is_bounded_before_json_parse(tmp_path, monkeypatch):
    path = tmp_path / "oversize.json"
    path.write_bytes(b" " * (METADATA_LIMIT + 1))
    reads = []
    parse_calls = []
    original_open = builtins.open

    class AuditedRead:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def __enter__(self):
            self.wrapped.__enter__()
            return self

        def __exit__(self, *args):
            return self.wrapped.__exit__(*args)

        def read(self, size=-1):
            reads.append(size)
            assert 0 < size <= METADATA_LIMIT + 1, "metadata must not use an unbounded read"
            return self.wrapped.read(size)

    monkeypatch.setattr(metadata, "open", lambda *a, **k: AuditedRead(original_open(*a, **k)),
                        raising=False)
    monkeypatch.setattr(metadata.json, "loads", lambda raw: parse_calls.append(raw))
    with pytest.raises(ValueError):
        metadata.load_metadata(str(path))
    assert reads == [] or sum(reads) <= METADATA_LIMIT + 1
    assert parse_calls == [], "reject oversize metadata before JSON parsing"


def test_exact_metadata_bytes_not_reserialized_values_define_identity(tmp_path):
    document = document_for(b"\x00\xff0123456789")
    compact = json.dumps(document, separators=(",", ":"), sort_keys=True).encode()
    changed = json.dumps(dict(reversed(list(document.items()))), indent=2).encode()
    paths = [tmp_path / name for name in ("a.json", "copy.json", "reformatted.json")]
    for path, raw in zip(paths, (compact, compact, changed)):
        path.write_bytes(raw)
    loaded = [metadata.load_metadata(str(path)) for path in paths]
    assert loaded[0][0] == loaded[1][0] == loaded[2][0]
    assert loaded[0][1] == loaded[1][1] == hashlib.sha256(compact).hexdigest()
    assert loaded[2][1] == hashlib.sha256(changed).hexdigest()
    assert loaded[0][1] != loaded[2][1]


@pytest.mark.parametrize("data", [b"\x00" * 131072, bytes(range(256)) * 512],
                         ids=["all-zero-two-full-pieces", "binary-two-full-pieces"])
def test_two_full_piece_boundary_and_unicode_filename(tmp_path, data):
    source = tmp_path / "मूल फ़ाइल-λ.bin"
    source.write_bytes(data)
    generated = metadata.create_metadata(str(source))
    oracle = document_for(data, filename=source.name)
    assert generated.file_size == 131072
    assert generated.piece_hashes == oracle["piece_hashes"]
    assert generated.file_sha256 == oracle["file_sha256"]
    assert generated.num_pieces == 2
    assert [generated.expected_piece_size(index) for index in range(2)] == [65536, 65536]
    store = FileStore(generated, "unicode-case", str(tmp_path / "pieces"))
    assert store.verify_and_store(1, data[65536:])
    assert store.verify_and_store(0, data[:65536])
    output = tmp_path / "पुनर्निर्माण-λ.bin"
    assert store.assemble_file(str(output))
    assert output.read_bytes() == data


def test_twelve_distinct_pieces_assemble_by_numeric_index(tmp_path):
    # All complete pieces differ, including their first and last bytes.
    chunks = [bytes([index]) + hashlib.shake_256(str(index).encode()).digest(65534)
              + bytes([255 - index]) for index in range(12)]
    data = b"".join(chunks) + b"\x00\xffshort-final"
    loaded, file_id, _ = load_document(tmp_path, document_for(data))
    assert len(set(loaded.piece_hashes)) == 13
    store = FileStore(loaded, file_id, str(tmp_path / "pieces"))
    for index in [10, 1, 11, 2, 9, 0, 8, 3, 7, 4, 6, 5, 12]:
        assert store.verify_and_store(index, data[index * PIECE_SIZE:(index + 1) * PIECE_SIZE])
    lexical = sorted(path.name for path in store.pieces_dir.glob("*.piece"))
    assert lexical[:4] == ["0.piece", "1.piece", "10.piece", "11.piece"]
    output = tmp_path / "assembled.bin"
    assert store.assemble_file(str(output))
    assert output.stat().st_size == len(data)
    assert output.read_bytes() == data
    assert hashlib.sha256(output.read_bytes()).hexdigest() == loaded.file_sha256


@pytest.mark.parametrize("already_owned", [False, True], ids=["new-piece", "existing-piece"])
def test_partial_piece_write_never_publishes_or_destroys_previous_piece(tmp_path, monkeypatch, already_owned):
    data = b"verified bytes\x00\xff"
    loaded, file_id, _ = load_document(tmp_path, document_for(data))
    store = FileStore(loaded, file_id, str(tmp_path / "pieces"))
    if already_owned:
        assert store.verify_and_store(0, data)
    before = {path.name: path.read_bytes() for path in store.pieces_dir.iterdir()}
    bits_before = store.get_bitfield()
    original_temp = store_module.NamedTemporaryFile

    class PartialWriter:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def __enter__(self):
            self.wrapped.__enter__()
            return self

        def __exit__(self, *args):
            return self.wrapped.__exit__(*args)

        @property
        def name(self):
            return self.wrapped.name

        def write(self, content):
            self.wrapped.write(content[:3])
            raise OSError(errno.ENOSPC, "isolated partial piece-write failure")

    monkeypatch.setattr(store_module, "NamedTemporaryFile",
                        lambda **kwargs: PartialWriter(original_temp(**kwargs)))
    with pytest.raises(OSError) as raised:
        store.verify_and_store(0, data)
    assert raised.value.errno == errno.ENOSPC
    assert store.get_bitfield() == bits_before
    assert {path.name: path.read_bytes() for path in store.pieces_dir.iterdir()} == before


@pytest.mark.parametrize("index", [-1, 3, True, False, 1.5, "1", None],
                         ids=["negative", "past-end", "true", "false", "float", "string", "null"])
def test_invalid_piece_read_and_write_leave_storage_unchanged(tmp_path, index):
    store, _ = populated_store(tmp_path)
    before = {path.name: path.read_bytes() for path in store.pieces_dir.iterdir()}
    for operation in (lambda: store.read_piece(index), lambda: store.verify_and_store(index, b"x" * 23)):
        with pytest.raises(IndexError):
            operation()
    assert store.get_bitfield() == [1, 1, 1]
    assert {path.name: path.read_bytes() for path in store.pieces_dir.iterdir()} == before


@pytest.mark.parametrize("fault", ["partial-write", "permission", "replace", "hash"],
                         ids=["disk-full-after-partial-write", "permission-write", "replace", "final-hash"])
def test_atomic_assembly_failure_preserves_unrelated_destination(tmp_path, monkeypatch, fault):
    store, data = populated_store(tmp_path)
    output = tmp_path / "sentinel.bin"
    sentinel = b"unrelated-existing-output\x00\xff"
    output.write_bytes(sentinel)
    before = {path.relative_to(tmp_path): path.read_bytes()
              for path in tmp_path.rglob("*") if path.is_file()}
    original_temp = store_module.NamedTemporaryFile

    class FailingWriter:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def __enter__(self):
            self.wrapped.__enter__()
            return self

        def __exit__(self, *args):
            return self.wrapped.__exit__(*args)

        @property
        def name(self):
            return self.wrapped.name

        def write(self, content):
            if fault == "partial-write":
                self.wrapped.write(content[:max(1, len(content) // 2)])
                raise OSError(errno.ENOSPC, "isolated simulated full disk")
            raise PermissionError(errno.EACCES, "isolated simulated permission denial")

    if fault in {"partial-write", "permission"}:
        monkeypatch.setattr(store_module, "NamedTemporaryFile",
                            lambda **kwargs: FailingWriter(original_temp(**kwargs)))
    elif fault == "replace":
        original_replace = Path.replace

        def replace(source, destination):
            if Path(destination) == output:
                raise OSError(errno.EIO, "isolated assembly replace failure")
            return original_replace(source, destination)

        monkeypatch.setattr(Path, "replace", replace)
    else:
        monkeypatch.setattr(store_module, "hash_file", lambda path: "0" * 64)

    if fault == "hash":
        assert store.assemble_file(str(output)) is False
    else:
        with pytest.raises(OSError):
            store.assemble_file(str(output))
    after = {path.relative_to(tmp_path): path.read_bytes()
             for path in tmp_path.rglob("*") if path.is_file()}
    assert after == before
    assert output.read_bytes() == sentinel
    assert store.get_bitfield() == [1] * store.metadata.num_pieces
    assert b"".join(store.read_piece(i) for i in range(store.metadata.num_pieces)) == data


def test_source_processing_uses_bounded_independent_piece_reads(tmp_path, monkeypatch):
    data = hashlib.shake_256(b"bounded-source").digest(3 * PIECE_SIZE + 17)
    source = tmp_path / "source.bin"
    source.write_bytes(data)
    original_open = builtins.open
    reads = []
    handles = []

    class Reader:
        def __init__(self, wrapped):
            self.wrapped = wrapped
            handles.append(wrapped)

        def __enter__(self):
            self.wrapped.__enter__()
            return self

        def __exit__(self, *args):
            return self.wrapped.__exit__(*args)

        def read(self, size=-1):
            assert 0 < size <= PIECE_SIZE, "source reads must stay bounded"
            reads.append(size)
            return self.wrapped.read(size)

        def seek(self, *args):
            return self.wrapped.seek(*args)

    def open_source(path, *args, **kwargs):
        handle = original_open(path, *args, **kwargs)
        return Reader(handle) if Path(path) == source else handle

    for module in (metadata, hashing, pieces, store_module):
        monkeypatch.setattr(module, "open", open_source, raising=False)
    generated = metadata.create_metadata(str(source))
    store = FileStore(generated, "source-case", source_path=str(source))
    store.validate_source()
    with ThreadPoolExecutor(max_workers=4) as pool:
        actual = list(pool.map(store.read_piece, [3, 0, 2, 1] * 4))
    for index, chunk in zip([3, 0, 2, 1] * 4, actual):
        assert chunk == data[index * PIECE_SIZE:(index + 1) * PIECE_SIZE]
    assert reads and all(handle.closed for handle in handles)
    assert len(handles) >= 16, "concurrent calls must not share a seek position"
    assert source.read_bytes() == data


def test_cached_piece_read_is_bounded_even_if_replaced_with_oversize_data(tmp_path, monkeypatch):
    store, _ = populated_store(tmp_path)
    target = store.pieces_dir / "1.piece"
    target.write_bytes(b"x" * 1000)
    original_open = builtins.open
    sizes = []

    class Reader(io.BytesIO):
        def read(self, size=-1):
            sizes.append(size)
            assert 0 < size <= 24, "read at most expected piece length plus one"
            return super().read(size)

    def open_piece(path, *args, **kwargs):
        if Path(path) == target:
            return Reader(target.read_bytes())
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(store_module, "open", open_piece, raising=False)
    with pytest.raises(ValueError):
        store.read_piece(1)
    assert sizes
    assert store.get_bitfield() == [1, 0, 1]
    assert target.read_bytes() == b"x" * 1000


@pytest.mark.parametrize("raw", [b"[]", b"null", b"17", b"true", b'"text"', b"\xff",
                                 b"\xef\xbb\xbf{}", b"{", b"{}"],
                         ids=["array", "null", "integer", "bool", "string", "utf8", "bom", "truncated", "missing"])
def test_metadata_parser_rejects_invalid_root_or_encoding(tmp_path, raw):
    path = tmp_path / "invalid.json"
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        metadata.load_metadata(str(path))
    assert path.read_bytes() == raw
