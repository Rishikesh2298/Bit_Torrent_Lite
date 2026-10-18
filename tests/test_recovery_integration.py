"""Recovery policy integrated with live request accounting and protocol events."""
import pytest

from recovery_policy import RecoveryConfig
from bittorrent_lite.scheduler import Coordinator, SchedulerConfig
from bittorrent_lite.scheduler import events as e
from bittorrent_lite.scheduler.adapters import SchedulerBridge, FileStoreAdapter
from bittorrent_lite.protocol import messages as m
from examples.scheduler_dependencies import ManualClock, RecordingTransport, InMemoryStore, make_file
from tests.test_pipeline_integration import scheduler, connect
from tests.test_scheduler_integration import response, disk_store


def requests(c):
    return c.snapshot()["pending"]


def sent(c, r, clock):
    c.handle_event(e.RequestSent(r["connection_id"], r["request_id"], r["piece_index"], clock.now()))


def test_reject_backoff_exact_boundary_and_stale_event_deduplication():
    c, clock, _, _, pieces = scheduler(1)
    connect(c, 1, 1)
    for delay in (2, 4, 10, 10):
        r = requests(c)[0]
        event = e.RejectReceived(1, r["request_id"], 0)
        c.handle_event(event)
        assert requests(c) == []
        counters = c.snapshot()["recovery"]["counters"]
        c.handle_event(event)
        c.handle_event(response(r, pieces[0]))
        c.handle_event(e.RequestSendFailed(1, r["request_id"], 0, "late"))
        assert c.snapshot()["recovery"]["counters"] == counters
        clock.advance(delay - .5)
        assert c.schedule() == 0
        clock.advance(.5)
        assert c.schedule() == 1
    assert c.snapshot()["recovery"]["penalties"][0]["streak"] == 4


def test_timeout_reassigns_to_other_provider_and_preserves_reconnect_penalty():
    c, clock, _, _, _ = scheduler(1)
    connect(c, 1, 1, "source")
    r = requests(c)[0]
    sent(c, r, clock)
    clock.advance(10)
    assert c.tick()[0].kind == "response_timeout"
    c.handle_event(e.Disconnected(1))
    connect(c, 2, 1, "source")
    assert not requests(c)
    connect(c, 3, 1, "backup")
    assert requests(c)[0]["connection_id"] == 3
    assert c.snapshot()["recovery"]["penalties"][0]["provider"] == "source"


@pytest.mark.parametrize("kind", ["send_failed", "send_unconfirmed", "enqueue_failed"])
def test_local_send_failures_cool_down_without_retry_streak(kind):
    t = RecordingTransport()
    if kind == "enqueue_failed":
        t.send_request = lambda *args: False
    c, clock, _, _, _ = scheduler(1, t)
    connect(c, 1, 1)
    if kind == "send_failed":
        r = requests(c)[0]
        c.handle_event(e.RequestSendFailed(1, r["request_id"], 0, "queue closed"))
    elif kind == "send_unconfirmed":
        clock.advance(5)
        c.tick()
    assert not requests(c)
    assert c.snapshot()["recovery"]["penalties"][0]["streak"] == 0
    assert c.schedule() == 0
    if kind == "enqueue_failed":
        t.send_request = RecordingTransport.send_request.__get__(t)
    clock.advance(1)
    assert c.schedule() == 1


def endgame(transport=None, config=None):
    c, clock, t, store, pieces = scheduler(1, transport, config)
    connect(c, 1, 1)
    first = requests(c)[0]
    sent(c, first, clock)
    connect(c, 2, 1)
    clock.advance(4.99)
    assert c.schedule() == 0
    clock.advance(.01)
    assert c.schedule() == 1
    copies = requests(c)
    assert len(copies) == 2
    assert {r["connection_id"] for r in copies} == {1, 2}
    connect(c, 3, 1)
    assert len(requests(c)) == 2
    return c, clock, t, store, pieces, copies


@pytest.mark.parametrize("winner", [0, 1])
def test_endgame_winner_cancels_loser_once_and_stale_events_are_harmless(winner):
    c, clock, t, store, pieces, copies = endgame()
    win, lose = copies[winner], copies[1-winner]
    c.handle_event(response(win, pieces[0]))
    assert c.snapshot()["owned"] == 1
    assert not requests(c)
    assert c.snapshot()["recovery"]["successes"] == 1
    assert ("CANCEL", lose["connection_id"], lose["request_id"], 0) in t.log
    assert sum(row[0] == "CANCEL" for row in t.log) == 1
    counters = c.snapshot()["recovery"]["counters"]
    c.handle_event(response(lose, pieces[0]))
    c.handle_event(e.RequestSendFailed(lose["connection_id"], lose["request_id"], 0, "late"))
    clock.advance(100)
    assert not c.tick()
    assert c.snapshot()["recovery"]["counters"] == counters
    assert c.snapshot()["pipeline_counters"]["completed"] == 1


def test_invalid_duplicate_keeps_other_copy_and_success_clears_exclusions():
    c, _, _, _, pieces, copies = endgame()
    c.handle_event(response(copies[0], b"bad"))
    assert len(requests(c)) == 1
    assert requests(c)[0]["request_id"] == copies[1]["request_id"]
    assert c.snapshot()["piece_states"]["REQUESTED"] == 1
    assert c.snapshot()["recovery"]["penalties"][0]["excluded"]
    c.handle_event(response(copies[1], pieces[0]))
    assert c.snapshot()["owned"] == 1
    assert not c.snapshot()["recovery"]["penalties"]


