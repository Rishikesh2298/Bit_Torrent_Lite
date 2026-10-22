"""Bounded upload lifecycle, source validation, fairness and worker shutdown."""
import hashlib
import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError

import pytest

from upload_service import (Manifest, ManifestError, PieceMeta, UploadConfig, UploadRequest,
                            UploadService, MemorySource, DirectorySource, DataOutput,
                            RejectOutput, load_manifest)


def fixture(pieces=(b'abcd', b'xy')):
    manifest = Manifest(tuple(PieceMeta(i, len(data), hashlib.sha256(data).hexdigest())
                              for i, data in enumerate(pieces)))
    return manifest, dict(enumerate(pieces))


def service(config=None, pieces=(b'abcd', b'xy'), source=None):
    manifest, data = fixture(pieces)
    return UploadService(manifest, source or MemorySource(manifest, data), config or UploadConfig())


def test_admission_no_read_permission_dedup_and_limits():
    reads = []
    s = service(UploadConfig(max_jobs=2, max_jobs_per_peer=1), source=lambda i: reads.append(i))
    assert s.submit(UploadRequest('a', 0), False).reason == 'permission_denied'
    assert s.submit(UploadRequest('a', True), True).reason == 'invalid_request'
    assert s.submit(UploadRequest('a', 4), True).reason == 'unknown_piece'
    a = s.submit(UploadRequest('a', 0), True)
    assert a.accepted
    assert s.submit(UploadRequest('a', 0), True).reason == 'duplicate'
    assert s.submit(UploadRequest('a', 1), True).reason == 'peer_limit'
    assert s.submit(UploadRequest('b', 0), True).accepted
    assert s.submit(UploadRequest('c', 0), True).reason == 'global_limit'
    assert reads == []
    assert s.snapshot().rejected_requests == 6
    s.shutdown()


def test_acknowledgement_holds_capacity_and_counts_only_full_data():
    s = service(UploadConfig(max_output_records=1, max_output_bytes=4, max_read_bytes=4))
    a = s.submit(UploadRequest('a', 0), True)
    b = s.submit(UploadRequest('b', 1), True)
    s.tick()
    assert s.mark_sent(a.job_id, 4) == 'not_delivered'
    output, = s.poll_outputs()
    assert isinstance(output, DataOutput)
    assert s.poll_outputs() == ()
    assert s.cancel(a.job_id) == 'too_late'
    assert s.mark_sent(a.job_id, 3) == 'invalid_byte_count'
    assert s.mark_sent(a.job_id, True) == 'invalid_byte_count'
    assert s.snapshot().sent_bytes == 0
    assert s.snapshot().reserved_output_bytes == 4
    s.tick()
    assert s.snapshot().queued_jobs == 1
    assert s.mark_sent(a.job_id, 4) == 'ok'
    assert s.mark_sent(a.job_id, 4) == 'unknown_job'
    s.tick()
    output, = s.poll_outputs()
    assert output.job_id == b.job_id
    assert s.mark_failed(b.job_id) == 'ok'
    snap = s.snapshot()
    assert snap.sent_bytes == 4 and snap.sent_pieces == 1 and snap.failed_sends == 1
    assert snap.active_jobs == snap.output_slots == snap.reserved_output_bytes == 0
    s.shutdown()


@pytest.mark.parametrize('source,reason', [
    (lambda i: bytearray(b'abcd'), 'invalid_source_data'),
    (lambda i: b'x', 'length_mismatch'), (lambda i: b'xxxx', 'hash_mismatch'),
    (lambda i: (_ for _ in ()).throw(OSError('private detail')), 'source_error')])
def test_source_failures_are_bounded_rejections(source, reason):
    s = service(source=source)
    s.submit(UploadRequest('a', 0), True)
    s.tick()
    output, = s.poll_outputs()
    assert isinstance(output, RejectOutput) and output.reason == reason
    assert 'private' not in repr(output)
    assert s.snapshot().output_slots == 1
    assert s.snapshot().reserved_output_bytes == s.snapshot().reserved_read_bytes == 0
    assert s.mark_failed(output.job_id) == 'ok'
    assert s.snapshot().failed_sends == 0 and s.snapshot().source_failures == 1
    s.shutdown()


def test_round_robin_fairness_and_small_piece_skips_unaffordable_peer():
    s = service(UploadConfig(max_output_bytes=6, max_read_bytes=6))
    for peer, piece in [('a', 0), ('a', 1), ('b', 0), ('c', 1)]:
        s.submit(UploadRequest(peer, piece), True)
    s.tick()
    outputs = s.poll_outputs()
    assert [(r.peer_id, r.piece) for r in outputs] == [('a', 0), ('c', 1)]
    assert s.snapshot().queued_jobs == 2
    for out in outputs:
        s.mark_sent(out.job_id, len(out.data))
    s.tick()
    assert [(r.peer_id, r.piece) for r in s.poll_outputs()] == [('a', 1), ('b', 0)]
    s.shutdown()


