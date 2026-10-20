"""Combined Part 4: upload permissions, transport ACKs, bounded reads and downloads."""
import threading
import time

import pytest

from choking_policy import Config as ChokingConfig
from upload_service import UploadConfig
from bittorrent_lite.scheduler.adapters import SchedulerBridge
from bittorrent_lite.scheduler.uploads import UploadController, FileStoreUploadSource
from bittorrent_lite.protocol import messages as m
from examples.scheduler_dependencies import ManualClock
from tests.test_scheduler_integration import disk_store


def setup(tmp_path, *, upload_config=None, sender=None, data=b'abcdefghijkl', size=4):
    store, pieces = disk_store(tmp_path, data=data, size=size)
    for i, piece in enumerate(pieces):
        assert store.verify_and_store(i, piece)
    clock = ManualClock()
    bridge = SchedulerBridge(clock)
    out = []
    coordinator = bridge.create_coordinator(store, upload_config=upload_config)
    bridge.register(1, 'remote', sender or out.append)
    bridge.drain(coordinator)
    return store, pieces, clock, bridge, coordinator, out


def grant(bridge, c, out):
    bridge.received(1, m.Interested())
    bridge.drain(c)
    command = next(message for message in out if isinstance(message, m.Unchoke))
    bridge.sent(1, command)
    bridge.drain(c)
    return command


def test_unconfirmed_permission_denies_read_and_full_write_counts_once(tmp_path):
    store, pieces, clock, bridge, c, out = setup(tmp_path)
    bridge.received(1, m.Interested())
    bridge.drain(c)
    unchoke = next(message for message in out if isinstance(message, m.Unchoke))
    assert c.snapshot()['neighbors'][1]['am_choking']
    bridge.received(1, m.Request(1, 0))
    bridge.drain(c)
    assert any(isinstance(message, m.Reject) and message.reason == 'choked' for message in out)
    assert c.uploads.snapshot()['service']['active_jobs'] == 0
    bridge.sent(1, unchoke)
    bridge.drain(c)
    assert not c.snapshot()['neighbors'][1]['am_choking']
    bridge.received(1, m.Request(2, 0))
    bridge.drain(c)
    piece = next(message for message in out if isinstance(message, m.Piece))
    assert piece.payload == pieces[0] and piece.request_id == 2
    assert c.uploads.snapshot()['service']['sent_bytes'] == 0
    assert c.uploads.snapshot()['service']['reserved_output_bytes'] == 4
    # A reconstructed message or wrong connection is not an acknowledgement.
    bridge.sent(1, m.Piece(2, 0, piece.payload))
    bridge.sent(2, piece)
    bridge.drain(c)
    assert c.uploads.snapshot()['service']['sent_bytes'] == 0
    bridge.sent(1, piece)
    bridge.sent(1, piece)
    bridge.drain(c)
    assert c.uploads.snapshot()['service']['sent_bytes'] == 4
    assert c.uploads.snapshot()['service']['active_jobs'] == 0
    c.uploads.shutdown()


def test_failed_data_enqueue_and_partial_write_do_not_count_bytes(tmp_path):
    _, _, _, bridge, c, out = setup(tmp_path)
    grant(bridge, c, out)
    bridge.received(1, m.Request(1, 0))
    bridge.drain(c)
    piece = next(message for message in out if isinstance(message, m.Piece))
    bridge.send_failed(1, piece, 'partial write then closed')
    bridge.disconnected(1)
    bridge.drain(c)
    snap = c.uploads.snapshot()
    assert snap['service']['sent_bytes'] == 0
    assert snap['service']['failed_sends'] == 1
    assert snap['service']['active_jobs'] == snap['pending_sends'] == 0
    bridge.sent(1, piece)
    bridge.drain(c)
    assert c.uploads.snapshot()['service']['sent_bytes'] == 0
    c.uploads.shutdown()


def test_duplicate_request_and_cancel_exact_identity_with_output_backpressure(tmp_path):
    cfg = UploadConfig(max_output_records=1)
    _, _, _, bridge, c, out = setup(tmp_path, upload_config=cfg)
    grant(bridge, c, out)
    bridge.received(1, m.Request(1, 0))
    bridge.received(1, m.Request(1, 0))
    bridge.received(1, m.Request(2, 1))
    bridge.drain(c)
    assert c.uploads.snapshot()['service']['active_jobs'] == 2
    assert len([x for x in out if isinstance(x, m.Piece)]) == 1
    bridge.received(1, m.Cancel(2, 0))  # mismatched piece cannot cancel job 2
    bridge.drain(c)
    assert c.uploads.snapshot()['service']['queued_jobs'] == 1
    bridge.received(1, m.Cancel(2, 1))
    bridge.drain(c)
    assert c.uploads.snapshot()['service']['active_jobs'] == 1
    bridge.received(1, m.Cancel(1, 0))  # already handed to transport: too late
    bridge.drain(c)
    assert c.uploads.snapshot()['service']['active_jobs'] == 1
    piece = next(x for x in out if isinstance(x, m.Piece))
    bridge.sent(1, piece)
    bridge.drain(c)
    assert c.uploads.snapshot()['tracked_jobs'] == 0
    bridge.received(1, m.Request(1, 0))
    bridge.drain(c)
    bridge.drain(c)  # reconcile protocol-error closure
    assert not c.snapshot()['neighbors'][1]['active']
    c.uploads.shutdown()


