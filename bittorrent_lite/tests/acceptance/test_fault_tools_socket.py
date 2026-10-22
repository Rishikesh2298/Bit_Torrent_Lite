"""PREPARE integration of owned fault helpers with actual loopback TCP sockets.

These tests are not an end-to-end download, scheduler recovery, or experiment.
"""
import hashlib
import json
import select
import socket
import time

import pytest

from bittorrent_lite.acceptance_tools.faults import (
    Drop, ExpectEOF, FaultTrace, Pause, Receive, RelayRule, Send,
    SocketFaultPeer, SocketFaultProxy, frame,
)
from bittorrent_lite.networking.framing import recv_message


def read_all(sock):
    chunks = []
    while True:
        data = sock.recv(65536)
        if not data:
            return b"".join(chunks)
        chunks.append(data)


def evidence(path):
    result = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert result[0]["event"] == "trace_started"
    assert result[-1]["event"] == "trace_closed"
    assert [row["sequence"] for row in result] == list(range(len(result)))
    for row in result:
        if "data_hex" in row:
            data = bytes.fromhex(row["data_hex"])
            assert row["byte_count"] == len(data)
            assert row["sha256"] == hashlib.sha256(data).hexdigest()
    return result


@pytest.mark.parametrize("mode", ["one-byte-fragments", "three-coalesced-frames"])
def test_real_peer_fragmentation_coalescing_and_binary_frames(tmp_path, mode):
    payload = b"\x00\xff\x80\n"
    raw = (
        frame({"type": "HANDSHAKE", "protocol_version": 1, "file_id": "f" * 64,
               "peer_id": "caf\u00e9", "payload_length": 0})
        + frame({"type": "PIECE", "request_id": 1, "piece_index": 0, "payload_length": 4}, payload)
        + frame({"type": "INTERESTED", "payload_length": 0})
    )
    fragments = (1,) * len(raw) if mode == "one-byte-fragments" else ()
    trace_path = tmp_path / "trace.jsonl"
    with FaultTrace(trace_path, mode) as trace:
        with SocketFaultPeer([Send(raw, fragments=fragments), Drop("complete fixture")], trace, timeout=3) as peer:
            with socket.create_connection(peer.address, timeout=2) as client:
                first, second, third = [recv_message(client) for _ in range(3)]
                assert (first.type, first.peer_id) == ("HANDSHAKE", "caf\u00e9")
                assert (second.type, second.request_id, second.piece_index, second.payload) == ("PIECE", 1, 0, payload)
                assert third.type == "INTERESTED"
                assert recv_message(client) is None
            peer.wait(3)
        assert not peer.alive
    writes = [row for row in evidence(trace_path) if row["event"] == "socket_write"]
    assert b"".join(bytes.fromhex(row["data_hex"]) for row in writes) == raw
    assert all(row["local"][0] == row["remote"][0] == "127.0.0.1" for row in writes)
    if fragments:
        assert [row["byte_count"] for row in writes] == [1] * len(raw)


