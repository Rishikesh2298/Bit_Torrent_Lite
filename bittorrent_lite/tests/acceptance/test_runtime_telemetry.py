"""PREPARE instrumentation regressions; fake transport is not TCP evidence."""
import json
import struct

import pytest

from bittorrent_lite.application.adapters import SchedulerBridge
from bittorrent_lite.application.runtime import PeerRuntime
from bittorrent_lite.common.config import PROTOCOL_VERSION
from bittorrent_lite.examples.scheduler_dependencies import ManualClock
from bittorrent_lite.networking import messages as m
from bittorrent_lite.networking import runtime_connection as rc
from bittorrent_lite.tests.integration.test_peer_runtime import Backend
from bittorrent_lite.tests.integration.test_scheduler_integration import disk_store


MESSAGES = [m.Handshake(PROTOCOL_VERSION, "f" * 64, "remote"),
            m.BitfieldMsg([1, 0]), m.Have(1), m.Interested(), m.NotInterested(),
            m.Choke(), m.Unchoke(), m.Request(13, 1), m.Piece(13, 1, b"a\x00\xffb"),
            m.Cancel(13, 1), m.Reject(13, 1, "unavailable")]


def wire_bytes(message):
    header = dict(message.to_header(), payload_length=len(message.payload))
    encoded = json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return struct.pack("!I", len(encoded)) + encoded + message.payload


class Socket:
    def __init__(self, incoming=b"", fail=False):
        self.incoming = incoming
        self.written = bytearray()
        self.fail = fail
        self.closed = False

    def settimeout(self, timeout):
        pass

    def getsockname(self):
        return ("127.0.0.1", 19001)

    def getpeername(self):
        return ("127.0.0.1", 19002)

    def sendall(self, data):
        if self.fail:
            self.written.extend(data[:3])
            raise OSError("failure after an unknowable-to-caller partial write")
        self.written.extend(data)

    def recv(self, size):
        # Fragment every prefix/header/payload across small reads.
        result, self.incoming = self.incoming[:min(size, 3)], self.incoming[min(size, 3):]
        return result

    def shutdown(self, how):
        pass

    def close(self):
        self.closed = True


def connection(sock, forwarded):
    result = rc.RuntimeConnection(sock, peer_id="local", file_id="f" * 64,
                                  bitfield=[0, 0], ready=lambda conn: None,
                                  event=lambda conn, kind, message: forwarded.append((kind, message)),
                                  disconnected=lambda *args: None)
    result.connection_id = 9
    result.remote_peer_id = "remote"
    result._running = True
    result.handshake_complete = True
    result.activate()
    return result


def capture(monkeypatch):
    records = []
    monkeypatch.setattr(rc.run_log, "emit", lambda event, **fields:
                        records.append(dict(event=event, **fields)))
    return records


@pytest.mark.parametrize("message", MESSAGES, ids=lambda message: message.type)
def test_completed_write_records_exact_frame_not_enqueue(monkeypatch, message):
    records, forwarded, sock = capture(monkeypatch), [], Socket()
    conn = connection(sock, forwarded)
    conn.send(message)
    assert not [r for r in records if r["event"] == "frame_sent"]
    assert forwarded == []
    conn._writer_queue.put_nowait(None)
    conn._writer_loop()
    completed = [r for r in records if r["event"] == "frame_sent"]
    assert len(completed) == 1
    record = completed[0]
    assert bytes(sock.written) == wire_bytes(message)
    assert record["frame_bytes"] == len(sock.written)
    assert record["frame_complete"] is True
    assert record["message_type"] == message.type
    assert record["connection_id"] == 9 and record["remote"] == "remote"
    assert record["local_endpoint"] == ["127.0.0.1", 19001]
    assert record["remote_endpoint"] == ["127.0.0.1", 19002]
    assert record["request_id"] == getattr(message, "request_id", None)
    assert record["piece"] == getattr(message, "piece_index", None)
    assert record["payload_bytes"] == len(message.payload)
    expected = [] if isinstance(message, (m.Handshake, m.BitfieldMsg)) else [("sent", message)]
    assert forwarded == expected
    conn.close()


