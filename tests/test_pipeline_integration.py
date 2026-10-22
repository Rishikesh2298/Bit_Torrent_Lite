"""Part 2 wiring: real storage/bridge and multi-peer lifecycle fault cases."""
import random

import pytest

from bittorrent_lite.scheduler import Coordinator, SchedulerConfig
from bittorrent_lite.scheduler import events as e
from bittorrent_lite.scheduler.adapters import SchedulerBridge, FileStoreAdapter
from bittorrent_lite.protocol import messages as m
from examples.scheduler_dependencies import ManualClock, RecordingTransport, InMemoryStore, make_file
from tests.test_scheduler_integration import disk_store, response


def scheduler(n=30, transport=None, config=None):
    pieces, hashes = make_file(n, 8)
    clock = ManualClock()
    transport = transport or RecordingTransport()
    store = InMemoryStore(hashes, 8)
    c = Coordinator(n, transport, store, clock, config, rng=random.Random(42))
    return c, clock, transport, store, pieces


def connect(c, cid, n, peer=None):
    c.handle_event(e.ConnectionReady(cid, peer or f"peer-{cid}"))
    c.handle_event(e.BitfieldReceived(cid, [True] * n))
    c.handle_event(e.UnchokeReceived(cid))


def test_default_four_slots_six_peers_and_refill():
    c, _, _, _, pieces = scheduler()
    for cid in range(1, 7):
        connect(c, cid, 30)
    snap = c.snapshot()
    assert len(snap["pending"]) == 24
    assert len({r["piece_index"] for r in snap["pending"]}) == 24
    assert all(n["outstanding"] == 4 for n in snap["neighbors"].values())
    r = snap["pending"][0]
    c.handle_event(response(r, pieces[r["piece_index"]]))
    snap = c.snapshot()
    assert snap["owned"] == 1
    assert len(snap["pending"]) == 24
    assert snap["pipeline_counters"]["completed"] == 1
    assert (r["connection_id"], r["request_id"]) not in {
        (p["connection_id"], p["request_id"]) for p in snap["pending"]}


def test_ten_peer_cap_duplicate_provider_and_reconnect():
    c, *_ = scheduler(60)
    for cid in range(1, 11):
        connect(c, cid, 60)
    assert len(c.snapshot()["pending"]) == 40
    c.handle_event(e.ConnectionReady(11, "eleven"))
    assert 11 not in c.snapshot()["neighbors"]
    c.handle_event(e.Disconnected(1))
    c.handle_event(e.ConnectionReady(12, "peer-2"))
    assert 12 not in c.snapshot()["neighbors"]
    connect(c, 11, 60, "peer-1")
    assert len(c.snapshot()["pending"]) == 40
    assert c.snapshot()["neighbors"][11]["active"]
    c.handle_event(e.ConnectionReady(1, "new"))
    assert not c.snapshot()["neighbors"][1]["active"]


def test_mixed_sent_unsent_deadlines_and_stale_events():
    c, clock, _, _, pieces = scheduler(8)
    connect(c, 1, 8)
    original = c.snapshot()["pending"]
    clock.advance(2)
    for r in original[:2]:
        c.handle_event(e.RequestSent(1, r["request_id"], r["piece_index"], clock.now()))
    clock.advance(3)
    expired = c.tick()
    assert len(expired) == 2
    assert {r.kind for r in expired} == {"send_unconfirmed"}
    # Timer processing refills free slots with other eligible pieces.
    assert len(c.snapshot()["pending"]) == 4
    c.handle_event(response(original[2], pieces[original[2]["piece_index"]]))
    assert c.snapshot()["owned"] == 0
    clock.advance(7)
    expired = c.tick()
    assert sorted(r.kind for r in expired) == ["response_timeout"] * 2 + ["send_unconfirmed"] * 2
    assert all(r["request_id"] > 6 for r in c.snapshot()["pending"])
    assert c.snapshot()["owned"] == 0


def test_failed_enqueue_batch_is_bounded_and_released():
    class Refusing(RecordingTransport):
        def __init__(self):
            super().__init__()
            self.calls = 0
        def send_request(self, *args):
            self.calls += 1
            return False
    t = Refusing()
    c, *_ = scheduler(20, t)
    connect(c, 1, 20)
    assert t.calls == 4
    assert not c.snapshot()["pending"]
    assert c.snapshot()["piece_states"]["MISSING"] == 20
    assert c.schedule() == 0
    assert t.calls == 8