@pytest.mark.parametrize("mode", ["delay", "trickle", "bandwidth"])
@pytest.mark.parametrize("post_connect_delay", [0.0, 0.12], ids=["immediate-trigger", "delayed-client-scheduling"])
def test_real_peer_timing_rules_are_observed_and_bounded(tmp_path, mode, post_connect_delay):
    raw = b"x" * 1024
    start_token = b"begin-v1"
    timed_actions = {
        "delay": [Pause(0.08), Send(raw)],
        "trickle": [Send(raw, fragments=(256,) * 4, gap_s=0.03)],
        "bandwidth": [Send(raw, bytes_per_second=8192)],
    }[mode]
    # accept() may return before create_connection() returns to this thread.
    # The exact start token prevents the timed action starting in that gap or
    # while this client is descheduled after connecting. This is an actual TCP
    # causal gate, not an assumption that the two threads begin together.
    script = [Receive(len(start_token), start_token), *timed_actions]
    lower_bound = {"delay": 0.07, "trickle": 0.08, "bandwidth": 0.115}[mode]
    trace_path = tmp_path / "trace.jsonl"
    with FaultTrace(trace_path, mode) as trace:
        with SocketFaultPeer(script, trace, timeout=3) as peer:
            with socket.create_connection(peer.address, timeout=2) as client:
                time.sleep(post_connect_delay)
                assert select.select([client], [], [], 0)[0] == []
                started = time.monotonic()
                trace.emit("client_timing_origin", measurement_start=started,
                           post_connect_delay=post_connect_delay)
                client.sendall(start_token)
                assert read_all(client) == raw
                peer.wait(3)
                assert time.monotonic() - started >= lower_bound
        assert not peer.alive
    records = evidence(trace_path)
    origin = next(row for row in records if row["event"] == "client_timing_origin")
    received_token = [row for row in records if row["event"] == "socket_read"]
    assert b"".join(bytes.fromhex(row["data_hex"]) for row in received_token) == start_token
    assert all(row["monotonic"] >= origin["measurement_start"] for row in received_token)
    timed_start = next(row for row in records if row["event"] == "action_started" and row["step"] == 1)
    assert timed_start["sequence"] > received_token[-1]["sequence"]
    writes = [row for row in records if row["event"] == "socket_write"]
    assert sum(row["byte_count"] for row in writes) == 1024
    if mode == "delay":
        pause_end = next(row for row in records if row["event"] == "action_completed" and row["step"] == 1)
        assert pause_end["monotonic"] - timed_start["monotonic"] >= lower_bound
    if mode == "trickle":
        assert {row["fragment"] for row in writes} == {0, 1, 2, 3}
        assert writes[-1]["monotonic"] - writes[0]["monotonic"] >= 0.08


def test_real_peer_controlled_payload_corruption_logs_exact_changed_byte(tmp_path):
    payload = b"valid-piece"
    raw = frame({"type": "PIECE", "request_id": 1, "piece_index": 0,
                 "payload_length": len(payload)}, payload)
    trace_path = tmp_path / "trace.jsonl"
    with FaultTrace(trace_path, "corrupt-payload") as trace:
        with SocketFaultPeer([Send(raw, corrupt_offset=len(raw) - 1, xor_mask=2)], trace, timeout=3) as peer:
            with socket.create_connection(peer.address, timeout=2) as client:
                received = recv_message(client)
                assert received.payload == payload[:-1] + bytes((payload[-1] ^ 2,))
                assert hashlib.sha256(received.payload).digest() != hashlib.sha256(payload).digest()
            peer.wait(3)
    records = evidence(trace_path)
    triggers = [row for row in records if row["event"] == "fault_triggered"]
    assert len(triggers) == 1
    assert (triggers[0]["fault"], triggers[0]["offset"], triggers[0]["xor_mask"]) == ("peer_corruption", len(raw) - 1, 2)
    actual = b"".join(bytes.fromhex(row["data_hex"]) for row in records if row["event"] == "socket_write")
    assert actual[:-1] == raw[:-1] and actual[-1] == raw[-1] ^ 2


@pytest.mark.parametrize("cut", [1, 3, 7, -2], ids=["mid-prefix-one", "mid-prefix-three", "mid-header", "mid-payload"])
def test_real_peer_midframe_drop_is_not_clean_close(tmp_path, cut):
    raw = frame({"type": "PIECE", "request_id": 1, "piece_index": 0, "payload_length": 4}, b"data")
    trace_path = tmp_path / "trace.jsonl"
    with FaultTrace(trace_path, "mid-frame-drop") as trace:
        with SocketFaultPeer([Send(raw[:cut]), Drop("declared incomplete frame")], trace, timeout=3) as peer:
            with socket.create_connection(peer.address, timeout=2) as client:
                with pytest.raises(ConnectionError, match="closed"):
                    recv_message(client)
            peer.wait(3)
    records = evidence(trace_path)
    assert any(row["event"] == "fault_triggered" and row["fault"] == "connection_drop" for row in records)
    assert sum(row["byte_count"] for row in records if row["event"] == "socket_write") == len(raw[:cut])


