"""Regression and boundary checks for the repository's implemented behavior."""

import hashlib
import json
import random
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from bittorrent_lite.file_manager.file_store import FileStore
from bittorrent_lite.file_manager.metadata import (
    calc_num_pieces, create_metadata, load_metadata, save_metadata, validate_metadata,
)
from bittorrent_lite.file_manager.splitter import split_file
from bittorrent_lite.peer.peer_state import PeerState
from bittorrent_lite.piece_manager.piece_picker import PiecePicker
from bittorrent_lite.protocol import messages
from bittorrent_lite.types import NeighborInfo, PendingRequest


@pytest.fixture
def sample(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"ABCDE12345xyz")
    metadata = create_metadata(str(source), 5)
    return source, metadata


@pytest.mark.parametrize("field,value", [
    ("file_size", True), ("file_size", 13.0), ("file_size", "13"),
    ("piece_size", True), ("piece_size", 5.0), ("piece_size", "5"),
    ("format_version", True), ("format_version", 1.0),
    ("piece_hashes", None), ("piece_hashes", "a" * 64),
    ("file_sha256", "z" * 64), ("file_sha256", "A" * 64),
    ("piece_hashes", ["z" * 64] * 3),
])
def test_metadata_rejects_invalid_field_types_and_hashes(sample, field, value):
    _, metadata = sample
    with pytest.raises(ValueError):
        validate_metadata(replace(metadata, **{field: value}), "a" * 64)


@pytest.mark.parametrize("value", ["z" * 64, "A" * 64, "", None])
def test_metadata_rejects_invalid_file_id(sample, value):
    with pytest.raises(ValueError):
        validate_metadata(sample[1], value)


@pytest.mark.parametrize("document", [[], None, {}, {"filename": "x"}])
def test_load_malformed_metadata_reports_value_error(tmp_path, document):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        load_metadata(str(path))


@pytest.mark.parametrize("size", [True, 1.5, "5", 0, -1])
def test_invalid_piece_size_is_rejected_before_reading(sample, size):
    source, _ = sample
    with pytest.raises(ValueError):
        list(split_file(str(source), size))
    with pytest.raises(ValueError):
        create_metadata(str(source), size)


@pytest.mark.parametrize("index", [True, 0.5, "0", -1, 3])
def test_expected_piece_size_rejects_invalid_index(sample, index):
    with pytest.raises(IndexError):
        sample[1].expected_piece_size(index)


def test_failed_source_revalidation_clears_advertisements(sample):
    source, metadata = sample
    store = FileStore(metadata, "sample", source_path=str(source))
    store.validate_source()
    source.write_bytes(b"X" * metadata.file_size)
    with pytest.raises(ValueError):
        store.validate_source()
    assert store.get_bitfield() == [0] * metadata.num_pieces


def test_seeder_read_rejects_source_changed_after_validation(sample):
    source, metadata = sample
    store = FileStore(metadata, "sample", source_path=str(source))
    store.validate_source()
    source.write_bytes(b"X" * metadata.file_size)
    with pytest.raises(ValueError):
        store.read_piece(0)


@pytest.mark.parametrize("damage", ["remove", "corrupt", "truncate"])
def test_cached_have_does_not_hide_disk_damage(sample, tmp_path, damage):
    _, metadata = sample
    store = FileStore(metadata, "sample", str(tmp_path / "pieces"))
    assert store.verify_and_store(0, b"ABCDE")
    piece = store.pieces_dir / "0.piece"
    if damage == "remove":
        piece.unlink()
    else:
        piece.write_bytes(b"XXXXX" if damage == "corrupt" else b"A")
    assert store.has_piece(0) is False
    assert store.get_bitfield()[0] == 0


def filled_store(sample, tmp_path):
    source, metadata = sample
    store = FileStore(metadata, "sample", str(tmp_path / "pieces"))
    for index, data in split_file(str(source), metadata.piece_size):
        assert store.verify_and_store(index, data)
    return store