def test_choke_during_verification_keeps_winner_and_releases_other_slots():
    c, clock, _, store, pieces = scheduler(8)
    connect(c, 1, 8)
    r = c.snapshot()["pending"][0]
    original = store.verify_and_store
    def verify(index, data):
        c.handle_event(e.ChokeReceived(1))
        snap = c.snapshot()
        assert len(snap["pending"]) == 1
        assert snap["pending"][0]["verifying"]
        c.handle_event(e.RequestSendFailed(1, r["request_id"], index, "late failure"))
        clock.advance(100)
        assert not c.tick()
        return original(index, data)
    store.verify_and_store = verify
    c.handle_event(response(r, pieces[r["piece_index"]]))
    assert c.snapshot()["owned"] == 1
    assert not c.snapshot()["pending"]
    c.handle_event(e.UnchokeReceived(1))
    assert len(c.snapshot()["pending"]) == 4


def test_storage_error_pauses_refills_without_losing_other_pending_work():
    c, _, _, store, pieces = scheduler(8)
    connect(c, 1, 8)
    store.fail_io = True
    r = c.snapshot()["pending"][0]
    c.handle_event(response(r, pieces[r["piece_index"]]))
    assert c.snapshot()["paused"]
    assert len(c.snapshot()["pending"]) == 3
    assert c.schedule() == 0
    assert not c.snapshot()["invalid_pieces"]
    store.fail_io = False
    c.resume_after_storage_error()
    assert len(c.snapshot()["pending"]) == 4


def test_rarest_first_is_preserved_in_pipeline_candidate_orders():
    c, *_ = scheduler(8)
    c.handle_event(e.ConnectionReady(1, "one"))
    c.handle_event(e.BitfieldReceived(1, [True] * 8))
    c.handle_event(e.ConnectionReady(2, "two"))
    c.handle_event(e.BitfieldReceived(2, [True] * 7 + [False]))
    c.handle_event(e.UnchokeReceived(1))
    assert c.snapshot()["pending"][0]["piece_index"] == 7


def test_four_slot_bridge_out_of_order_corrupt_retry_and_disk_assembly(tmp_path):
    data = bytes(range(251)) * 3
    store, pieces = disk_store(tmp_path, data=data, size=64)
    clock = ManualClock()
    bridge = SchedulerBridge(clock)
    outgoing = []
    c = Coordinator(len(pieces), bridge, FileStoreAdapter(store), clock)
    bridge.register(1, "source", outgoing.append)
    bridge.received(1, m.BitfieldMsg([True] * len(pieces)))
    bridge.received(1, m.Unchoke())
    bridge.drain(c)
    assert len(c.snapshot()["pending"]) == 4
    # Recovery excludes corrupt providers for the affected piece. Supply a
    # second independent source for that piece instead of retrying corruption.
    backup = []
    bridge.register(2, "backup", backup.append)
    bridge.received(2, m.BitfieldMsg([True] * len(pieces)))
    bridge.received(2, m.Unchoke())
    bridge.drain(c)
    corrupted = False
    for _ in range(20):
        batch = [(1, msg) for msg in outgoing if isinstance(msg, m.Request)]
        batch += [(2, msg) for msg in backup if isinstance(msg, m.Request)]
        outgoing.clear()
        backup.clear()
        if c.snapshot()["ready_to_assemble"]:
            break
        assert batch, "download stalled"
        assert all(n["outstanding"] <= 4 for n in c.snapshot()["neighbors"].values())
        for cid, req in reversed(batch):
            bridge.sent(cid, req)
            payload = pieces[req.piece_index]
            if not corrupted:
                payload = b"corrupt"
                corrupted = True
            bridge.received(cid, m.Piece(req.request_id, req.piece_index, payload))
            # Duplicate responses must not create ownership or release other slots.
            bridge.received(cid, m.Piece(req.request_id, req.piece_index, payload))
        bridge.drain(c)
    assert c.snapshot()["ready_to_assemble"]
    assert not c.snapshot()["pending"]
    assert c.snapshot()["pipeline_counters"]["invalid"] == 1
    assert c.snapshot()["pipeline_counters"]["completed"] == len(pieces)
    assert store.assemble_file(str(tmp_path / "assembled.bin"))
    assert (tmp_path / "assembled.bin").read_bytes() == data


@pytest.mark.parametrize("kwargs", [dict(request_window=5), dict(max_connections=0),
                                      dict(max_connections=True)])
def test_scheduler_validates_pipeline_limits(kwargs):
    with pytest.raises(ValueError):
        SchedulerConfig(**kwargs)
