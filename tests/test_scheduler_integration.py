"""Lifecycle, fault, and disk-integration coverage for the submitted scheduler."""
import hashlib
import random
from concurrent.futures import ThreadPoolExecutor

import pytest

from bittorrent_lite.scheduler import Coordinator, SchedulerConfig, RequestManager, PiecePicker
from bittorrent_lite.scheduler import events as e
from bittorrent_lite.scheduler.adapters import FileStoreAdapter, SchedulerBridge
from bittorrent_lite.file_manager.file_store import FileStore
from bittorrent_lite.types import TorrentMetadata
from bittorrent_lite.protocol import messages as m
from examples.scheduler_dependencies import ManualClock, RecordingTransport, InMemoryStore, make_file


def setup_scheduler(n=3, transport=None):
    pieces, hashes = make_file(n, 8)
    clock = ManualClock()
    transport = transport or RecordingTransport()
    store = InMemoryStore(hashes, 8)
    c = Coordinator(n, transport, store, clock, SchedulerConfig(request_window=1), rng=random.Random(1))
    c.handle_event(e.ConnectionReady(1, "one"))
    c.handle_event(e.BitfieldReceived(1, [True] * n))
    c.handle_event(e.UnchokeReceived(1))
    return c, clock, transport, store, pieces


def pending(c):
    return c.snapshot()["pending"][0]


def response(r, data):
    return e.PieceReceived(r["connection_id"], r["request_id"], r["piece_index"], data)


def test_success_before_send_and_late_duplicate_events():
    c, clock, t, store, pieces = setup_scheduler()
    r = pending(c)
    c.handle_event(response(r, pieces[r["piece_index"]]))
    next_request = pending(c)
    c.handle_event(e.RequestSent(1, r["request_id"], r["piece_index"], 0))
    c.handle_event(response(r, pieces[r["piece_index"]]))
    assert c.snapshot()["owned"] == 1
    assert pending(c) == next_request
    assert sum(item[0] == "HAVE" for item in t.log) == 1


def test_interest_enqueue_failure_blocks_requests():
    class Transport(RecordingTransport):
        def send_interest(self, *args):
            return False
    c, *_ = setup_scheduler(transport=Transport())
    assert not c.snapshot()["pending"]


def test_request_enqueue_failure_releases_reservation():
    class Transport(RecordingTransport):
        def send_request(self, *args):
            return False
    c, *_ = setup_scheduler(transport=Transport())
    assert not c.snapshot()["pending"]
    assert c.snapshot()["piece_states"]["MISSING"] == 3


@pytest.mark.parametrize("field", [[1, 2, 0], [1, "yes", 0], [1], [1, None, 0]])
def test_bad_bitfield_preserves_previous_snapshot(field):
    c, *_ = setup_scheduler()
    c.handle_event(e.BitfieldReceived(1, field))
    assert c.snapshot()["availability"] == [1, 1, 1]
    assert c.snapshot()["problems"]


@pytest.mark.parametrize("index", [True, 1.5, -1, 3, "0"])
def test_bad_have_is_reported(index):
    c, *_ = setup_scheduler()
    c.handle_event(e.HaveReceived(1, index))
    assert c.snapshot()["problems"]


def test_timeout_starts_on_send_and_unsent_has_separate_limit():
    c, clock, *_ = setup_scheduler()
    r = pending(c)
    clock.advance(4)
    assert c.tick() == []
    c.handle_event(e.RequestSent(1, r["request_id"], r["piece_index"], clock.now()))
    clock.advance(9)
    assert c.tick() == []
    clock.advance(1)
    assert c.tick()[0].kind == "response_timeout"
    assert pending(c)["request_id"] != r["request_id"]
    clock.advance(5)
    assert c.tick()[0].kind == "send_unconfirmed"