def test_failed_final_hash_preserves_existing_output(sample, tmp_path):
    store = filled_store(sample, tmp_path)
    store.metadata = replace(store.metadata, file_sha256="0" * 64)
    output = tmp_path / "output.bin"
    output.write_bytes(b"previous output")
    assert store.assemble_file(str(output)) is False
    assert output.read_bytes() == b"previous output"


def test_assembling_to_source_does_not_truncate_it(sample):
    source, metadata = sample
    original = source.read_bytes()
    store = FileStore(metadata, "sample", source_path=str(source))
    store.validate_source()
    assert store.assemble_file(str(source)) is True
    assert source.read_bytes() == original


def test_assembly_write_failure_preserves_output_and_cleans_temp(sample, tmp_path, monkeypatch):
    store = filled_store(sample, tmp_path)
    output = tmp_path / "output.bin"
    output.write_bytes(b"previous output")
    original_read = store.read_piece

    def read(index):
        if index == 1:
            raise OSError("simulated disk error")
        return original_read(index)

    monkeypatch.setattr(store, "read_piece", read)
    before = set(tmp_path.iterdir())
    with pytest.raises(OSError):
        store.assemble_file(str(output))
    assert output.read_bytes() == b"previous output"
    assert set(tmp_path.iterdir()) == before


def test_storage_failure_does_not_publish_have(sample, tmp_path):
    store = FileStore(sample[1], "sample", str(tmp_path / "pieces"))
    # A directory at the target file path forces an actual filesystem error.
    (store.pieces_dir / "0.piece").mkdir()
    with pytest.raises(OSError):
        store.verify_and_store(0, b"ABCDE")
    assert store.get_bitfield() == [0] * store.metadata.num_pieces


@pytest.mark.parametrize("size", [1, 5, 6, 65535, 65536, 65537, 131073])
def test_binary_storage_workflow_across_boundaries(tmp_path, size):
    data = random.Random(size).randbytes(size)
    source = tmp_path / "binary.dat"
    source.write_bytes(data)
    metadata = create_metadata(str(source))
    path = tmp_path / "metadata.json"
    save_metadata(metadata, str(path))
    loaded, file_id = load_metadata(str(path))
    assert file_id == hashlib.sha256(path.read_bytes()).hexdigest()
    assert loaded.file_sha256 == hashlib.sha256(data).hexdigest()
    assert calc_num_pieces(size, loaded.piece_size) == loaded.num_pieces
    store = FileStore(loaded, file_id, str(tmp_path / "pieces"))
    pieces = list(split_file(str(source)))
    for index, piece in reversed(pieces):
        assert len(piece) == loaded.expected_piece_size(index)
        assert store.verify_and_store(index, piece)
    output = tmp_path / "assembled.dat"
    assert store.assemble_file(str(output))
    assert output.read_bytes() == data


@pytest.mark.parametrize("size", [-1, True, 2.5])
def test_picker_rejects_invalid_piece_count(size):
    with pytest.raises(ValueError):
        PiecePicker(size)


def test_peer_state_owns_its_remote_bitfield_snapshot(sample):
    state = PeerState("local", 9000, sample[1])
    bits = [0, 0, 0]
    state.set_peer_bitfield("remote", bits)
    state.update_peer_has_piece("remote", 1)
    assert bits == [0, 0, 0]
    assert state.peer_bitfields["remote"] == [0, 1, 0]


@pytest.mark.parametrize("index", [-1, True, 3])
def test_peer_state_invalid_add_leaves_state_unchanged(sample, index):
    state = PeerState("local", 9000, sample[1])
    with pytest.raises(IndexError):
        state.add_piece(index, b"x")
    assert state.pieces == {}
    assert state.bitfield == [0] * 3


def test_peer_state_have_returns_bool(sample):
    state = PeerState("local", 9000, sample[1])
    assert state.have_piece(0) is False
    state.add_piece(0, b"ABCDE")
    assert state.have_piece(0) is True


