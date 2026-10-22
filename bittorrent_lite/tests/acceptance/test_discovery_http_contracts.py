"""Live loopback HTTP contracts. Partition these into integration, not unit."""

import http.client
import json
import threading

import pytest

from bittorrent_lite.discovery.tracker_server import make_server


pytestmark = pytest.mark.timeout(15)


@pytest.fixture
def live_tracker():
    server = make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, name="acceptance-owned-tracker")
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)
        assert not thread.is_alive(), "owned tracker worker failed to stop"


def request(server, raw, *, headers=None, method="POST", path="/announce"):
    conn = http.client.HTTPConnection(*server.server_address, timeout=3)
    try:
        conn.request(method, path, body=raw,
                     headers={"Content-Type": "application/json"} if headers is None else headers)
        response = conn.getresponse()
        payload = response.read()
        assert response.getheader("Content-Type") == "application/json"
        assert int(response.getheader("Content-Length")) == len(payload)
        assert response.getheader("Connection") == "close"
        return response.status, json.loads(payload)
    finally:
        conn.close()


def body(peer="peer-1", **extra):
    return json.dumps({"file_id": "a" * 64, "peer_id": peer,
                       "listen_port": 7001, "event": "started", **extra}).encode()


@pytest.mark.parametrize("size", [4095, 4096, 4097], ids=["below-4kib", "at-4kib", "above-4kib"])
def test_live_request_byte_boundary_and_subsequent_health(live_tracker, size):
    raw = body()
    raw += b" " * (size - len(raw))
    status, result = request(live_tracker, raw)
    if size > 4096:
        assert status == 413 and "error" in result
        assert live_tracker.state.peer_count() == 0
    else:
        assert status == 200 and result == {"interval": 5, "peers": []}
        assert live_tracker.state.peer_count() == 1
    assert request(live_tracker, body("healthy"))[0] == 200
    assert live_tracker.state.get("a" * 64, "healthy") is not None


@pytest.mark.parametrize("raw,headers,status", [
    (b"{}", {}, 415),
    (b"{}", {"Content-Type": "text/plain"}, 415),
    (b"\xff\xfe", {"Content-Type": "application/json"}, 400),
    (b"\xef\xbb\xbf{}", {"Content-Type": "application/json"}, 400),
    (b"[]", {"Content-Type": "application/json"}, 400),
    (b"null", {"Content-Type": "application/json"}, 400),
    (b'[' * 2000 + b'0' + b']' * 2000, {"Content-Type": "application/json"}, 400),
    (b'', {"Content-Type": "application/json", "Content-Length": '9' * 5000}, 413),
    (body(ip="198.51.100.77"), {"Content-Type": "application/json"}, 400),
], ids=["missing-content-type", "wrong-content-type", "invalid-utf8", "bom", "array", "null",
        "bounded-deep-nesting", "huge-content-length", "spoofed-ip"])
def test_live_invalid_request_preserves_membership_and_recovers(live_tracker, raw, headers, status):
    assert request(live_tracker, body("existing"))[0] == 200
    before = live_tracker.state.get("a" * 64, "existing")
    actual, result = request(live_tracker, raw, headers=headers)
    assert actual == status and "error" in result
    assert live_tracker.state.peer_count() == 1
    assert live_tracker.state.get("a" * 64, "existing") == before
    actual, result = request(live_tracker, body("healthy"))
    assert actual == 200
    assert result["peers"] == [{"peer_id": "existing", "ip": "127.0.0.1", "port": 7001}]
