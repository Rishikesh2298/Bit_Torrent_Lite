"""Finite boundary domains for the preserved standalone follow-up contracts."""
import hashlib
import json
from dataclasses import FrozenInstanceError

import pytest

from bittorrent_lite.scheduling.request_pipeline import PipelineConfig, PipelineManager, RequestKey
from bittorrent_lite.scheduling.recovery import CapacityError, RecoveryConfig, RecoveryPolicy
from bittorrent_lite.scheduling.upload_service import (
    DirectorySource, Manifest, ManifestError, MemorySource, PieceMeta,
    UploadConfig, UploadRequest, UploadService, load_manifest,
)
from bittorrent_lite.scheduling.choking_policy import PeerInfo, Policy


def pipeline(window):
    manager = PipelineManager(8, config=PipelineConfig(window=window))
    manager.register_connection(1, "A", now=0)
    manager.set_available(1, range(8), now=0)
    manager.set_permissions(1, interested=True, unchoked=True, now=0)
    return manager


@pytest.mark.parametrize("window", [1, 2, 3, 4])
def test_each_standalone_window_counts_queued_sent_and_verifying(window):
    manager = pipeline(window)
    requests = manager.fill({1: list(range(8))}, now=0)
    assert len(requests) == window
    assert manager.reserve(1, window, now=0) is None
    assert manager.confirm_sent(requests[0].key, sent_at=0, now=0)
    assert manager.start_verification(requests[0].key, now=0)
    assert manager.reserve(1, window, now=0) is None
    assert manager.snapshot()["outstanding"] == [{"connection_id": 1, "count": window}]
    completed = manager.finish_verification(requests[0].key, valid=True, now=0)
    assert [(outcome.kind, outcome.key) for outcome in completed] == [("completed", requests[0].key)]
    assert manager.reserve(1, window, now=0) is not None
    assert manager.snapshot()["outstanding"][0]["count"] == window


@pytest.mark.parametrize("sent", [False, True], ids=["queued", "sent"])
@pytest.mark.parametrize("delta", [-0.001, 0, 0.001], ids=["before", "at", "after"])
def test_default_pipeline_deadline_exact_boundary(sent, delta):
    manager = pipeline(1)
    request = manager.reserve(1, 0, now=0)
    if sent:
        manager.confirm_sent(request.key, sent_at=1, now=1)
    deadline = 11 if sent else 5
    outcomes = manager.expire(now=deadline + delta)
    if delta < 0:
        assert outcomes == ()
        assert manager.snapshot()["pending"][0]["request_id"] == request.key.request_id
    else:
        assert [(row.key, row.reason) for row in outcomes] == [(
            request.key, "response_timeout" if sent else "send_unconfirmed")]
        assert manager.snapshot()["pending"] == []
        assert manager.snapshot()["outstanding"][0]["count"] == 0


@pytest.mark.parametrize("field", ["connection_id", "request_id", "piece_index"])
def test_stale_identity_field_cannot_release_live_request(field):
    manager = pipeline(1)
    request = manager.reserve(1, 0, now=0)
    fields = request.key.to_dict()
    fields[field] += 1
    wrong = RequestKey(**fields)
    before = manager.snapshot()
    assert manager.reject(wrong, now=0) == ()
    assert manager.cancel(wrong, reason="stale", now=0) == ()
    assert manager.send_failed(wrong, reason="stale", now=0) == ()
    assert not manager.start_verification(wrong, now=0)
    assert manager.snapshot() == before


def test_pipeline_snapshots_and_request_values_are_detached():
    manager = pipeline(1)
    request = manager.reserve(1, 0, now=0)
    before = manager.snapshot()
    mutated = manager.snapshot()
    mutated["connections"][0]["available"].clear()
    mutated["pending"][0]["piece_index"] = 7
    mutated["counters"]["issued"] = -1
    assert manager.snapshot() == before
    with pytest.raises(FrozenInstanceError):
        request.queued_at = 100


