"""
Tracker client and discovery worker tests (Debargha's module).

Worker timing tests inject a fake announce function and tiny retry
delays so they run quickly without a network.
"""

import json
import queue
import socket
import threading
import time

import pytest

from bittorrent_lite.peer.tracker_client import (
    AnnounceResponse, DiscoveryWorker, PeersDiscovered, TrackerError,
    TrackerRequestError, announce, parse_response,
)
from bittorrent_lite.tracker.tracker_server import make_server
from bittorrent_lite.types import PeerRecord

FILE_A = "a" * 64

pytestmark = pytest.mark.timeout(20)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class RunningTracker:
    def __init__(self, port=0):
        self.server = make_server("127.0.0.1", port)
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def tracker():
    running = RunningTracker()
    yield running
    running.stop()


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


# ──────────────────────────────────────────────
# Response parsing
# ──────────────────────────────────────────────

class TestParseResponse:

    def test_valid(self):
        raw = json.dumps({"interval": 5, "peers": [
            {"peer_id": "peer-02", "ip": "127.0.0.1", "port": 7003}]}).encode()
        assert parse_response(raw) == AnnounceResponse(5, (PeerRecord("peer-02", "127.0.0.1", 7003),))

    def test_drops_self_and_duplicates(self):
        raw = json.dumps({"interval": 5, "peers": [
            {"peer_id": "me", "ip": "127.0.0.1", "port": 7001},
            {"peer_id": "p2", "ip": "127.0.0.1", "port": 7002},
            {"peer_id": "p2", "ip": "127.0.0.1", "port": 7009}]}).encode()
        assert parse_response(raw, own_peer_id="me").peers == (PeerRecord("p2", "127.0.0.1", 7002),)

    @pytest.mark.parametrize("payload", [
        b"nope", b"[]",
        json.dumps({"interval": 0, "peers": []}).encode(),
        json.dumps({"interval": True, "peers": []}).encode(),
        json.dumps({"interval": 5}).encode(),
        json.dumps({"interval": 5, "peers": [{"peer_id": "p", "ip": "0.0.0.0", "port": 1}]}).encode(),
        json.dumps({"interval": 5, "peers": [{"peer_id": "p", "ip": "::1", "port": 1}]}).encode(),
        json.dumps({"interval": 5, "peers": [{"peer_id": "p", "ip": "1.2.3.4", "port": 0}]}).encode(),
        json.dumps({"interval": 5, "peers": [{"peer_id": "bad id", "ip": "1.2.3.4", "port": 9}]}).encode(),
    ])
    def test_rejects(self, payload):
        with pytest.raises(TrackerRequestError) as info:
            parse_response(payload)
        assert info.value.category == "bad_response"


# ──────────────────────────────────────────────
# announce() against a real tracker
# ──────────────────────────────────────────────

