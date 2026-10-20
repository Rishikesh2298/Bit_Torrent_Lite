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