@pytest.mark.parametrize("missing", [0, 1, 3, 4, 5])
@pytest.mark.parametrize("age", [4.999, 5, 5.001], ids=["before", "at", "after"])
def test_recovery_default_endgame_threshold_and_age(missing, age):
    policy = RecoveryPolicy(5)
    assert policy.allow_duplicate(
        now=age, piece=0, provider="B", missing_count=missing,
        no_unreserved_candidates=True,
        pending=[{"request_id": 1, "provider": "A", "piece": 0,
                  "queued_at": 0, "sent_at": 0, "verifying": False}],
    ) is (1 <= missing <= 4 and age >= 5)


@pytest.mark.parametrize("limit,maximum", [("providers", 256), ("entries", 4096)])
def test_recovery_default_capacity_boundaries_never_evict_penalties(limit, maximum):
    policy = RecoveryPolicy(maximum + 1)
    for index in range(maximum):
        provider = f"A-{index}" if limit == "providers" else "A"
        policy.failed(now=0, provider=provider, piece=index, kind="invalid_piece")
        if index + 1 in (maximum - 1, maximum):
            snapshot = policy.snapshot(now=0)
            key = "penalty_provider_count" if limit == "providers" else "penalty_entry_count"
            assert snapshot[key] == index + 1
    before = policy.snapshot(now=0)
    provider = f"A-{maximum}" if limit == "providers" else "A"
    with pytest.raises(CapacityError):
        policy.failed(now=1, provider=provider, piece=maximum, kind="reject")
    assert policy.snapshot(now=0) == before  # failed capacity did not advance time
    assert all(row["excluded"] for row in before["penalties"])
    policy.succeeded(now=0, provider="winner", piece=0)
    policy.failed(now=0, provider=provider, piece=maximum, kind="reject")
    assert policy.snapshot(now=0)["penalty_entry_count"] == maximum


@pytest.mark.parametrize("count", [255, 256, 257])
def test_recovery_default_recent_history_boundary(count):
    policy = RecoveryPolicy(1)
    for index in range(count):
        policy.failed(now=index, provider="A", piece=0, kind="disconnect")
    snapshot = policy.snapshot(now=count)
    assert len(snapshot["recent_events"]) == min(count, 256)
    assert snapshot["omitted_events"] == max(0, count - 256)
    assert snapshot["counters"]["disconnect"] == count
    assert [event["seq"] for event in snapshot["recent_events"]] == list(range(max(0, count - 256), count))


@pytest.mark.parametrize("length", [0, 1, 4194303, 4194304, 4194305])
def test_upload_piece_length_boundary(length):
    if 1 <= length <= 4194304:
        piece = PieceMeta(0, length, "A" * 64)
        assert piece.length == length and piece.sha256 == "a" * 64
    else:
        with pytest.raises(ManifestError):
            PieceMeta(0, length, "A" * 64)


@pytest.mark.parametrize("count", [0, 1, 4095, 4096, 4097])
def test_upload_manifest_piece_count_boundary(count):
    pieces = tuple(PieceMeta(index, 1, "0" * 64) for index in range(count))
    if 1 <= count <= 4096:
        assert len(Manifest(pieces)) == count
    else:
        with pytest.raises(ManifestError):
            Manifest(pieces)


@pytest.mark.parametrize("size", [1048575, 1048576, 1048577])
def test_upload_manifest_input_byte_boundary(tmp_path, size):
    document = json.dumps({"version": 1, "pieces": [{"index": 0, "length": 1, "sha256": "A" * 64}]}).encode()
    target = tmp_path / "manifest.json"
    target.write_bytes(document + b" " * (size - len(document)))
    assert target.stat().st_size == size
    if size <= 1048576:
        assert load_manifest(target).pieces == (PieceMeta(0, 1, "a" * 64),)
    else:
        with pytest.raises(ManifestError, match="larger than 1 MiB"):
            load_manifest(target)


@pytest.mark.parametrize("indices", [(0, 0), (1,), (1, 0)], ids=["duplicate", "missing-zero", "wrong-order"])
def test_upload_manifest_rejects_duplicate_missing_and_unordered_indices(indices):
    with pytest.raises(ManifestError):
        Manifest(tuple(PieceMeta(index, 1, "0" * 64) for index in indices))