def test_permission_flags_are_directional():
    neighbor = NeighborInfo("connection", "remote")
    assert not neighbor.can_download() and not neighbor.can_upload()
    neighbor.am_interested = True
    neighbor.peer_choking = False
    assert neighbor.can_download() and not neighbor.can_upload()
    neighbor.peer_interested = True
    neighbor.am_choking = False
    assert neighbor.can_download() and neighbor.can_upload()


def test_request_deadline_boundary(monkeypatch):
    request = PendingRequest(1, 0, "c", deadline=10)
    monkeypatch.setattr("bittorrent_lite.types.time.monotonic", lambda: 11)
    assert request.is_expired()
    request.deadline = 0
    assert not request.is_expired()


@pytest.mark.parametrize("message,fields", [
    (messages.Handshake(1, "a" * 64, "p"), {"protocol_version": 1, "file_id": "a" * 64, "peer_id": "p"}),
    (messages.BitfieldMsg([1, 0, 1]), {"pieces": [1, 0, 1]}),
    (messages.Have(2), {"piece_index": 2}),
    (messages.Interested(), {}), (messages.NotInterested(), {}),
    (messages.Choke(), {}), (messages.Unchoke(), {}),
    (messages.Request(7, 2), {"request_id": 7, "piece_index": 2}),
    (messages.Piece(7, 2, b"\x00\xff"), {"request_id": 7, "piece_index": 2, "payload_length": 2}),
    (messages.Cancel(7, 2), {"request_id": 7, "piece_index": 2}),
    (messages.Reject(7, 2, "busy"), {"request_id": 7, "piece_index": 2, "reason": "busy"}),
])
def test_existing_message_headers_and_binary_payload(message, fields):
    expected = {"type": message.type, **fields}
    assert message.to_header() == expected
    header = json.loads(json.dumps(expected))
    decoded = messages.MESSAGE_REGISTRY[header["type"]].from_header(header, message.payload)
    assert decoded == message
    assert decoded.payload == message.payload