def test_choke_disconnect_and_reconnect_identity():
    c, _, _, _, pieces = setup_scheduler()
    r = pending(c)
    c.handle_event(e.ChokeReceived(1))
    assert not c.snapshot()["pending"]
    assert c.snapshot()["availability"] == [1, 1, 1]
    c.handle_event(e.Disconnected(1))
    c.handle_event(e.Disconnected(1))
    c.handle_event(e.ConnectionReady(1, "one"))
    assert not c.snapshot()["neighbors"][1]["active"]
    assert c.snapshot()["availability"] == [0, 0, 0]
    c.handle_event(response(r, pieces[r["piece_index"]]))
    assert c.snapshot()["owned"] == 0
    c.handle_event(e.ConnectionReady(2, "one"))
    c.handle_event(e.BitfieldReceived(2, [True] * 3))
    c.handle_event(e.UnchokeReceived(2))
    assert pending(c)["connection_id"] == 2


@pytest.mark.parametrize("kind", ["reject", "send_failure", "corrupt"])
def test_failed_request_released_and_stale_response_ignored(kind):
    c, clock, _, _, pieces = setup_scheduler(1)
    r = pending(c)
    event = {"reject": e.RejectReceived(1, r["request_id"], 0),
             "send_failure": e.RequestSendFailed(1, r["request_id"], 0),
             "corrupt": response(r, b"bad")}[kind]
    c.handle_event(event)
    assert not c.snapshot()["pending"]
    if kind == "corrupt":
        # A corrupt provider stays excluded for this piece; another can supply it.
        c.handle_event(e.ConnectionReady(2, "two"))
        c.handle_event(e.BitfieldReceived(2, [True]))
        c.handle_event(e.UnchokeReceived(2))
    else:
        clock.advance(2 if kind == "reject" else 1)
        c.schedule()
    new = pending(c)
    assert (new["connection_id"], new["request_id"]) != (r["connection_id"], r["request_id"])
    c.handle_event(response(r, pieces[0]))
    assert c.snapshot()["owned"] == 0
    assert pending(c) == new


def test_storage_failure_pauses_and_can_resume():
    c, _, _, store, pieces = setup_scheduler()
    store.fail_io = True
    r = pending(c)
    c.handle_event(response(r, pieces[r["piece_index"]]))
    assert c.snapshot()["paused"]
    assert not c.snapshot()["pending"]
    assert not c.snapshot()["invalid_pieces"]
    store.fail_io = False
    c.resume_after_storage_error()
    assert len(c.snapshot()["pending"]) == 1


def test_verification_retains_reservation_even_before_send_confirmation():
    c, clock, _, store, pieces = setup_scheduler()
    original = store.verify_and_store
    def checking(index, data):
        assert c.snapshot()["piece_states"]["VERIFYING"] == 1
        clock.advance(100)
        assert c.tick() == []
        assert c.schedule() == 0
        return original(index, data)
    store.verify_and_store = checking
    r = pending(c)
    c.handle_event(response(r, pieces[r["piece_index"]]))
    assert c.snapshot()["owned"] == 1


def test_per_connection_window_and_global_piece_reservations():
    c, *_ = setup_scheduler(8)
    for cid in range(2, 7):
        c.handle_event(e.ConnectionReady(cid, str(cid)))
        c.handle_event(e.BitfieldReceived(cid, [True] * 8))
        c.handle_event(e.UnchokeReceived(cid))
    requests = c.snapshot()["pending"]
    assert len(requests) == 6
    assert len({r["piece_index"] for r in requests}) == 6
    assert all(n["outstanding"] == 1 for n in c.snapshot()["neighbors"].values())


@pytest.mark.parametrize("kwargs", [dict(request_window=0), dict(request_window=True),
    dict(response_timeout=-1), dict(response_timeout=float("nan")),
    dict(send_confirm_timeout=float("inf"))])
def test_config_validation(kwargs):
    with pytest.raises(ValueError):
        SchedulerConfig(**kwargs)


