"""Isolated HTTP parsing and discovery timing contracts, without live sockets."""

import io
import json
import queue
from email.message import Message

import pytest

from bittorrent_lite.common import config
from bittorrent_lite.discovery import tracker_client as client
from bittorrent_lite.discovery.tracker_server import AnnounceError, TrackerHandler
from bittorrent_lite.discovery.tracker_state import TrackerState


FILE_ID = "a" * 64


def handler_for(raw, headers):
    handler = object.__new__(TrackerHandler)
    handler.headers = Message()
    for key, value in headers.items():
        handler.headers[key] = value
    handler.rfile = io.BytesIO(raw)
    return handler


@pytest.mark.parametrize("length", [4095, 4096, 4097], ids=["below-4kib", "at-4kib", "above-4kib"])
def test_http_body_bound_is_checked_before_read(length):
    handler = handler_for(b"x" * length, {"Content-Type": "application/json", "Content-Length": str(length)})
    if length > 4096:
        with pytest.raises(AnnounceError) as raised:
            handler._read_body()
        assert raised.value.status == 413
        assert handler.rfile.tell() == 0
    else:
        assert handler._read_body() == b"x" * length
        assert handler.rfile.tell() == length


@pytest.mark.parametrize("headers,status", [
    ({"Content-Length": "2"}, 415),
    ({"Content-Type": "text/plain", "Content-Length": "2"}, 415),
    ({"Content-Type": "application/json"}, 411),
    ({"Content-Type": "application/json", "Content-Length": "-1"}, 400),
    ({"Content-Type": "application/json", "Content-Length": "1.5"}, 400),
    ({"Content-Type": "application/json", "Content-Length": "two"}, 400),
    ({"Content-Type": "application/json", "Content-Length": "2", "Transfer-Encoding": "chunked"}, 415),
], ids=["missing-content-type", "wrong-content-type", "missing-length", "negative-length",
        "float-length", "text-length", "transfer-encoding"])
def test_http_invalid_headers_reject_without_consuming_body(headers, status):
    handler = handler_for(b"{}", headers)
    with pytest.raises(AnnounceError) as raised:
        handler._read_body()
    assert raised.value.status == status
    assert handler.rfile.tell() == 0


def test_http_short_body_has_controlled_error():
    handler = handler_for(b"{", {"Content-Type": "application/json", "Content-Length": "20"})
    with pytest.raises(AnnounceError) as raised:
        handler._read_body()
    assert raised.value.status == 400
    assert "incomplete" in str(raised.value)


@pytest.mark.parametrize('raw_length, status', [('9' * 5000, 413), ('²', 400), ('１２', 400)])
def test_http_length_lexical_bounds_reject_before_integer_or_body_read(raw_length, status):
    handler = handler_for(b'{}', {'Content-Type': 'application/json', 'Content-Length': raw_length})
    with pytest.raises(AnnounceError) as raised:
        handler._read_body()
    assert raised.value.status == status and handler.rfile.tell() == 0


def test_http_large_leading_zero_length_remains_bounded_and_valid():
    handler = handler_for(b'{}', {'Content-Type': 'application/json', 'Content-Length': '0' * 5000 + '2'})
    assert handler._read_body() == b'{}'


def test_http_parser_recursion_is_controlled_without_membership_access(monkeypatch):
    from types import SimpleNamespace
    from bittorrent_lite.discovery import tracker_server
    handler = handler_for(b'[]', {'Content-Type': 'application/json', 'Content-Length': '2'})
    handler.path = '/announce'
    responses = []
    handler._send_error = lambda status, message: responses.append((status, message))
    def deeply_nested(raw):
        raise RecursionError('controlled parser limit')
    monkeypatch.setattr(tracker_server, 'json', SimpleNamespace(
        loads=deeply_nested, JSONDecodeError=json.JSONDecodeError))
    # No server/state exists: rejection must finish before membership access.
    handler.do_POST()
    assert responses == [(400, 'body is not valid UTF-8 JSON')]


def test_http_json_content_type_allows_charset_parameter():
    handler = handler_for(b"{}", {"Content-Type": "Application/JSON; charset=utf-8", "Content-Length": "2"})
    assert handler._read_body() == b"{}"


@pytest.mark.parametrize("status,payload", [(200, {"interval": 5, "peers": []}),
                                           (400, {"error": "bad λ value"})],
                         ids=["success", "error"])
def test_http_response_length_matches_exact_encoded_bytes(status, payload):
    handler = object.__new__(TrackerHandler)
    captured = {"headers": []}
    handler.send_response = lambda code: captured.update(status=code)
    handler.send_header = lambda name, value: captured["headers"].append((name, value))
    handler.end_headers = lambda: captured.update(ended=True)
    handler.wfile = io.BytesIO()
    handler._send_json(status, payload)
    headers = dict(captured["headers"])
    raw = handler.wfile.getvalue()
    assert captured["status"] == status and captured["ended"]
    assert headers["Content-Type"] == "application/json"
    assert int(headers["Content-Length"]) == len(raw)
    assert headers["Connection"] == "close" and handler.close_connection
    assert json.loads(raw) == payload


@pytest.mark.parametrize("length", [65535, 65536, 65537],
                         ids=["below-64kib", "at-64kib", "above-64kib"])
def test_announce_reads_only_response_limit_plus_one(monkeypatch, length):
    raw = b'{"interval":5,"peers":[]}'
    raw += b" " * (length - len(raw))
    reads = []

    class Response(io.BytesIO):
        def read(self, count=-1):
            reads.append(count)
            return super().read(count)

    response = Response(raw)
    monkeypatch.setattr(client.urllib.request, "urlopen", lambda *a, **k: response)
    if length > 65536:
        with pytest.raises(client.TrackerRequestError) as raised:
            client.announce("http://isolated.invalid", FILE_ID, "p", 1234, "started")
        assert raised.value.category == "bad_response"
    else:
        assert client.announce("http://isolated.invalid", FILE_ID, "p", 1234, "started") == client.AnnounceResponse(5, ())
    assert reads == [65537]
    assert response.closed