def test_metadata_cli_creates_loadable_file(sample, tmp_path):
    source, _ = sample
    output = tmp_path / "cli.json"
    result = subprocess.run([
        sys.executable, "-m", "bittorrent_lite.scripts.generate_metadata",
        "--file", str(source), "--output", str(output), "--piece-size", "5",
    ], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert output.exists(), result.stdout
    metadata, _ = load_metadata(str(output))
    assert metadata == sample[1]


def test_metadata_cli_invalid_input_returns_failure(tmp_path):
    output = tmp_path / "cli.json"
    result = subprocess.run([
        sys.executable, "-m", "bittorrent_lite.scripts.generate_metadata",
        "--file", str(tmp_path / "missing"), "--output", str(output),
    ], capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert not output.exists()


def test_metadata_cli_refuses_to_overwrite_source(sample):
    source, _ = sample
    original = source.read_bytes()
    result = subprocess.run([
        sys.executable, "-m", "bittorrent_lite.scripts.generate_metadata",
        "--file", str(source), "--output", str(source),
    ], capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert source.read_bytes() == original


def test_invalid_metadata_save_preserves_existing_file(sample, tmp_path):
    target = tmp_path / "metadata.json"
    target.write_bytes(b"previous metadata")
    with pytest.raises(ValueError):
        save_metadata(replace(sample[1], file_sha256="invalid"), str(target))
    assert target.read_bytes() == b"previous metadata"


@pytest.mark.parametrize("bits", [[1], [1, 2, 0], [0, "1", 0]])
def test_invalid_peer_bitfield_leaves_snapshot_unchanged(sample, bits):
    state = PeerState("local", 9000, sample[1])
    state.set_peer_bitfield("remote", [1, 0, 0])
    with pytest.raises(ValueError):
        state.set_peer_bitfield("remote", bits)
    assert state.peer_bitfields["remote"] == [1, 0, 0]


@pytest.mark.parametrize("seed", range(8))
def test_randomized_picker_state_and_selection(seed):
    rng = random.Random(seed)
    picker = PiecePicker(17)
    neighbors = {}
    for _ in range(400):
        peer = f"peer-{rng.randrange(8)}"
        action = rng.randrange(3)
        if action == 0:
            bits = [rng.randrange(2) for _ in range(17)]
            neighbors[peer] = set(i for i, bit in enumerate(bits) if bit)
            picker.update_availability(peer, bits)
        elif action == 1 and peer in neighbors:
            index = rng.randrange(17)
            neighbors[peer].add(index)
            picker.peer_has_piece(peer, index)
        else:
            neighbors.pop(peer, None)
            picker.peer_disconnected(peer, [0] * 17)
        expected = [sum(i in pieces for pieces in neighbors.values()) for i in range(17)]
        assert picker.get_availability() == expected
        owned = [rng.randrange(2) for _ in range(17)]
        reserved = set(rng.sample(range(17), 4))
        for advertised in neighbors.values():
            candidates = advertised - {i for i, bit in enumerate(owned) if bit} - reserved
            chosen = picker.pick_piece(owned, [int(i in advertised) for i in range(17)], reserved)
            if candidates:
                assert chosen in candidates
                assert expected[chosen] == min(expected[i] for i in candidates)
            else:
                assert chosen is None


def test_concurrent_picker_updates_keep_distinct_neighbor_counts():
    picker = PiecePicker(16)

    def update(index):
        peer = str(index)
        for _ in range(100):
            picker.update_availability(peer, [0] * 16)
            picker.peer_has_piece(peer, index)
            picker.peer_has_piece(peer, index)
            picker.peer_disconnected(peer, [0] * 16)
        picker.update_availability(peer, [int(i == index) for i in range(16)])

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(update, range(16)))
    assert picker.get_availability() == [1] * 16


def test_piece_replace_failure_preserves_previous_verified_bytes(sample, tmp_path, monkeypatch):
    store = filled_store(sample, tmp_path)
    piece = store.pieces_dir / "0.piece"
    before = set(store.pieces_dir.iterdir())

    def fail_replace(self, target):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(type(piece), "replace", fail_replace)
    with pytest.raises(OSError):
        store.verify_and_store(0, b"ABCDE")
    assert piece.read_bytes() == b"ABCDE"
    assert store.get_bitfield()[0] == 1
    assert set(store.pieces_dir.iterdir()) == before


def test_assembly_cannot_overwrite_piece_storage(sample, tmp_path):
    store = filled_store(sample, tmp_path)
    piece = store.pieces_dir / "0.piece"
    with pytest.raises(ValueError):
        store.assemble_file(str(piece))
    assert piece.read_bytes() == b"ABCDE"


def test_source_piece_hash_failure_does_not_publish_partial_bitfield(sample):
    source, metadata = sample
    metadata = replace(metadata, piece_hashes=[metadata.piece_hashes[0], "0" * 64, metadata.piece_hashes[2]])
    store = FileStore(metadata, "sample", source_path=str(source))
    with pytest.raises(ValueError):
        store.validate_source()
    assert store.get_bitfield() == [0, 0, 0]


def test_maximum_size_file_and_oversize_rejection(tmp_path):
    from bittorrent_lite.config import MAX_FILE_SIZE

    source = tmp_path / "maximum.bin"
    with source.open("wb") as stream:
        for _ in range(64):
            stream.write(bytes(range(256)) * 4096)
    assert source.stat().st_size == MAX_FILE_SIZE
    metadata = create_metadata(str(source))
    store = FileStore(metadata, "maximum", source_path=str(source))
    store.validate_source()
    output = tmp_path / "output.bin"
    assert store.assemble_file(str(output))
    assert output.stat().st_size == MAX_FILE_SIZE
    with source.open("ab") as stream:
        stream.write(b"x")
    with pytest.raises(ValueError):
        create_metadata(str(source))
