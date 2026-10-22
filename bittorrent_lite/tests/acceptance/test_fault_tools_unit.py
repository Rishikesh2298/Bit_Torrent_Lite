"""PREPARE fault-helper units: synthetic or owned filesystem evidence only."""
import errno
import hashlib
import json
from pathlib import Path

import pytest

from bittorrent_lite.acceptance_tools.faults import (
    Drop, FaultTrace, Pause, Receive, RelayRule, Send, SocketFaultPeer,
    SocketFaultProxy, StorageFault, StorageFaults, corrupt_byte, frame,
)


def rows(path):
    """Independent trace oracle; no helper verifier supplies expected results."""
    result = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert result[0]["event"] == "trace_started"
    assert result[-1]["event"] == "trace_closed"
    assert [row["sequence"] for row in result] == list(range(len(result)))
    assert all(row["schema"] == "btl-fault-v1" for row in result)
    assert len({row["owner"] for row in result}) == 1
    assert [row["monotonic"] for row in result] == sorted(row["monotonic"] for row in result)
    for row in result:
        if "data_hex" in row:
            data = bytes.fromhex(row["data_hex"])
            assert row["byte_count"] == len(data)
            assert row["sha256"] == hashlib.sha256(data).hexdigest()
    return result


def test_fault_frame_and_corruption_have_independent_byte_oracles():
    header = b'{"type":"PIECE","payload_length":3,"tag":"caf\xc3\xa9"}'
    payload = b"\x00\xff\x80"
    assert frame({"type": "PIECE", "payload_length": 3, "tag": "caf\u00e9"}, payload) == (
        len(header).to_bytes(4, "big") + header + payload)
    assert corrupt_byte(payload, 1, 0x80) == b"\x00\x7f\x80"
    assert payload == b"\x00\xff\x80"


@pytest.mark.parametrize("factory", [
    lambda: Send(b"abc", fragments=(1, 1)),
    lambda: Send(b"abc", fragments=(0, 3)),
    lambda: Send(b"abc", gap_s=float("nan")),
    lambda: Send(b"abc", bytes_per_second=0),
    lambda: Send(b"abc", corrupt_offset=3),
    lambda: Receive(True),
    lambda: Receive(3, b"ab"),
    lambda: Pause(-1),
    lambda: Drop(""),
    lambda: RelayRule(chunk_size=65537),
    lambda: RelayRule(corrupt_offset=5, drop_after=5),
    lambda: RelayRule(drop_after=9, max_bytes=8),
    lambda: StorageFault("rename"),
    lambda: StorageFault("replace", after_bytes=1),
    lambda: StorageFault("write", call=0),
    lambda: corrupt_byte(b"a", 0, 256),
], ids=["fragment-sum", "zero-fragment", "nan-gap", "zero-bandwidth", "corrupt-past-end",
        "bool-length", "expected-length", "negative-pause", "empty-drop-reason", "huge-chunk",
        "corrupt-after-drop", "drop-after-budget", "unknown-storage-op", "partial-replace",
        "zero-call", "oversize-mask"])
def test_fault_actions_reject_invalid_or_unbounded_arguments(factory):
    with pytest.raises(ValueError):
        factory()


def test_trace_is_exclusive_closed_and_byte_exact(tmp_path):
    path = tmp_path / "trace.jsonl"
    with FaultTrace(path, "unit-trace") as trace:
        trace.bytes("actual", b"\x00\xff")
        with pytest.raises(FileExistsError):
            FaultTrace(path, "replacement")
    with pytest.raises(RuntimeError, match="closed"):
        trace.emit("late")
    evidence = rows(path)
    assert evidence[1]["data_hex"] == "00ff"
    assert evidence[1]["byte_count"] == 2


def test_peer_scripts_forbid_unreachable_actions_and_proxy_remote_targets(tmp_path):
    with FaultTrace(tmp_path / "trace.jsonl", "invalid-plan") as trace:
        with pytest.raises(ValueError, match="final action"):
            SocketFaultPeer([Drop(), Send(b"unreachable")], trace)
        with pytest.raises(ValueError, match="loopback"):
            SocketFaultProxy(("192.0.2.1", 8000), trace)


@pytest.mark.parametrize("phase", ["normal", "assembly"])
@pytest.mark.parametrize("operation", ["read", "write", "replace"])
@pytest.mark.parametrize("error_number", [errno.EIO, errno.EACCES, errno.ENOSPC],
                         ids=["io", "permission", "simulated-disk-full"])