def test_cancel_queued_ready_and_shutdown_delivered():
    s = service()
    a = s.submit(UploadRequest('a', 0), True)
    assert s.cancel(a.job_id) == 'cancelled'
    assert s.cancel(a.job_id) == 'unknown_job'
    b = s.submit(UploadRequest('a', 1), True)
    s.tick()
    assert s.cancel(b.job_id) == 'cancelled'
    assert s.poll_outputs() == ()
    c = s.submit(UploadRequest('a', 0), True)
    s.tick()
    s.poll_outputs()
    s.shutdown()
    s.shutdown()
    assert s.mark_sent(c.job_id, 4) == 'unknown_job'
    assert s.submit(UploadRequest('a', 0), True).reason == 'closed'
    assert s.snapshot().cancelled_jobs == 3
    assert s.snapshot().active_jobs == 0


def test_two_workers_bound_reads_cancellation_and_nonblocking_shutdown():
    gate = threading.Event()
    started = [threading.Event(), threading.Event()]
    lock = threading.Lock()
    calls = []
    def read(index):
        with lock:
            slot = len(calls)
            calls.append(index)
        if slot < 2:
            started[slot].set()
        assert gate.wait(5), 'worker gate timed out'
        return b'abcd'
    s = service(UploadConfig(workers=2), source=read)
    try:
        jobs = [s.submit(UploadRequest(str(i), 0), True).job_id for i in range(5)]
        s.tick(8)
        assert all(event.wait(2) for event in started)
        assert len(calls) == 2
        assert s.snapshot().reading_jobs == 2 and s.snapshot().queued_jobs == 3
        assert s.snapshot().reserved_read_bytes == s.snapshot().reserved_output_bytes == 8
        assert s.cancel(jobs[0]) == s.cancel(jobs[0]) == 'cancelled'
        assert s.snapshot().active_jobs == 5
        begin = time.monotonic()
        s.shutdown(wait=False)
        assert time.monotonic() - begin < 1
        assert s.snapshot().reading_jobs == 2
        gate.set()
        s.shutdown(wait=True)
        assert s.snapshot().active_jobs == s.snapshot().reserved_output_bytes == 0
        assert s.snapshot().cancelled_jobs == 5
        assert s.poll_outputs() == ()
    finally:
        gate.set()
        s.shutdown()


def test_owner_thread_and_immutable_snapshot():
    s = service()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(RuntimeError):
            pool.submit(s.snapshot).result()
    with pytest.raises(FrozenInstanceError):
        s.snapshot().sent_bytes = 1
    with pytest.raises(ValueError):
        s.shutdown(wait=1)
    assert not s.snapshot().closed
    s.shutdown()


def test_memory_source_copies_mapping_and_rejects_boolean_keys():
    manifest, data = fixture((b'abcd',))
    source = MemorySource(manifest, data)
    data[0] = b'xxxx'
    assert source(0) == b'abcd'
    with pytest.raises(ValueError):
        MemorySource(manifest, {False: b'abcd'})
    with pytest.raises(ManifestError):
        Manifest(None)


def test_directory_source_exact_size_and_manifest_roundtrip(tmp_path):
    manifest, data = fixture()
    document = {'version': 1, 'pieces': [dict(index=p.index, length=p.length, sha256=p.sha256.upper())
                                        for p in manifest.pieces]}
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(document))
    loaded = load_manifest(path)
    assert loaded == manifest
    source = DirectorySource(loaded, tmp_path)
    for index, payload in data.items():
        (tmp_path / f'piece-{index:06d}.bin').write_bytes(payload)
    assert source(0) == data[0]
    (tmp_path / 'piece-000000.bin').write_bytes(b'abcdextra')
    with pytest.raises(ValueError):
        source(0)
    document['extra'] = 1
    path.write_text(json.dumps(document))
    with pytest.raises(ManifestError):
        load_manifest(path)


@pytest.mark.parametrize('document', [
    '{"version":1,"version":1,"pieces":[]}',
    '{"version":true,"pieces":[]}', '{bad', '[]',
    '{"version":1,"pieces":[{"index":false,"length":1,"sha256":"' + '0'*64 + '"}]}'])
def test_manifest_invalid_input(tmp_path, document):
    path = tmp_path / 'manifest.json'
    path.write_text(document)
    with pytest.raises(ManifestError):
        load_manifest(path)


@pytest.mark.parametrize('kwargs', [dict(workers=1), dict(workers=True), dict(max_jobs=0),
    dict(max_jobs=1, max_jobs_per_peer=2), dict(max_output_records=True), dict(max_piece_length=4194305)])
def test_invalid_config(kwargs):
    with pytest.raises(ValueError):
        UploadConfig(**kwargs)


def test_demo_cli_and_existing_directory_refusal(tmp_path):
    destination = tmp_path / 'demo'
    args = [sys.executable, '-m', 'upload_service', 'demo', '--directory', str(destination)]
    result = subprocess.run(args, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert 'sent_bytes=65536 sent_pieces=2' in result.stdout
    result = subprocess.run(args, text=True, capture_output=True)
    assert result.returncode == 1