@pytest.mark.parametrize("message", MESSAGES, ids=lambda message: message.type)
def test_complete_fragmented_read_records_actual_frame_bytes(monkeypatch, message):
    records, forwarded = capture(monkeypatch), []
    encoded = wire_bytes(message)
    conn = connection(Socket(encoded), forwarded)
    delivered = []
    monkeypatch.setattr(conn, "_dispatch_message", delivered.append)
    conn._reader_loop()
    assert delivered == [message]
    received = [r for r in records if r["event"] == "frame_received"]
    assert len(received) == 1
    assert received[0]["frame_bytes"] == len(encoded)
    assert received[0]["payload_bytes"] == len(message.payload)
    assert received[0]["message_type"] == message.type
    assert conn.closed


def test_partial_send_failure_never_claims_byte_count_or_upload(monkeypatch):
    records, forwarded, sock = capture(monkeypatch), [], Socket(fail=True)
    conn = connection(sock, forwarded)
    message = m.Piece(13, 1, b"payload")
    conn.send(message)
    conn._writer_loop()
    assert len(sock.written) == 3  # Only the controlled provider knows this.
    failures = [r for r in records if r["event"] == "frame_send_failed"]
    assert len(failures) == 1 and failures[0]["frame_bytes"] is None
    assert failures[0]["partial_bytes_known"] is False
    assert not [r for r in records if r["event"] in ("frame_sent", "piece_uploaded")]
    assert ("send_failed", message) in forwarded
    assert not [kind for kind, message in forwarded if kind == "sent"]
    assert conn.closed


def test_incomplete_receive_does_not_count_complete_frame(monkeypatch):
    records = capture(monkeypatch)
    encoded = wire_bytes(m.Piece(2, 1, b"payload"))[:-2]
    conn = connection(Socket(encoded), [])
    conn._reader_loop()
    assert not [r for r in records if r["event"] == "frame_received"]
    failures = [r for r in records if r["event"] == "frame_receive_failed"]
    assert len(failures) == 1 and failures[0]["received_bytes"] == len(encoded)


def bridge_with_request(tmp_path):
    store, pieces = disk_store(tmp_path, data=b"abcdefghij")
    records, sent = [], []
    bridge = SchedulerBridge(ManualClock(), observe=lambda event, **fields:
                             records.append(dict(event=event, **fields)))
    coordinator = bridge.create_coordinator(store)
    bridge.register(17, "source-z", sent.append)
    bridge.received(17, m.BitfieldMsg([1] * len(pieces)))
    bridge.received(17, m.Unchoke())
    bridge.drain(coordinator)
    request = coordinator.snapshot()["pending"][0]
    return store, pieces, bridge, coordinator, request, records


def test_committed_verification_has_exact_source_and_request_provenance(tmp_path):
    store, pieces, bridge, coordinator, request, records = bridge_with_request(tmp_path)
    message = m.Piece(request["request_id"], request["piece_index"], pieces[request["piece_index"]])
    try:
        bridge.received(17, message)
        bridge.drain(coordinator)
        verified = [r for r in records if r["event"] == "PIECE_VERIFIED"]
        assert verified == [{"event": "PIECE_VERIFIED", "connection_id": 17,
                             "request_id": message.request_id, "piece": message.piece_index,
                             "remote": "source-z", "bytes": len(message.payload)}]
        bridge.received(17, message)
        bridge.received(17, m.Piece(999999, 1, b"xxxx"))
        bridge.drain(coordinator)
        assert len([r for r in records if r["event"] == "PIECE_VERIFIED"]) == 1
        assert len([r for r in records if r["event"] == "PIECE_IGNORED"]) == 2
        snapshots = [r for r in records if r["event"] == "SCHEDULER_SNAPSHOT"]
        assert len(snapshots) == 6
        assert snapshots[-1]["pending"] == coordinator.snapshot()["pending"]
        assert snapshots[-1]["uploads"] == coordinator.snapshot()["uploads"]
        assert snapshots[-1]["connected_peers"] == 1
    finally:
        coordinator.shutdown()
        bridge.shutdown()


