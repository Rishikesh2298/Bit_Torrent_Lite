"""
Tracker tests (Debargha's module).

IDs refer to the test table in the individual plan (D-T01 ...).
State tests use a fake clock; HTTP tests run a real server on a free port.
"""

import http.client
import json
import socket
import threading
import time

import pytest

from bittorrent_lite.tracker.tracker_server import (
    REQUEST_READ_TIMEOUT, AnnounceError, make_server, validate_announce,
)
from bittorrent_lite.tracker.tracker_state import TrackerState

FILE_A = "a" * 64
FILE_B = "b" * 64


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def state(clock):
    return TrackerState(expiry_seconds=20, clock=clock)


def ids(peers):
    return [p.peer_id for p in peers]


# ──────────────────────────────────────────────
# Membership table
# ──────────────────────────────────────────────

class TestTrackerState:

    def test_two_peers_see_each_other_not_themselves(self, state):      # D-T01
        assert state.announce(FILE_A, "peer-01", "127.0.0.1", 7002, "started") == []
        peers = state.announce(FILE_A, "peer-02", "127.0.0.1", 7003, "started")
        assert ids(peers) == ["peer-01"]
        assert (peers[0].ip, peers[0].port) == ("127.0.0.1", 7002)
        assert ids(state.announce(FILE_A, "peer-01", "127.0.0.1", 7002, "update")) == ["peer-02"]

    def test_refresh_keeps_one_record_and_updates_time(self, state, clock):   # D-T02
        state.announce(FILE_A, "peer-01", "127.0.0.1", 7002, "started")
        clock.now += 7
        state.announce(FILE_A, "peer-01", "127.0.0.1", 7002, "update")
        assert state.peer_count(FILE_A) == 1
        assert state.get(FILE_A, "peer-01").last_seen == clock.now

    def test_refresh_replaces_endpoint(self, state):
        state.announce(FILE_A, "peer-01", "127.0.0.1", 7002, "started")
        state.announce(FILE_A, "peer-01", "10.0.0.5", 7100, "update")
        record = state.get(FILE_A, "peer-01")
        assert (record.ip, record.port) == ("10.0.0.5", 7100)
        assert state.peer_count() == 1

    def test_files_are_isolated(self, state):                             # D-T03
        state.announce(FILE_A, "peer-01", "127.0.0.1", 7002, "started")
        assert state.announce(FILE_B, "peer-02", "127.0.0.1", 7003, "started") == []
        assert ids(state.announce(FILE_A, "peer-03", "127.0.0.1", 7004, "started")) == ["peer-01"]

    def test_same_peer_id_in_two_files_is_two_entries(self, state):
        state.announce(FILE_A, "peer-01", "127.0.0.1", 7002, "started")
        state.announce(FILE_B, "peer-01", "127.0.0.1", 7002, "started")
        assert state.peer_count() == 2

    def test_expiry_boundary(self, state, clock):                         # D-T04
        state.announce(FILE_A, "peer-01", "127.0.0.1", 7002, "started")
        clock.now += 19.9
        assert ids(state.peers_for(FILE_A)) == ["peer-01"]
        clock.now += 0.1          # age exactly 20 s
        assert state.peers_for(FILE_A) == []
        assert state.peer_count() == 0

    def test_expired_entry_not_returned_to_announcer(self, state, clock):
        state.announce(FILE_A, "peer-01", "127.0.0.1", 7002, "started")
        clock.now += 25
        assert state.announce(FILE_A, "peer-02", "127.0.0.1", 7003, "started") == []

    def test_stopped_removes_and_repeat_is_harmless(self, state):         # D-T05
        state.announce(FILE_A, "peer-01", "127.0.0.1", 7002, "started")
        state.announce(FILE_A, "peer-01", "127.0.0.1", 7002, "stopped")
        state.announce(FILE_A, "peer-01", "127.0.0.1", 7002, "stopped")
        assert state.peer_count() == 0
        assert state.announce(FILE_A, "peer-02", "127.0.0.1", 7003, "started") == []

    def test_update_after_restart_recreates_entry(self, clock):
        fresh = TrackerState(20, clock)          # empty table = restarted tracker
        fresh.announce(FILE_A, "peer-01", "127.0.0.1", 7002, "update")
        assert fresh.peer_count(FILE_A) == 1

    def test_completed_flag_survives_later_update(self, state):
        state.announce(FILE_A, "seed-01", "127.0.0.1", 7001, "completed")
        state.announce(FILE_A, "seed-01", "127.0.0.1", 7001, "update")
        assert state.get(FILE_A, "seed-01").completed is True

    def test_unknown_event_rejected(self, state):
        with pytest.raises(ValueError):
            state.announce(FILE_A, "peer-01", "127.0.0.1", 7002, "paused")
        assert state.peer_count() == 0

    def test_custom_expiry_ten_seconds(self, clock):
        short = TrackerState(expiry_seconds=10, clock=clock)
        short.announce(FILE_A, "peer-01", "127.0.0.1", 7002, "started")
        clock.now += 10
        assert short.peers_for(FILE_A) == []


