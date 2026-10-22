"""Owned filesystem integration of the fault adapter with the real FileStore."""
import builtins
import errno
import hashlib
import json
from pathlib import Path

import pytest

from bittorrent_lite.acceptance_tools.faults import FaultTrace, StorageFault, StorageFaults
from bittorrent_lite.common.types import TorrentMetadata
from bittorrent_lite.storage import file_store as store_module


@pytest.mark.parametrize("operation", ["read", "write", "replace", "assembly.read", "assembly.write", "assembly.replace"])
def test_filestore_fault_seams_preserve_source_output_and_ownership(tmp_path, monkeypatch, operation):
    data = b"01234567ABCDEFGH"
    metadata = TorrentMetadata(1, "fixture.bin", len(data), 8,
                               [hashlib.sha256(data[:8]).hexdigest(), hashlib.sha256(data[8:]).hexdigest()],
                               hashlib.sha256(data).hexdigest())
    trace_path = tmp_path / "trace.jsonl"
    # Assembly reads first validate two stored pieces, then read again to write
    # the temporary output. The third read is the actual assembly-read seam.
    call = 3 if operation == "assembly.read" else 1
    partial = 0 if operation.endswith("replace") else 3
    with FaultTrace(trace_path, operation) as trace:
        adapter = StorageFaults(tmp_path / "owned", trace, [
            StorageFault(operation, call=call, after_bytes=partial, error_number=errno.ENOSPC if "write" in operation else errno.EACCES)])
        source = adapter.root / "source.bin"
        output = adapter.root / "completed.bin"
        source.write_bytes(data)
        output.write_bytes(b"pre-existing-output")
        store = store_module.FileStore(metadata, "f" * 64, str(adapter.root / "pieces"))
        populated = operation == "read" or operation.startswith("assembly.")
        if populated:
            assert store.verify_and_store(0, data[:8])
            assert store.verify_and_store(1, data[8:])
        original_open = builtins.open
        original_path = Path
        # Reconstruct after binding, so the FileStore's Path instances use the
        # local adapter while existing pieces remain ordinary real disk files.
        with monkeypatch.context() as injection:
            adapter.bind_module(injection, store_module)
            exercised = store_module.FileStore(metadata, "f" * 64, str(adapter.root / "pieces"))
            if operation.startswith("assembly."):
                assert exercised.has_piece(0)
                assert exercised.has_piece(1)
            # Preloading above must not consume the declared normal read fault.
            # Normal read is therefore exercised with the original store, while
            # assembly calls use the rebound path objects and scoped counters.
            phase = "assembly" if operation.startswith("assembly.") else "normal"
            with adapter.phase(phase):
                with pytest.raises(OSError) as failure:
                    if operation == "read":
                        store.read_piece(0)
                    elif operation.startswith("assembly."):
                        exercised.assemble_file(str(output))
                    else:
                        exercised.verify_and_store(0, data[:8])
            assert failure.value.errno == (errno.ENOSPC if "write" in operation else errno.EACCES)
            if operation in ("write", "replace"):
                assert exercised.get_bitfield() == [0, 0]
                assert not (adapter.root / "pieces" / ("f" * 64) / "0.piece").exists()
            assert builtins.open is original_open
            assert Path is original_path
        adapter.assert_finished()
        assert source.read_bytes() == data
        assert output.read_bytes() == b"pre-existing-output"
        if populated:
            assert (adapter.root / "pieces" / ("f" * 64) / "0.piece").read_bytes() == data[:8]
            assert (adapter.root / "pieces" / ("f" * 64) / "1.piece").read_bytes() == data[8:]
    records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    triggers = [row for row in records if row["event"] == "fault_triggered"]
    assert len(triggers) == 1
    assert (triggers[0]["operation"], triggers[0]["call"]) == (operation, call)
    assert sum(row["event"] == "storage_open" for row in records) == sum(
        row["event"] == "storage_closed" for row in records)
    if "write" in operation:
        partials = [bytes.fromhex(row["data_hex"]) for row in records if row["event"] == "storage_partial_write"]
        assert partials == [b"012"]
        cleaned = b"".join(bytes.fromhex(row["data_hex"]) for row in records if row["event"] == "storage_cleanup_bytes")
        assert cleaned == b"012"