@pytest.mark.parametrize("raw", [
    b"null", b"[]", b"1", b'"text"', b"\xff", b"\xef\xbb\xbf{}",
    b'{"version":1,"pieces":[] ,"version":1}',
    b'{"version":NaN,"pieces":[]}', b'{"version":Infinity,"pieces":[]}',
    b'{"version":1,"pieces":[],"extra":0}', b'{"version":1}',
    b"[" * 2000 + b"0" + b"]" * 2000,
], ids=["null", "array", "integer", "string", "utf8", "bom", "duplicate-key",
        "nan", "infinity", "extra", "missing", "deep"])
def test_upload_manifest_parser_rejection_is_controlled(tmp_path, raw):
    path = tmp_path / "invalid.json"
    path.write_bytes(raw)
    with pytest.raises(ManifestError):
        load_manifest(path)
    assert path.read_bytes() == raw


@pytest.mark.parametrize("length", [1, 4194304])
def test_upload_boundary_piece_delivery_counts_only_acknowledged_bytes(length):
    payload = b"\xff" * length
    manifest = Manifest((PieceMeta(0, length, hashlib.sha256(payload).hexdigest()),))
    source = MemorySource(manifest, {0: payload})
    service = UploadService(manifest, source, UploadConfig(max_output_bytes=length, max_read_bytes=length))
    try:
        admitted = service.submit(UploadRequest("A", 0), True)
        assert admitted.accepted
        service.tick()
        output, = service.poll_outputs()
        assert output.data == payload
        assert service.snapshot().sent_bytes == 0
        assert service.mark_sent(output.job_id, length - 1) == "invalid_byte_count"
        assert service.snapshot().reserved_output_bytes == length
        assert service.mark_sent(output.job_id, length) == "ok"
        assert service.snapshot().sent_bytes == length
        assert service.snapshot().active_jobs == service.snapshot().reserved_output_bytes == 0
    finally:
        service.shutdown()


@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_directory_source_exact_length_and_one_extra_byte(tmp_path, delta):
    manifest = Manifest((PieceMeta(0, 4, "0" * 64),))
    payload = b"abcdx"[:4 + delta]
    target = tmp_path / "piece-000000.bin"
    target.write_bytes(payload)
    source = DirectorySource(manifest, tmp_path)
    if delta == 0:
        assert source(0) == payload
    else:
        with pytest.raises(ValueError, match="length"):
            source(0)
    assert target.read_bytes() == payload


@pytest.mark.parametrize("count", [127, 128, 129])
def test_choking_default_peer_capacity_and_failed_admission_atomicity(count):
    policy = Policy()
    for index in range(min(count, 128)):
        policy.connect(PeerInfo(f"peer-{index}"), 0)
    if count == 129:
        before = policy.snapshot(0)
        with pytest.raises(OverflowError):
            policy.connect(PeerInfo("extra"), 1)
        assert policy.snapshot(0) == before
    assert len(policy.snapshot(0).peers) == min(count, 128)


@pytest.mark.parametrize("at", [9.999, 10, 10.001])
def test_choking_confirmation_overdue_boundary_retains_reservation(at):
    # Follow-up Part 5 says "exceeding", not "at or beyond", the timeout.
    policy = Policy()
    policy.connect(PeerInfo("A", True), 0)
    intent, = policy.tick(0).intents
    state = policy.tick(at).state
    assert len([event for event in state.diagnostics if event.code == "confirmation_overdue"]) == int(at > 10)
    assert state.peers[0].pending == intent
    assert state.peers[0].reserved and not state.peers[0].confirmed
    assert policy.acknowledge(intent.token, True, at)
    assert policy.snapshot(at).peers[0].confirmed


@pytest.mark.parametrize("byte_count", [0, 1, 16777216, 16777217, True])
def test_choking_contribution_input_boundary_is_atomic(byte_count):
    policy = Policy()
    policy.connect(PeerInfo("A"), 0)
    if type(byte_count) is int and 1 <= byte_count <= 16777216:
        policy.record_contribution("A", byte_count, 0)
        assert policy.snapshot(0).peers[0].recent_bytes == byte_count
    else:
        before = policy.snapshot(0)
        with pytest.raises(ValueError):
            policy.record_contribution("A", byte_count, 1)
        assert policy.snapshot(0) == before