@pytest.mark.parametrize("fault, expected", [
    ("length", "length_mismatch"), ("hash", "hash_mismatch"),
    ("disk", "local_io_error"), ("false", "store_rejected_unclassified")])
def test_verification_failure_classification_does_not_invent_hash_failure(
        tmp_path, monkeypatch, fault, expected):
    store, pieces, bridge, coordinator, request, records = bridge_with_request(tmp_path)
    data = pieces[request["piece_index"]]
    haves = []
    monkeypatch.setattr(bridge, 'send_have', lambda *args: haves.append(args))
    if fault == "length":
        data = data[:-1]
    elif fault == "hash":
        data = bytes([data[0] ^ 1]) + data[1:]
    elif fault == "disk":
        def failed_write(index, payload):
            raise OSError("controlled local storage failure")
        monkeypatch.setattr(store, "verify_and_store", failed_write)
    else:
        monkeypatch.setattr(store, "verify_and_store", lambda index, payload: False)
    try:
        bridge.received(17, m.Piece(request["request_id"], request["piece_index"], data))
        bridge.drain(coordinator)
        outcomes = [r for r in records if r["event"] == "PIECE_VERIFICATION"]
        assert len(outcomes) == 1 and outcomes[0]["outcome"] == expected
        assert not [r for r in records if r["event"] == "PIECE_VERIFIED"]
        assert haves == []
        assert store.get_bitfield() == [0] * len(pieces)
        assert coordinator.snapshot()["verified_download_bytes"] == 0
        assert bool(coordinator.snapshot()["storage_error"]) == (fault == "disk")
    finally:
        coordinator.shutdown()
        bridge.shutdown()


def test_same_length_hash_failure_retries_healthy_alternate_and_commits_only_valid_piece(tmp_path):
    """P-T09: real disk/bridge, injected protocol events, no TCP claim."""
    store, pieces = disk_store(tmp_path, data=b"four", size=4)
    records, bad_outgoing, good_outgoing = [], [], []
    bridge = SchedulerBridge(ManualClock(), observe=lambda event, **fields:
                             records.append(dict(event=event, **fields)))
    coordinator = bridge.create_coordinator(store)
    try:
        bridge.register(1, "bad-source", bad_outgoing.append)
        bridge.received(1, m.BitfieldMsg([1]))
        bridge.received(1, m.Unchoke())
        bridge.drain(coordinator)
        original = next(message for message in bad_outgoing if isinstance(message, m.Request))
        wrong_hash = bytes([pieces[0][0] ^ 1]) + pieces[0][1:]
        assert len(wrong_hash) == len(pieces[0]) == 4
        bridge.received(1, m.Piece(original.request_id, 0, wrong_hash))
        bridge.drain(coordinator)
        assert coordinator.snapshot()["pending"] == []
        assert store.get_bitfield() == [0]
        assert not [message for message in bad_outgoing if isinstance(message, m.Have)]
        assert [record["outcome"] for record in records
                if record["event"] == "PIECE_VERIFICATION"] == ["hash_mismatch"]
        assert not [record for record in records if record["event"] == "PIECE_VERIFIED"]

        bridge.register(2, "healthy-source", good_outgoing.append)
        bridge.received(2, m.BitfieldMsg([1]))
        bridge.received(2, m.Unchoke())
        bridge.drain(coordinator)
        retry = next(message for message in good_outgoing if isinstance(message, m.Request))
        assert retry.piece_index == original.piece_index == 0
        pending = coordinator.snapshot()["pending"]
        assert len(pending) == 1 and pending[0]["connection_id"] == 2
        assert pending[0]["request_id"] == retry.request_id
        bridge.received(2, m.Piece(retry.request_id, 0, pieces[0]))
        bridge.drain(coordinator)
        assert store.get_bitfield() == [1] and store.read_piece(0) == pieces[0]
        assert coordinator.snapshot()["owned"] == 1
        assert coordinator.snapshot()["pending"] == []
        assert coordinator.snapshot()["verified_download_bytes"] == 4
        verified = [record for record in records if record["event"] == "PIECE_VERIFIED"]
        assert len(verified) == 1
        assert (verified[0]["connection_id"], verified[0]["request_id"],
                verified[0]["piece"], verified[0]["bytes"]) == (2, retry.request_id, 0, 4)
        assert [record["outcome"] for record in records
                if record["event"] == "PIECE_VERIFICATION"] == ["hash_mismatch", "stored"]
        assert [message for message in bad_outgoing if isinstance(message, m.Have)] == [m.Have(0)]
        assert [message for message in good_outgoing if isinstance(message, m.Have)] == [m.Have(0)]
    finally:
        coordinator.shutdown()
        bridge.shutdown()