def test_disconnect_and_choke_are_counted_only_for_removed_live_requests():
    c, *_ = scheduler(8)
    connect(c, 1, 8)
    c.handle_event(e.ChokeReceived(1))
    c.handle_event(e.ChokeReceived(1))
    assert c.snapshot()["recovery"]["counters"]["choke"] == 4
    assert not c.snapshot()["recovery"]["penalties"]
    c.handle_event(e.UnchokeReceived(1))
    c.handle_event(e.Disconnected(1))
    c.handle_event(e.Disconnected(1))
    assert c.snapshot()["recovery"]["counters"]["disconnect"] == 4


def test_capacity_failure_pauses_and_cannot_be_bypassed_by_storage_resume():
    config = SchedulerConfig(recovery=RecoveryConfig(max_penalty_entries=1))
    c, _, _, _, _ = scheduler(8, config=config)
    connect(c, 1, 8)
    a, b = requests(c)[:2]
    c.handle_event(e.RejectReceived(1, a["request_id"], a["piece_index"]))
    c.handle_event(e.RejectReceived(1, b["request_id"], b["piece_index"]))
    snap = c.snapshot()
    assert snap["paused"] and snap["recovery_error"]
    assert snap["recovery"]["penalty_entry_count"] == 1
    before = requests(c)
    assert c.schedule() == 0
    c.resume_after_storage_error()
    assert requests(c) == before
    assert c.snapshot()["paused"]


def test_capacity_failure_during_enqueue_releases_unissued_batch():
    t = RecordingTransport()
    t.send_request = lambda *args: False
    c, *_ = scheduler(8, t, SchedulerConfig(recovery=RecoveryConfig(max_penalty_entries=1)))
    connect(c, 1, 8)
    assert c.snapshot()["recovery_error"]
    assert not requests(c)
    assert c.snapshot()["piece_states"]["MISSING"] == 8


def test_disk_failure_is_not_a_provider_penalty():
    c, _, _, store, pieces, copies = endgame()
    store.fail_io = True
    c.handle_event(response(copies[0], pieces[0]))
    assert c.snapshot()["paused"]
    assert not c.snapshot()["recovery"]["penalties"]
    assert c.snapshot()["recovery"]["counters"]["invalid_piece"] == 0
    assert len(requests(c)) == 1
    store.fail_io = False
    c.handle_event(response(copies[1], pieces[0]))
    assert c.snapshot()["owned"] == 1


def test_cancel_queue_failure_does_not_undo_verified_ownership():
    t = RecordingTransport()
    t.send_cancel = lambda *args: False
    c, _, _, _, pieces, copies = endgame(t)
    c.handle_event(response(copies[0], pieces[0]))
    assert c.snapshot()["owned"] == 1
    assert not requests(c)
    assert any("CANCEL enqueue failed" in text for _, text in c.snapshot()["problems"])


def test_disabled_endgame_and_legacy_transport_do_not_duplicate():
    for config, legacy in [(SchedulerConfig(recovery=RecoveryConfig(endgame_enabled=False)), False),
                           (SchedulerConfig(), True)]:
        t = RecordingTransport()
        if legacy:
            t.send_cancel = None
        c, clock, _, _, _ = scheduler(1, t, config)
        connect(c, 1, 1)
        sent(c, requests(c)[0], clock)
        connect(c, 2, 1)
        clock.advance(5)
        assert c.schedule() == 0
        assert len(requests(c)) == 1


def test_sequential_strategy_and_initial_owned_sync():
    pieces, hashes = make_file(6, 8)
    store = InMemoryStore(hashes, 8)
    store.verify_and_store(0, pieces[0])
    c = Coordinator(6, RecordingTransport(), store, ManualClock(),
                    SchedulerConfig(recovery=RecoveryConfig(strategy="sequential")))
    connect(c, 1, 6)
    assert [r["piece_index"] for r in requests(c)] == [1, 2, 3, 4]
    assert c.snapshot()["recovery"]["owned"] == [0]


def test_bridge_endgame_emits_cancel_and_assembles_real_bytes(tmp_path):
    store, pieces = disk_store(tmp_path, data=b"data", size=4)
    clock = ManualClock()
    bridge = SchedulerBridge(clock)
    queues = {1: [], 2: []}
    c = Coordinator(1, bridge, FileStoreAdapter(store), clock)
    for cid in (1, 2):
        bridge.register(cid, str(cid), queues[cid].append)
        bridge.received(cid, m.BitfieldMsg([True]))
        bridge.received(cid, m.Unchoke())
    bridge.drain(c)
    first = next(msg for msg in queues[1] if isinstance(msg, m.Request))
    bridge.sent(1, first)
    bridge.drain(c)
    clock.advance(5)
    c.schedule()
    second = next(msg for msg in queues[2] if isinstance(msg, m.Request))
    bridge.received(2, m.Piece(second.request_id, 0, pieces[0]))
    bridge.drain(c)
    assert any(isinstance(msg, m.Cancel) and msg.request_id == first.request_id for msg in queues[1])
    bridge.received(1, m.Piece(first.request_id, 0, pieces[0]))
    bridge.drain(c)
    assert c.snapshot()["owned"] == 1
    assert store.assemble_file(str(tmp_path / "out.bin"))
    assert (tmp_path / "out.bin").read_bytes() == b"data"


@pytest.mark.parametrize("provider", ["", "x" * 129, None])
def test_provider_identity_validation_happens_before_registration(provider):
    c, *_ = scheduler(1)
    c.handle_event(e.ConnectionReady(1, provider))
    assert not c.snapshot()["neighbors"]
    connect(c, 1, 1, "valid")
    assert requests(c)