def test_fault_peer_worker_mismatch_and_deadline_failures_are_observable(tmp_path):
    with FaultTrace(tmp_path / "mismatch.jsonl", "expected-helper-negative") as trace:
        with SocketFaultPeer([Receive(4, b"good")], trace, timeout=2) as peer:
            with socket.create_connection(peer.address, timeout=1) as client:
                client.sendall(b"evil")
            with pytest.raises(RuntimeError, match="predeclared oracle"):
                peer.wait(3)
        assert not peer.alive
    assert any(row["event"] == "script_failed" for row in evidence(tmp_path / "mismatch.jsonl"))
    with FaultTrace(tmp_path / "deadline.jsonl", "expected-helper-negative") as trace:
        with SocketFaultPeer([Receive(1)], trace, timeout=0.15) as peer:
            with pytest.raises(RuntimeError, match="deadline"):
                peer.wait(2)
        assert not peer.alive
    assert any(row["event"] == "script_failed" and row["error"] == "TimeoutError"
               for row in evidence(tmp_path / "deadline.jsonl"))


def test_proxy_bidirectional_bytes_exact_corruption_drop_and_cleanup(tmp_path):
    with FaultTrace(tmp_path / "upstream.jsonl", "proxy-upstream") as upstream_trace:
        with SocketFaultPeer([Receive(4, b"ping"), Send(b"abcdefgh"), ExpectEOF()], upstream_trace, timeout=4) as peer:
            with FaultTrace(tmp_path / "proxy.jsonl", "proxy") as proxy_trace:
                with SocketFaultProxy(peer.address, proxy_trace,
                                      outbound=RelayRule(chunk_size=2, delay_s=0.01),
                                      inbound=RelayRule(chunk_size=8, corrupt_offset=1, xor_mask=1,
                                                        drop_after=4, bytes_per_second=128), timeout=3) as proxy:
                    with socket.create_connection(proxy.address, timeout=2) as client:
                        client.sendall(b"ping")
                        client.shutdown(socket.SHUT_WR)
                        assert read_all(client) == b"accd"
                    proxy.wait(4)
                assert not proxy.alive
            peer.wait(4)
        assert not peer.alive and peer.received == [b"ping"]
    records = evidence(tmp_path / "proxy.jsonl")
    triggers = {(row["fault"], row["direction"], row["offset"])
                for row in records if row["event"] == "fault_triggered"}
    assert triggers == {("proxy_corruption", "inbound", 1), ("proxy_drop", "inbound", 4)}
    for direction, expected in (("outbound", b"ping"), ("inbound", b"accd")):
        writes = [row for row in records if row["event"] == "proxy_write" and row["direction"] == direction]
        assert b"".join(bytes.fromhex(row["data_hex"]) for row in writes) == expected
        assert all(row["local"][0] == row["remote"][0] == "127.0.0.1" for row in writes)
    assert records[-2]["event"] == "proxy_exited" and records[-2]["live_relays"] == 0


def test_proxy_missing_trigger_cannot_report_success(tmp_path):
    with FaultTrace(tmp_path / "upstream.jsonl", "untriggered-upstream") as upstream_trace:
        with SocketFaultPeer([Send(b"short"), ExpectEOF()], upstream_trace, timeout=3) as peer:
            with FaultTrace(tmp_path / "proxy.jsonl", "expected-helper-negative") as trace:
                with SocketFaultProxy(peer.address, trace, inbound=RelayRule(corrupt_offset=10), timeout=2) as proxy:
                    with socket.create_connection(proxy.address, timeout=1) as client:
                        client.shutdown(socket.SHUT_WR)
                        assert read_all(client) == b"short"
                    with pytest.raises(AssertionError, match="untriggered"):
                        proxy.wait(3)
                assert not proxy.alive
            peer.wait(3)


def test_close_only_stops_owned_idle_listeners(tmp_path):
    with socket.socket() as unrelated:
        unrelated.bind(("127.0.0.1", 0))
        unrelated.listen(1)
        with FaultTrace(tmp_path / "trace.jsonl", "owned-cleanup") as trace:
            peer = SocketFaultPeer([Receive(1)], trace, timeout=2).start()
            peer.close()
            assert not peer.alive
            with pytest.raises(RuntimeError, match="before script completion"):
                peer.wait(1)
            with socket.create_connection(unrelated.getsockname(), timeout=1) as client:
                accepted, _ = unrelated.accept()
                with accepted:
                    client.sendall(b"x")
                    assert accepted.recv(1) == b"x"
