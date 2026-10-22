"""September master/individual-plan contracts at Prabhat's module boundaries."""
import pytest

from bittorrent_lite.scheduler import events as e
from bittorrent_lite.scheduler.adapters import SchedulerBridge
from bittorrent_lite.scheduler.upload_policy import ProjectUploadPolicy
from choking_policy import PeerInfo
from bittorrent_lite.protocol import messages as m
from tests.test_pipeline_integration import scheduler, connect
from tests.test_scheduler_integration import disk_store, response
from examples.scheduler_dependencies import ManualClock


def test_original_default_never_duplicates_and_ids_are_connection_scoped():
    c, clock, _, _, _ = scheduler(1)
    connect(c, 1, 1)
    r = c.snapshot()["pending"][0]
    c.handle_event(e.RequestSent(1, r["request_id"], 0, 0))
    connect(c, 2, 1)
    clock.advance(5)
    c.tick()
    assert len(c.snapshot()["pending"]) == 1
    assert c.snapshot()["pending"][0]["request_id"] == 1
    c.handle_event(e.Disconnected(1))
    replacement = c.snapshot()["pending"][0]
    assert (replacement["connection_id"], replacement["request_id"]) == (2, 1)


def test_choke_keeps_sent_response_acceptable_but_cancels_unsent():
    c, _, _, _, pieces = scheduler(6)
    connect(c, 1, 6)
    r = c.snapshot()["pending"][0]
    c.handle_event(e.RequestSent(1, r["request_id"], r["piece_index"], 0))
    c.handle_event(e.ChokeReceived(1))
    assert len(c.snapshot()["pending"]) == 1
    c.handle_event(response(r, pieces[r["piece_index"]]))
    assert c.snapshot()["owned"] == 1
    assert not c.snapshot()["pending"]


def test_timer_restarts_after_cooldown_without_network_events():
    c, clock, _, _, _ = scheduler(1)
    connect(c, 1, 1)
    clock.advance(5)
    c.tick()
    assert not c.snapshot()["pending"]
    clock.advance(1)
    c.tick()
    assert c.snapshot()["pending"][0]["request_id"] == 2


def test_global_rarity_precedes_source_order():
    c, _, transport, _, _ = scheduler(2)
    for cid, bits in [(1, [1, 0]), (2, [1, 1])]:
        c.handle_event(e.ConnectionReady(cid, str(cid)))
        c.handle_event(e.BitfieldReceived(cid, bits))
    # Batch the permission facts to compare candidates from both sources.
    c._on_unchoke(e.UnchokeReceived(1))
    c._on_unchoke(e.UnchokeReceived(2))
    c.schedule()
    requests = [r for r in transport.log if r[0] == "REQUEST"]
    assert requests[0][-1] == 1


def acknowledge(policy, decision, now):
    for intent in decision.intents:
        policy.acknowledge(intent.token, True, now)
    # Denies release slots before allows for replacement recipients.
    for intent in policy.tick(now).intents:
        policy.acknowledge(intent.token, True, now)


def test_interval_scores_reset_and_zero_score_rotation_is_stable():
    p = ProjectUploadPolicy()
    for pid in ("a", "b", "c", "d"):
        p.connect(PeerInfo(pid, True), 0)
    d = p.tick(0)
    assert (d.state.regular, d.state.optimistic) == (("a",), "b")
    acknowledge(p, d, 0)
    p.record_contribution("d", 100, 1)
    assert next(x for x in p.snapshot(4).peers if x.peer_id == "d").recent_bytes == 100
    d = p.tick(5)
    assert d.state.regular == ("d",)
    assert all(x.recent_bytes == 0 for x in d.state.peers)
    acknowledge(p, d, 5)
    d = p.tick(10)
    assert (d.state.regular, d.state.optimistic) == (("d",), "a")
    acknowledge(p, d, 10)
    d = p.tick(15)
    assert (d.state.regular, d.state.optimistic) == (("b",), "c")


def test_seeder_rotates_both_slots_and_completed_free_rider_stays_disabled():
    p = ProjectUploadPolicy()
    for pid in ("a", "b", "c", "d"):
        p.connect(PeerInfo(pid, True), 0)
    p.set_seeder(True, 0)
    d = p.tick(0)
    acknowledge(p, d, 0)
    d = p.tick(5)
    assert (d.state.regular, d.state.optimistic) == (("c",), "d")
    acknowledge(p, d, 5)
    p.set_upload_enabled(False, 6)
    acknowledge(p, p.tick(6), 6)
    p.set_seeder(True, 7)
    assert not any(x.desired or x.confirmed for x in p.tick(10).state.peers)


def test_full_event_queue_closes_transport_and_cleans_reservations():
    c, clock, _, _, _ = scheduler(1)
    bridge = SchedulerBridge(clock, event_capacity=2)
    closed = []
    bridge.register(1, "remote", lambda message: None, close=closed.append)
    bridge.drain(c)
    bridge.received(1, m.Have(0))
    bridge.received(1, m.Have(0))
    bridge.received(1, m.Have(0))
    assert bridge.events.qsize() == 2
    assert closed == ["event queue full"]
    bridge.drain(c)
    assert not c.snapshot()["neighbors"][1]["active"]
    assert c.snapshot()["availability"] == [0]