def test_storage_fault_exact_call_partial_bytes_and_preserved_inputs(tmp_path, phase, operation, error_number):
    key = operation if phase == "normal" else f"assembly.{operation}"
    trace_path = tmp_path / "trace.jsonl"
    with FaultTrace(trace_path, "storage-injection") as trace:
        adapter = StorageFaults(tmp_path / "owned", trace, [
            StorageFault(key, call=2, after_bytes=0 if operation == "replace" else 3,
                         error_number=error_number)])
        source = adapter.root / "source.bin"
        destination = adapter.root / "destination.bin"
        source.write_bytes(b"ABCDEFGH")
        destination.write_bytes(b"original-output")
        with adapter.phase(phase):
            if operation == "read":
                with adapter.open(source) as stream:
                    assert stream.read(1) == b"A"
                    with pytest.raises(OSError) as failure:
                        stream.read(7)
                    assert stream.tell() == 4
                assert source.read_bytes() == b"ABCDEFGH"
                assert destination.read_bytes() == b"original-output"
            elif operation == "write":
                with adapter.open(adapter.root / "partial.bin", "wb") as stream:
                    assert stream.write(b"ok") == 2
                    with pytest.raises(OSError) as failure:
                        stream.write(b"123456")
                assert (adapter.root / "partial.bin").read_bytes() == b"ok123"
                assert source.read_bytes() == b"ABCDEFGH"
                assert destination.read_bytes() == b"original-output"
            else:
                first = adapter.root / "first.bin"
                first.write_bytes(b"first")
                adapter.replace(first, adapter.root / "first-result.bin")
                with pytest.raises(OSError) as failure:
                    adapter.replace(source, destination)
                assert source.read_bytes() == b"ABCDEFGH"
                assert destination.read_bytes() == b"original-output"
                assert (adapter.root / "first-result.bin").read_bytes() == b"first"
        assert failure.value.errno == error_number
        assert adapter.triggered == [(key, 2)]
        adapter.assert_finished()
    evidence = rows(trace_path)
    triggers = [row for row in evidence if row["event"] == "fault_triggered"]
    assert [(row["operation"], row["call"], row["errno"]) for row in triggers] == [(key, 2, error_number)]
    partials = [row for row in evidence if row["event"] == f"storage_partial_{operation}"]
    if operation != "replace":
        assert bytes.fromhex(partials[0]["data_hex"]) == (b"BCD" if operation == "read" else b"123")


def test_storage_adapter_rejects_escapes_reuse_and_untriggered_or_leaked_handles(tmp_path):
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"unrelated")
    with FaultTrace(tmp_path / "trace.jsonl", "ownership") as trace:
        adapter = StorageFaults(tmp_path / "owned", trace, [StorageFault("read")])
        for candidate in (outside, Path("..") / "outside.bin", adapter.root):
            with pytest.raises(ValueError, match="inside"):
                adapter.open(candidate, "wb")
        with pytest.raises(FileExistsError):
            StorageFaults(adapter.root, trace)
        with pytest.raises(AssertionError, match="untriggered"):
            adapter.assert_finished()
        path = adapter.root / "input.bin"
        path.write_bytes(b"safe")
        stream = adapter.open(path)
        try:
            with pytest.raises(AssertionError, match="remain open"):
                adapter.assert_finished()
            with pytest.raises(OSError):
                stream.read()
        finally:
            stream.close()
        adapter.assert_finished()
    assert outside.read_bytes() == b"unrelated"
    assert path.read_bytes() == b"safe"


def test_assembly_phase_restores_after_exception_and_duplicate_triggers_rejected(tmp_path):
    with FaultTrace(tmp_path / "trace.jsonl", "phase") as trace:
        with pytest.raises(ValueError, match="ambiguous"):
            StorageFaults(tmp_path / "invalid", trace, [StorageFault("read"), StorageFault("read")])
        assert not (tmp_path / "invalid").exists()
        adapter = StorageFaults(tmp_path / "owned", trace, [StorageFault("assembly.read")])
        source = adapter.root / "input.bin"
        source.write_bytes(b"payload")
        with pytest.raises(OSError):
            with adapter.phase("assembly"), adapter.open(source) as stream:
                stream.read()
        with adapter.open(source) as stream:
            assert stream.read() == b"payload"
        adapter.assert_finished()