def test_request_manager_exact_identity_and_cleanup():
    clock = ManualClock()
    rm = RequestManager(clock, SchedulerConfig(request_window=1))
    r = rm.reserve(1, 0)
    assert rm.reserve(2, 0) is None
    assert rm.reserve(1, 1) is None
    assert rm.cancel(2, r.request_id, 0) is None
    assert rm.cancel(1, r.request_id + 1, 0) is None
    assert rm.mark_sent(1, r.request_id, 0, 0)
    assert not rm.mark_sent(1, r.request_id, 0, 1)
    assert rm.get_expired(10) == [r]
    assert rm.cancel_connection(1) == [r]
    assert rm.cancel_connection(1) == []
    assert rm.reserved_pieces() == frozenset()


def test_picker_randomized_availability_matches_independent_model():
    rng = random.Random(52)
    picker = PiecePicker(12, rng)
    model = {}
    for _ in range(1000):
        cid = rng.randrange(8)
        if rng.random() < .25:
            model.pop(cid, None)
            picker.remove_connection(cid)
        else:
            bits = [bool(rng.randrange(2)) for _ in range(12)]
            model[cid] = bits[:]
            picker.update_bitfield(cid, bits)
            bits[0] = not bits[0]
        counts = [sum(bits[i] for bits in model.values()) for i in range(12)]
        assert picker.availability_snapshot() == counts
        chosen = picker.pick_piece([False] * 12, [True] * 12, set())
        if any(counts):
            assert counts[chosen] == min(x for x in counts if x)
        else:
            assert chosen is None


def disk_store(tmp_path, data=b"abcdefghij", size=4):
    pieces = [data[i:i+size] for i in range(0, len(data), size)]
    metadata = TorrentMetadata(1, "out.bin", len(data), size,
        [hashlib.sha256(p).hexdigest() for p in pieces], hashlib.sha256(data).hexdigest())
    return FileStore(metadata, "test", str(tmp_path / "pieces")), pieces


def test_protocol_bridge_download_to_real_disk_and_assemble(tmp_path):
    store, pieces = disk_store(tmp_path)
    clock = ManualClock()
    bridge = SchedulerBridge(clock)
    outgoing = []
    c = Coordinator(len(pieces), bridge, FileStoreAdapter(store), clock,
                    SchedulerConfig(request_window=1))
    bridge.register(1, "source", outgoing.append)
    bits = [1] * len(pieces)
    bridge.received(1, m.BitfieldMsg(bits))
    bits[0] = 0  # callback must snapshot before processing
    bridge.received(1, m.Unchoke())
    bridge.drain(c)
    while not c.snapshot()["ready_to_assemble"]:
        request = next(message for message in outgoing if isinstance(message, m.Request))
        outgoing.clear()
        bridge.sent(1, request)
        bridge.received(1, m.Piece(request.request_id, request.piece_index,
                                    pieces[request.piece_index]))
        bridge.drain(c)
    assert store.assemble_file(str(tmp_path / "result.bin"))
    assert (tmp_path / "result.bin").read_bytes() == b"abcdefghij"
    assert c.snapshot()["owned"] == 3
    assert not c.snapshot()["complete"]
    assert not c.snapshot()["pending"]


def test_disk_adapter_revalidates_cached_pieces(tmp_path):
    store, pieces = disk_store(tmp_path)
    store.verify_and_store(0, pieces[0])
    (store.pieces_dir / "0.piece").write_bytes(b"bad")
    assert FileStoreAdapter(store).verified_bitfield() == [False] * 3


def test_bridge_contains_queue_failures_and_serializes_worker_events():
    bridge = SchedulerBridge(ManualClock())
    c, *_ = setup_scheduler(transport=bridge)
    def broken(message):
        raise ConnectionError("closed")
    bridge.register(2, "two", broken)
    assert not bridge.send_request(2, 1, 0)
    bridge.drain(c)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: bridge.received(2, m.Have(0)), range(200)))
    bridge.drain(c)
    # Saturation closes the affected session and reconciles even a lost close event.
    assert c.snapshot()["availability"][0] == 1
    assert not c.snapshot()["neighbors"][2]["active"]
    bridge.disconnected(2)
    bridge.drain(c)
    assert not bridge.send_have(2, 0)
    with pytest.raises(ValueError):
        bridge.register(2, "reconnected", broken)