@pytest.mark.parametrize("raw", [
    b"\xff", b"\xef\xbb\xbf{}", b"null", b"true", b"42", b'"text"', b"[]",
    b'{"interval":NaN,"peers":[]}', b'{"interval":Infinity,"peers":[]}',
    b'{"interval":5,"peers":[null]}', b'{"interval":5,"peers":[{"peer_id":true}]}',
], ids=["utf8", "bom", "null", "bool", "integer", "string", "array", "nan", "infinity", "null-peer", "bad-peer"])
def test_response_malformed_json_values_have_documented_error_category(raw):
    with pytest.raises(client.TrackerRequestError) as raised:
        client.parse_response(raw)
    assert raised.value.category == "bad_response"


def test_bounded_deep_response_has_controlled_rejection():
    raw = b"[" * 1500 + b"0" + b"]" * 1500
    assert len(raw) < 65536
    with pytest.raises(client.TrackerRequestError) as raised:
        client.parse_response(raw)
    assert raised.value.category == "bad_response"


@pytest.mark.parametrize("age", [19.999, 20.0, 20.001], ids=["just-before", "at", "just-after"])
def test_tracker_expiry_and_boundary_refresh(age):
    clock = [100.0]
    state = TrackerState(clock=lambda: clock[0])
    state.announce(FILE_ID, "first", "127.0.0.1", 7001, "started")
    clock[0] += age
    assert [peer.peer_id for peer in state.peers_for(FILE_ID)] == (["first"] if age < 20 else [])
    state.announce(FILE_ID, "first", "127.0.0.1", 7002, "update")
    assert state.peer_count() == 1
    assert state.get(FILE_ID, "first").last_seen == clock[0]
    assert state.get(FILE_ID, "first").port == 7002
    state.announce(FILE_ID, "first", "127.0.0.1", 7002, "stopped")
    state.announce(FILE_ID, "first", "127.0.0.1", 7003, "started")
    assert state.peer_count() == 1
    assert state.get(FILE_ID, "first").port == 7003


class ScriptedWait:
    """A deterministic wait provider for the worker; no real threads or sleeps."""

    def __init__(self, worker, after_wait):
        self.worker = worker
        self.after_wait = after_wait
        self.delays = []

    def wait(self, delay):
        self.delays.append(delay)
        self.after_wait(len(self.delays))

    def set(self):
        pass

    def clear(self):
        pass


def test_original_retry_delays_cap_then_reset_without_sleep():
    calls = []
    failures = client.TrackerRequestError("unreachable", "predeclared tracker outage")
    outcomes = [failures, failures, failures, failures, client.AnnounceResponse(5, ()), failures]

    def announce(*args, **kwargs):
        calls.append(args[4])
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    events = queue.Queue()
    worker = client.DiscoveryWorker("http://isolated.invalid", FILE_ID, "p", 1234, events,
                                    announce_fn=announce)
    wait = ScriptedWait(worker, lambda count: worker._stop.set() if count == 6 else None)
    worker._wake = wait
    worker._send_stopped = False
    worker._run()
    assert tuple(config.TRACKER_RETRY_DELAYS) == (2, 4, 10)
    assert wait.delays == [2, 4, 10, 10, 5, 2]
    assert calls == ["started"] * 5 + ["update"]
    assert worker.successes == 1 and worker.failures == 5 and worker.consecutive_failures == 1
    outcomes = [events.get_nowait() for _ in range(events.qsize())]
    assert [type(item) for item in outcomes] == [client.TrackerError] * 4 + [client.PeersDiscovered, client.TrackerError]


def test_dropped_discovery_snapshot_is_replaced_by_next_fresh_snapshot(monkeypatch):
    from bittorrent_lite.common.types import PeerRecord

    monkeypatch.setattr(client, "QUEUE_PUT_TIMEOUT", 0)
    events = queue.Queue(maxsize=1)
    events.put("occupied")
    calls = []

    def announce(*args, **kwargs):
        calls.append(args[4])
        return client.AnnounceResponse(5, (PeerRecord(f"candidate-{len(calls)}", "127.0.0.1", 7000),))

    worker = client.DiscoveryWorker("http://isolated.invalid", FILE_ID, "p", 1234, events,
                                    announce_fn=announce)

    def after_wait(count):
        if count == 1:
            assert events.get_nowait() == "occupied"
        else:
            worker._stop.set()

    worker._wake = ScriptedWait(worker, after_wait)
    worker._send_stopped = False
    worker._run()
    assert worker.dropped_events == 1
    assert calls == ["started", "update"]
    fresh = events.get_nowait()
    assert isinstance(fresh, client.PeersDiscovered)
    assert [peer.peer_id for peer in fresh.peers] == ["candidate-2"]
    assert events.empty()


def test_completed_interrupts_pending_retry_and_stopped_follows_success():
    calls = []

    def announce(*args, **kwargs):
        calls.append(args[4])
        if len(calls) == 1:
            raise client.TrackerRequestError("unreachable", "predeclared outage")
        return client.AnnounceResponse(5, ())

    worker = client.DiscoveryWorker("http://isolated.invalid", FILE_ID, "p", 1234, queue.Queue(),
                                    announce_fn=announce)

    def after_wait(count):
        if count == 1:
            worker.mark_completed()
        else:
            worker._stop.set()

    worker._wake = ScriptedWait(worker, after_wait)
    worker._run()
    assert calls == ["started", "completed", "stopped"]
    assert not worker._completed_pending.is_set()