def test_disable_uploads_cancels_queued_work_and_waits_for_deny_ack(tmp_path):
    _, _, _, bridge, c, out = setup(tmp_path, upload_config=UploadConfig(max_output_records=1))
    grant(bridge, c, out)
    bridge.received(1, m.Request(1, 0))
    bridge.received(1, m.Request(2, 1))
    bridge.drain(c)
    c.uploads.set_upload_enabled(False)
    snap = c.uploads.snapshot()
    assert snap['service']['queued_jobs'] == 0
    assert snap['service']['active_jobs'] == 1  # delivered cannot be recalled
    assert snap['policy']['peers'][0]['confirmed']
    deny = next(x for x in out if isinstance(x, m.Choke))
    bridge.received(1, m.Request(3, 2))
    bridge.drain(c)
    assert isinstance(out[-1], m.Reject)
    bridge.sent(1, deny)
    bridge.drain(c)
    assert not c.uploads.snapshot()['policy']['peers'][0]['confirmed']
    bridge.disconnected(1)
    bridge.drain(c)
    assert c.uploads.snapshot()['service']['active_jobs'] == 0
    c.uploads.shutdown()


def test_failed_permission_enqueue_does_not_grant_and_retries_with_new_intent(tmp_path):
    calls = []
    def send(message):
        calls.append(message)
        return False
    _, _, _, bridge, c, _ = setup(tmp_path, sender=send)
    bridge.received(1, m.Interested())
    bridge.drain(c)
    snap = c.uploads.snapshot()
    assert not snap['policy']['peers'][0]['confirmed']
    assert snap['pending_sends'] == 0
    c.tick()
    assert len([x for x in calls if isinstance(x, m.Unchoke)]) == 2
    assert c.uploads.snapshot()['policy']['diagnostics'][-1]['code'] == 'command_not_applied'
    c.uploads.shutdown()


def test_corrupt_disk_piece_is_rejected_and_never_released(tmp_path):
    store, _, _, bridge, c, out = setup(tmp_path)
    grant(bridge, c, out)
    (store.pieces_dir / '0.piece').write_bytes(b'xxxx')
    bridge.received(1, m.Request(1, 0))
    bridge.drain(c)
    reject = next(x for x in out if isinstance(x, m.Reject))
    assert reject.reason == 'unavailable'
    assert not any(isinstance(x, m.Piece) for x in out)
    bridge.sent(1, reject)
    bridge.drain(c)
    assert c.uploads.snapshot()['service']['source_failures'] == 1
    assert c.uploads.snapshot()['service']['active_jobs'] == 0
    c.uploads.shutdown()


def test_two_permission_slots_and_delayed_acks_do_not_overgrant(tmp_path):
    store, _ = disk_store(tmp_path)
    clock = ManualClock()
    sent = []
    uploads = UploadController(store, lambda cid, message: sent.append((cid, message)), clock)
    for cid in range(1, 5):
        uploads.connect(cid, str(cid))
        uploads.interested(cid, True)
    uploads.tick()
    assert len(sent) == 2
    assert all(isinstance(message, m.Unchoke) for _, message in sent)
    clock.advance(16)
    uploads.tick()
    assert len(sent) == 2  # rotation cannot assume unconfirmed allows failed
    assert sum(p['reserved'] for p in uploads.snapshot()['policy']['peers']) == 2
    for cid, message in list(sent):
        uploads.completed(cid, message, True)
    uploads.tick()
    assert sum(p['reserved'] for p in uploads.snapshot()['policy']['peers']) <= 2
    uploads.shutdown()
    for cid in range(1, 5):
        uploads.disconnect(cid)
    assert uploads.snapshot()['policy']['closed']


def test_worker_cancel_keeps_reservation_until_read_finishes(tmp_path, monkeypatch):
    entered, gate = threading.Event(), threading.Event()
    original = FileStoreUploadSource.__call__
    def blocked(self, index):
        entered.set()
        assert gate.wait(5)
        return original(self, index)
    monkeypatch.setattr(FileStoreUploadSource, '__call__', blocked)
    _, _, _, bridge, c, out = setup(tmp_path, upload_config=UploadConfig(workers=2))
    try:
        grant(bridge, c, out)
        bridge.received(1, m.Request(1, 0))
        bridge.drain(c)
        assert entered.wait(2)
        bridge.received(1, m.Cancel(1, 0))
        bridge.drain(c)
        snap = c.uploads.snapshot()
        assert snap['service']['active_jobs'] == snap['tracked_jobs'] == 1
        assert snap['service']['reserved_read_bytes'] == 4
        gate.set()
        deadline = time.monotonic() + 2
        while c.uploads.snapshot()['service']['active_jobs'] and time.monotonic() < deadline:
            c.tick()
            threading.Event().wait(.001)
        assert c.uploads.snapshot()['tracked_jobs'] == 0
        assert not any(isinstance(x, m.Piece) for x in out)
    finally:
        gate.set()
        c.uploads.shutdown()