def test_status_and_real_sampler_hook_are_periodic_with_manual_clock(tmp_path):
    store, _ = disk_store(tmp_path)
    records, calls, clock = [], [], ManualClock()
    def sampler():
        calls.append(clock.now())
        return {"rss_bytes": 1234, "cpu_seconds": .125, "threads": 1}
    runtime = PeerRuntime("local", store, tmp_path / "out", Backend(), clock=clock,
                          emit=records.append, resource_sampler=sampler)
    try:
        runtime.start()
        runtime.step()
        clock.advance(.999)
        runtime.step()
        assert len([r for r in records if r["event"] == "STATUS"]) == 1
        clock.advance(.001)
        runtime.step()
        statuses = [r for r in records if r["event"] == "STATUS"]
        assert len(statuses) == 2 and calls == [0, 1]
        assert all(r["connected_peers"] == 0 and r["pending_requests"] == 0 for r in statuses)
        samples = [r for r in records if r["event"] == "RESOURCE_SAMPLE"]
        assert [r["metrics"] for r in samples] == [sampler_metrics()] * 2
    finally:
        runtime.shutdown()


def sampler_metrics():
    return {"rss_bytes": 1234, "cpu_seconds": .125, "threads": 1}


@pytest.mark.parametrize("sample", [{"rss": float("nan")}, {"cpu": float("inf")},
                                    {"threads": True}, {"rss": -1}, {}, None],
                         ids=["nan", "infinite", "bool", "negative", "empty", "null"])
def test_invalid_resource_samples_are_explicit_errors_not_zero(tmp_path, sample):
    store, _ = disk_store(tmp_path)
    records = []
    runtime = PeerRuntime("local", store, tmp_path / "out", Backend(), clock=ManualClock(),
                          emit=records.append, resource_sampler=lambda: sample)
    try:
        runtime.start()
        runtime.step()
        assert len([r for r in records if r["event"] == "RESOURCE_SAMPLE_ERROR"]) == 1
        assert not [r for r in records if r["event"] == "RESOURCE_SAMPLE"]
    finally:
        runtime.shutdown()


@pytest.mark.parametrize("provider", [None, "raises"], ids=["absent", "raises"])
def test_missing_or_failed_resource_provider_is_visible(tmp_path, provider):
    store, _ = disk_store(tmp_path)
    records = []
    def fail():
        raise OSError("process no longer available")
    runtime = PeerRuntime("local", store, tmp_path / "out", Backend(), clock=ManualClock(),
                          emit=records.append, resource_sampler=fail if provider else None)
    try:
        runtime.start()
        runtime.step()
        event = "RESOURCE_SAMPLE_ERROR" if provider else "RESOURCE_SAMPLE_UNAVAILABLE"
        assert len([r for r in records if r["event"] == event]) == 1
        assert not [r for r in records if r["event"] == "RESOURCE_SAMPLE"]
    finally:
        runtime.shutdown()