def make_upload(tmp_path):
    store, pieces = disk_store(tmp_path)
    for i, piece in enumerate(pieces):
        store.verify_and_store(i, piece)
    bridge = SchedulerBridge(ManualClock())
    queue, closed = [], []
    def withdraw(message):
        for i, queued in enumerate(queue):
            if queued is message:
                queue.pop(i)
                return True
        return False
    c = bridge.create_coordinator(store)
    bridge.register(1, "remote", queue.append, withdraw=withdraw, close=closed.append)
    bridge.received(1, m.Interested())
    bridge.drain(c)
    allow = next(x for x in queue if isinstance(x, m.Unchoke))
    queue.remove(allow)
    bridge.sent(1, allow)
    bridge.drain(c)
    return bridge, c, queue, closed


def test_cancel_withdraws_queued_upload_but_not_started_frame(tmp_path):
    bridge, c, queue, _ = make_upload(tmp_path)
    try:
        bridge.received(1, m.Request(1, 0))
        bridge.drain(c)
        bridge.received(1, m.Cancel(1, 0))
        bridge.drain(c)
        assert not any(isinstance(x, m.Piece) for x in queue)
        assert c.uploads.snapshot()["service"]["active_jobs"] == 0
        bridge.received(1, m.Request(2, 0))
        bridge.drain(c)
        started = next(x for x in queue if isinstance(x, m.Piece))
        queue.remove(started)
        bridge.received(1, m.Cancel(2, 0))
        bridge.drain(c)
        assert c.uploads.snapshot()["service"]["active_jobs"] == 1
        bridge.sent(1, started)
        bridge.drain(c)
        assert c.uploads.snapshot()["service"]["sent_bytes"] == len(started.payload)
    finally:
        c.uploads.shutdown()


def test_choke_withdraws_upload_and_rejects_it(tmp_path):
    bridge, c, queue, _ = make_upload(tmp_path)
    try:
        bridge.received(1, m.Request(1, 0))
        bridge.drain(c)
        c.uploads.set_upload_enabled(False)
        assert not any(isinstance(x, m.Piece) for x in queue)
        assert any(isinstance(x, m.Reject) and x.reason == "choked" for x in queue)
        assert c.uploads.snapshot()["service"]["sent_bytes"] == 0
    finally:
        c.uploads.shutdown()


@pytest.mark.parametrize("message", [m.Request(1, 1), m.Request(0, 0), m.Request(2, 999)])
def test_invalid_upload_identity_closes_session(tmp_path, message):
    bridge, c, queue, closed = make_upload(tmp_path)
    try:
        bridge.received(1, m.Request(1, 0))
        bridge.drain(c)
        bridge.received(1, message)
        bridge.drain(c)
        bridge.drain(c)
        assert closed
        assert not c.snapshot()["neighbors"][1]["active"]
        assert c.uploads.snapshot()["service"]["active_jobs"] == 0
    finally:
        c.uploads.shutdown()


def test_timeout_withdraws_exact_unsent_request(tmp_path):
    store, _ = disk_store(tmp_path)
    clock = ManualClock()
    bridge = SchedulerBridge(clock)
    queue = []
    def withdraw(message):
        queue.remove(message)
        return True
    c = bridge.create_coordinator(store)
    bridge.register(1, "remote", queue.append, withdraw=withdraw)
    bridge.received(1, m.BitfieldMsg([1] * store.metadata.num_pieces))
    bridge.received(1, m.Unchoke())
    bridge.drain(c)
    try:
        assert any(isinstance(x, m.Request) for x in queue)
        clock.advance(5)
        c.tick()
        assert not any(isinstance(x, (m.Request, m.Cancel)) for x in queue)
    finally:
        c.uploads.shutdown()


def test_final_completion_requires_successful_assembly(tmp_path):
    store, pieces = disk_store(tmp_path)
    for i, piece in enumerate(pieces):
        store.verify_and_store(i, piece)
    bridge = SchedulerBridge(ManualClock())
    c = bridge.create_coordinator(store)
    try:
        assert c.snapshot()["ready_to_assemble"] and not c.snapshot()["complete"]
        (store.pieces_dir / "0.piece").write_bytes(b"corrupt")
        assert not c.finalize_download(str(tmp_path / "result.bin"))
        assert not c.snapshot()["complete"]
        assert c.snapshot()["storage_error"]
        store.verify_and_store(0, pieces[0])
        assert c.finalize_download(str(tmp_path / "result.bin"))
        assert c.snapshot()["complete"]
        assert (tmp_path / "result.bin").read_bytes() == b"".join(pieces)
        assert not c.uploads.snapshot()["service"]["closed"]
    finally:
        c.uploads.shutdown()


def test_incomplete_file_is_stalled_not_complete(tmp_path):
    store, _ = disk_store(tmp_path)
    c = SchedulerBridge(ManualClock()).create_coordinator(store)
    try:
        assert c.snapshot()["stalled"]
        assert not c.snapshot()["complete"]
        with pytest.raises(ValueError):
            c.finalize_download(str(tmp_path / "result.bin"))
    finally:
        c.uploads.shutdown()