class TestAnnounce:

    def test_round_trip(self, tracker):
        assert announce(tracker.url, FILE_A, "peer-01", 7002, "started").peers == ()
        response = announce(tracker.url, FILE_A, "peer-02", 7003, "started")
        assert response.interval == 5
        assert response.peers == (PeerRecord("peer-01", "127.0.0.1", 7002),)

    def test_unreachable(self):
        with pytest.raises(TrackerRequestError) as info:
            announce(f"http://127.0.0.1:{free_port()}", FILE_A, "peer-01", 7002, "started")
        assert info.value.category == "unreachable"

    def test_http_error_category(self, tracker):
        with pytest.raises(TrackerRequestError) as info:
            announce(tracker.url, "bad", "peer-01", 7002, "started")
        assert info.value.category == "http_status"
        assert "400" in info.value.detail

    def test_timeout(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()      # accepts at TCP level but never answers
        try:
            started = time.monotonic()
            with pytest.raises(TrackerRequestError) as info:
                announce(f"http://127.0.0.1:{listener.getsockname()[1]}", FILE_A,
                         "peer-01", 7002, "started", timeout=0.5)
            assert info.value.category == "timeout"
            assert time.monotonic() - started < 3
        finally:
            listener.close()


# ──────────────────────────────────────────────
# Discovery worker
# ──────────────────────────────────────────────

class ScriptedAnnounce:
    """Fake announce: pops outcomes; an Exception instance is raised."""

    def __init__(self, outcomes, default=None):
        self.outcomes = list(outcomes)
        self.default = default or AnnounceResponse(60, ())
        self.calls = []
        self.lock = threading.Lock()

    def __call__(self, url, file_id, peer_id, port, event, timeout):
        with self.lock:
            self.calls.append((event, time.monotonic()))
            outcome = self.outcomes.pop(0) if self.outcomes else self.default
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def events(self):
        with self.lock:
            return [c[0] for c in self.calls]


def make_worker(fake, events=None, **kwargs):
    kwargs.setdefault("retry_delays", [0.05, 0.1, 0.2])
    return DiscoveryWorker("http://unused", FILE_A, "peer-01", 7002,
                           events if events is not None else queue.Queue(),
                           announce_fn=fake, **kwargs)


def drain(q):
    items = []
    while True:
        try:
            items.append(q.get_nowait())
        except queue.Empty:
            return items


class TestDiscoveryWorker:

    def test_publishes_peers_then_waits_interval(self):
        peers = (PeerRecord("peer-02", "127.0.0.1", 7003),)
        fake = ScriptedAnnounce([AnnounceResponse(60, peers)])
        events = queue.Queue()
        worker = make_worker(fake, events)
        worker.start()
        item = events.get(timeout=2)
        assert isinstance(item, PeersDiscovered) and item.peers == peers
        time.sleep(0.2)
        assert fake.events() == ["started"]          # waiting 60 s, not looping
        assert worker.stop(send_stopped=False)

    def test_retry_backoff_then_reset(self):
        fail = TrackerRequestError("unreachable", "down")
        fake = ScriptedAnnounce([fail, fail, fail, fail, AnnounceResponse(1, ()), fail])
        events = queue.Queue()
        worker = make_worker(fake, events)
        worker.start()
        assert wait_for(lambda: len(fake.calls) >= 6, timeout=5)
        worker.stop(send_stopped=False)
        gaps = [b[1] - a[1] for a, b in zip(fake.calls, fake.calls[1:])]
        # 0.05, 0.1, 0.2, 0.2 (capped), then interval 1 s after success
        assert gaps[0] < gaps[1] < gaps[2] + 0.05
        assert abs(gaps[3] - 0.2) < 0.1
        assert gaps[4] >= 0.9
        # first attempts stay "started" until one succeeds
        assert fake.events()[:5] == ["started"] * 5 and fake.events()[5] == "update"
        assert worker.consecutive_failures == 1
        kinds = [type(e) for e in drain(events)]
        assert kinds[:4] == [TrackerError] * 4 and PeersDiscovered in kinds

    def test_silly_interval_is_clamped(self):
        fake = ScriptedAnnounce([], default=AnnounceResponse(10 ** 9, ()))
        worker = make_worker(fake)
        worker.start()
        assert wait_for(lambda: worker.last_delay is not None)
        assert worker.last_delay == 60
        worker.stop(send_stopped=False)

    def test_stop_during_retry_is_prompt(self):                        # D-T09
        fake = ScriptedAnnounce([], default=TrackerRequestError("unreachable", "down"))
        worker = make_worker(fake, retry_delays=[30])
        worker.start()
        assert wait_for(lambda: len(fake.calls) == 1)
        started = time.monotonic()
        assert worker.stop()
        assert time.monotonic() - started < 1
        assert fake.events() == ["started"]        # never registered -> no stopped

    def test_stopped_sent_on_exit_and_failure_ignored(self):
        fake = ScriptedAnnounce([AnnounceResponse(60, ()), TrackerRequestError("timeout", "x")])
        worker = make_worker(fake)
        worker.start()
        assert wait_for(lambda: len(fake.calls) == 1)
        assert worker.stop()
        assert fake.events() == ["started", "stopped"]

    def test_mark_completed_announces_immediately(self):
        fake = ScriptedAnnounce([])
        worker = make_worker(fake)
        worker.start()
        assert wait_for(lambda: len(fake.calls) == 1)
        worker.mark_completed()
        assert wait_for(lambda: len(fake.calls) == 2)
        assert fake.events()[1] == "completed"
        worker.announce_now()
        assert wait_for(lambda: len(fake.calls) == 3)
        assert fake.events()[2] == "update"
        worker.stop(send_stopped=False)

    def test_full_queue_does_not_block_forever(self, monkeypatch):
        monkeypatch.setattr("bittorrent_lite.peer.tracker_client.QUEUE_PUT_TIMEOUT", 0.05)
        full = queue.Queue(maxsize=1)
        full.put("busy")
        fake = ScriptedAnnounce([], default=AnnounceResponse(1, ()))
        worker = make_worker(fake, full)
        worker.start()
        assert wait_for(lambda: worker.dropped_events >= 1)
        assert worker.stop(send_stopped=False)

    def test_rejects_bad_construction(self):
        with pytest.raises(ValueError):
            DiscoveryWorker("http://x", "bad", "peer-01", 7002, queue.Queue())
        with pytest.raises(ValueError):
            DiscoveryWorker("http://x", FILE_A, "peer-01", 0, queue.Queue())

    def test_tracker_absent_then_started_then_restarted(self):        # D-T08
        port = free_port()
        url = f"http://127.0.0.1:{port}"
        events_a, events_b = queue.Queue(), queue.Queue()
        worker_a = DiscoveryWorker(url, FILE_A, "peer-01", 7002, events_a,
                                   retry_delays=[0.1, 0.2, 0.3])
        worker_b = DiscoveryWorker(url, FILE_A, "peer-02", 7003, events_b,
                                   retry_delays=[0.1, 0.2, 0.3])
        worker_a.start()
        worker_b.start()
        try:
            assert isinstance(events_a.get(timeout=2), TrackerError)

            tracker = RunningTracker(port)
            tracker.server.interval = 1
            assert wait_for(lambda: tracker.server.state.peer_count(FILE_A) == 2)

            # restart with an empty table; periodic updates rebuild it
            tracker.stop()
            tracker = RunningTracker(port)
            tracker.server.interval = 1
            assert tracker.server.state.peer_count() == 0
            assert wait_for(lambda: tracker.server.state.peer_count(FILE_A) == 2, timeout=8)

            def saw_other(q, other):
                return any(isinstance(e, PeersDiscovered) and
                           [p.peer_id for p in e.peers] == [other] for e in drain(q))
            assert wait_for(lambda: saw_other(events_b, "peer-01"), timeout=4)

            worker_a.stop()
            assert tracker.server.state.get(FILE_A, "peer-01") is None   # stopped received
        finally:
            worker_a.stop(send_stopped=False)
            worker_b.stop(send_stopped=False)
            tracker.stop()