@pytest.mark.parametrize("workers,data,size", [
    (0, b'complete bidirectional scheduler transfer', 8),
    (2, b'complete bidirectional scheduler transfer', 8),
    (2, bytes(range(256)) * 1024 + b'tail', 65536),
], ids=["synchronous", "two-workers", "two-workers-large-file"])
def test_combined_seed_upload_to_downloader_and_verified_contribution(tmp_path, workers, data, size):
    seed, pieces = disk_store(tmp_path / 'seed', data=data, size=size)
    target, _ = disk_store(tmp_path / 'target', data=data, size=size)
    for i, piece in enumerate(pieces):
        seed.verify_and_store(i, piece)
    clock = ManualClock()
    source_bridge, target_bridge = SchedulerBridge(clock), SchedulerBridge(clock)
    source = source_bridge.create_coordinator(seed, upload_config=UploadConfig(workers=workers))
    destination = target_bridge.create_coordinator(target, upload_config=UploadConfig(workers=workers))
    to_target, to_source = [], []
    source_bridge.register(1, 'downloader', to_target.append)
    target_bridge.register(1, 'seeder', to_source.append)
    source_bridge.drain(source)
    target_bridge.drain(destination)
    target_bridge.received(1, m.BitfieldMsg([True] * len(pieces)))
    target_bridge.drain(destination)
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            source.tick()
            destination.tick()
            batch = list(to_source)
            to_source.clear()
            for message in batch:
                target_bridge.sent(1, message)
                source_bridge.received(1, message)
            target_bridge.drain(destination)
            source_bridge.drain(source)
            batch = list(to_target)
            to_target.clear()
            for message in batch:
                source_bridge.sent(1, message)
                target_bridge.received(1, message)
            source_bridge.drain(source)
            target_bridge.drain(destination)
            if destination.snapshot()['ready_to_assemble']:
                break
            if workers:
                threading.Event().wait(.001)
        assert destination.snapshot()['ready_to_assemble']
        assert destination.finalize_download(str(tmp_path / 'result.bin'))
        assert (tmp_path / 'result.bin').read_bytes() == data
        assert source.uploads.snapshot()['service']['sent_bytes'] == len(data)
        policy = destination.uploads.snapshot()['policy']
        assert policy['peers'][0]['recent_bytes'] == len(data)
        assert policy['seeder']
        assert source.uploads.snapshot()['service']['active_jobs'] == 0
    finally:
        source.uploads.shutdown()
        destination.uploads.shutdown()


def test_disconnect_reconnect_old_completion_cannot_change_new_permission(tmp_path):
    _, _, _, bridge, c, out = setup(tmp_path)
    bridge.received(1, m.Interested())
    bridge.drain(c)
    old = next(x for x in out if isinstance(x, m.Unchoke))
    bridge.disconnected(1)
    bridge.drain(c)
    new_out = []
    bridge.register(2, 'remote', new_out.append)
    bridge.received(2, m.Interested())
    bridge.drain(c)
    bridge.sent(1, old)
    bridge.drain(c)
    assert not c.uploads.snapshot()['policy']['peers'][0]['confirmed']
    new = next(x for x in new_out if isinstance(x, m.Unchoke))
    bridge.sent(2, new)
    bridge.drain(c)
    assert c.uploads.snapshot()['policy']['peers'][0]['confirmed']
    c.uploads.shutdown()


def test_invalid_shutdown_preserves_live_upload_state(tmp_path):
    _, _, _, bridge, c, out = setup(tmp_path)
    grant(bridge, c, out)
    before = c.uploads.snapshot()
    try:
        with pytest.raises(ValueError):
            c.uploads.shutdown(wait=1)
        assert c.uploads.snapshot() == before
        bridge.received(1, m.Request(1, 0))
        bridge.drain(c)
        assert any(isinstance(x, m.Piece) for x in out)
    finally:
        c.uploads.shutdown()


@pytest.mark.parametrize("budget,error", [(0, ValueError), (-1, ValueError), (True, TypeError), (1.5, TypeError)])
def test_invalid_dispatch_budget_preserves_permission_state(tmp_path, budget, error):
    _, _, _, _, c, out = setup(tmp_path)
    c.uploads.interested(1, True)
    before = c.uploads.snapshot()
    try:
        with pytest.raises(error):
            c.uploads.tick(budget)
        assert c.uploads.snapshot() == before
        assert out == []
    finally:
        c.uploads.shutdown()