# ──────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────

def body(**overrides):
    data = {"file_id": FILE_A, "peer_id": "peer-01", "listen_port": 7002, "event": "started"}
    data.update(overrides)
    return data


class TestValidation:

    def test_valid(self):
        assert validate_announce(body()) == (FILE_A, "peer-01", 7002, "started")

    @pytest.mark.parametrize("field,value", [
        ("file_id", "A" * 64), ("file_id", "a" * 63), ("file_id", 5),
        ("peer_id", ""), ("peer_id", "x" * 33), ("peer_id", "bad id"), ("peer_id", None),
        ("listen_port", 0), ("listen_port", 65536), ("listen_port", "7002"),
        ("listen_port", True), ("listen_port", 7002.0),
        ("event", "paused"), ("event", None),
    ])
    def test_bad_field(self, field, value):                                 # D-T06
        with pytest.raises(AnnounceError) as info:
            validate_announce(body(**{field: value}))
        assert info.value.status == 400

    def test_missing_and_extra_fields(self):
        data = body()
        del data["event"]
        with pytest.raises(AnnounceError):
            validate_announce(data)
        with pytest.raises(AnnounceError):
            validate_announce(body(ip="1.2.3.4"))
        with pytest.raises(AnnounceError):
            validate_announce([1, 2])


# ──────────────────────────────────────────────
# HTTP server
# ──────────────────────────────────────────────

@pytest.fixture
def server(clock):
    srv = make_server("127.0.0.1", 0, TrackerState(20, clock))
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def request(server, method="POST", path="/announce", payload=None, raw=None,
            headers=None):
    host, port = server.server_address
    conn = http.client.HTTPConnection(host, port, timeout=5)
    if raw is None and payload is not None:
        raw = json.dumps(payload).encode()
    hdrs = {"Content-Type": "application/json"}
    hdrs.update(headers or {})
    conn.request(method, path, body=raw, headers=hdrs)
    response = conn.getresponse()
    data = json.loads(response.read())
    conn.close()
    return response.status, data


@pytest.mark.timeout(15)
class TestTrackerHttp:

    def test_two_clients_discover_each_other(self, server):
        status, data = request(server, payload=body(peer_id="peer-01", listen_port=7002))
        assert status == 200 and data == {"interval": 5, "peers": []}
        status, data = request(server, payload=body(peer_id="peer-02", listen_port=7003))
        assert data["peers"] == [{"peer_id": "peer-01", "ip": "127.0.0.1", "port": 7002}]

    def test_invalid_body_does_not_mutate(self, server):                     # D-T06
        status, _ = request(server, payload=body(listen_port=True))
        assert status == 400
        status, _ = request(server, raw=b"{not json")
        assert status == 400
        status, _ = request(server, raw=b"\xff\xfe")
        assert status == 400
        assert server.state.peer_count() == 0

    def test_error_codes(self, server):
        assert request(server, path="/peers", payload=body())[0] == 404
        assert request(server, method="GET")[0] == 405
        assert request(server, method="DELETE", raw=b"")[0] == 405
        assert request(server, raw=b"x" * 5000)[0] == 413
        assert request(server, payload=body(), headers={"Content-Type": "text/plain"})[0] == 415

    def test_missing_content_length(self, server):
        host, port = server.server_address
        with socket.create_connection((host, port), timeout=5) as sock:
            sock.sendall(b"POST /announce HTTP/1.1\r\nHost: x\r\n"
                         b"Content-Type: application/json\r\n\r\n")
            reply = sock.recv(4096)
        assert reply.startswith(b"HTTP/1.1 411")

    def test_transfer_encoding_rejected(self, server):
        host, port = server.server_address
        with socket.create_connection((host, port), timeout=5) as sock:
            sock.sendall(b"POST /announce HTTP/1.1\r\nHost: x\r\n"
                         b"Content-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n"
                         b"0\r\n\r\n")
            reply = sock.recv(4096)
        assert reply.startswith(b"HTTP/1.1 415")

    def test_stalled_body_times_out_and_server_recovers(self, server):        # D-T07
        host, port = server.server_address
        stalled = socket.create_connection((host, port), timeout=10)
        stalled.sendall(b"POST /announce HTTP/1.1\r\nHost: x\r\n"
                        b"Content-Type: application/json\r\nContent-Length: 100\r\n\r\n{\"fi")
        started = time.monotonic()
        status, _ = request(server, payload=body())     # queued behind the stalled client
        assert status == 200
        assert time.monotonic() - started < REQUEST_READ_TIMEOUT + 2
        stalled.close()

    def test_source_ip_used(self, server):
        request(server, payload=body(peer_id="peer-01"))
        assert server.state.get(FILE_A, "peer-01").ip == "127.0.0.1"
