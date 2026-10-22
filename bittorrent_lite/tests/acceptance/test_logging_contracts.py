"""Direct logging contracts; malformed legacy readers get no strict-audit credit."""

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from bittorrent_lite.common import run_log
from bittorrent_lite.common.logging import get_logger


@pytest.fixture
def isolated_log(monkeypatch, tmp_path):
    # Preserve any caller's existing singleton without closing its handle.
    monkeypatch.setattr(run_log, "_file", None)
    monkeypatch.setattr(run_log, "_path", None)
    monkeypatch.setattr(run_log, '_sequence', 0)
    monkeypatch.delenv('BTL_LOG_STRICT', raising=False)
    monkeypatch.setenv(run_log.ENV_VAR, str(tmp_path / "events.jsonl"))
    monkeypatch.setenv(run_log.PROC_ENV_VAR, "owned-test-process")
    yield tmp_path / "events.jsonl"
    handle = run_log._file
    if handle is not None:
        handle.close()


def test_disabled_event_log_does_no_io(isolated_log, monkeypatch):
    monkeypatch.delenv(run_log.ENV_VAR)

    def unexpected_open(*args, **kwargs):
        raise AssertionError("disabled logging must not open a destination")

    monkeypatch.setattr(run_log, "open", unexpected_open, raising=False)
    run_log.emit("disabled", piece=1)
    assert not isolated_log.exists()


def test_enabled_event_schema_and_explicit_process_override(isolated_log, monkeypatch):
    monkeypatch.setattr(run_log, "time", SimpleNamespace(monotonic=lambda: 123.25))
    run_log.emit("piece_verified", piece=3, bytes=65536)
    run_log.emit("exit", proc="explicit-process", reason="stopped")
    # Parse every line directly; never use the permissive production reader.
    raw = isolated_log.read_bytes()
    assert raw.endswith(b"\n")
    records = [json.loads(line) for line in raw.splitlines()]
    assert records == [
        {"mono": 123.25, "proc": "owned-test-process", "event": "piece_verified", "piece": 3, "bytes": 65536},
        {"mono": 123.25, "proc": "explicit-process", "event": "exit", "reason": "stopped"},
    ]


def test_concurrent_event_writes_are_complete_and_unique(isolated_log):
    def write(producer):
        for sequence in range(25):
            run_log.emit("test-record", producer=producer, sequence=sequence,
                         payload="\u0000λ" * 20)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(8)))
    raw = isolated_log.read_bytes()
    assert raw.endswith(b"\n")
    records = [json.loads(line) for line in raw.splitlines()]
    identities = [(record["producer"], record["sequence"]) for record in records]
    assert len(identities) == 200
    assert len(set(identities)) == 200
    assert set(identities) == {(producer, sequence) for producer in range(8) for sequence in range(25)}
    assert all(record["proc"] == "owned-test-process" and record["event"] == "test-record"
               and record["payload"] == "\u0000λ" * 20 for record in records)
    for producer in range(8):
        assert [record["sequence"] for record in records if record["producer"] == producer] == list(range(25))


def test_concurrent_timestamps_follow_serialized_record_order(isolated_log, monkeypatch):
    first_at_lock = threading.Event()
    second_finished = threading.Event()
    actual_lock = threading.Lock()
    clock_lock = threading.Lock()
    clock_value = [0]

    class OrderedLock:
        def __enter__(self):
            if threading.current_thread().name == "acceptance-first-record":
                first_at_lock.set()
                assert second_finished.wait(3), "second producer did not finish"
            actual_lock.acquire()

        def __exit__(self, *args):
            actual_lock.release()

    def monotonic():
        with clock_lock:
            clock_value[0] += 1
            return float(clock_value[0])

    monkeypatch.setattr(run_log, "_lock", OrderedLock())
    monkeypatch.setattr(run_log, "time", SimpleNamespace(monotonic=monotonic))
    first = threading.Thread(target=lambda: run_log.emit("first"), name="acceptance-first-record")

    def second_record():
        try:
            run_log.emit("second")
        finally:
            second_finished.set()

    second = threading.Thread(target=second_record, name="acceptance-second-record")
    first.start()
    try:
        assert first_at_lock.wait(3)
        second.start()
        second.join(3)
        first.join(3)
        assert not first.is_alive() and not second.is_alive()
    finally:
        second_finished.set()
        first.join(3)
        if second.ident is not None:
            second.join(3)
    records = [json.loads(line) for line in isolated_log.read_text("utf-8").splitlines()]
    assert [record["event"] for record in records] == ["second", "first"]
    assert [record["mono"] for record in records] == [1.0, 2.0]


def test_changed_event_destination_closes_previous_descriptor(isolated_log, monkeypatch, tmp_path):
    run_log.emit("first")
    original_handle = run_log._file
    second = tmp_path / "second.jsonl"
    monkeypatch.setenv(run_log.ENV_VAR, str(second))
    run_log.emit("second")
    try:
        assert original_handle.closed, "changing destinations must not leak the previous descriptor"
        assert [json.loads(line)["event"] for line in isolated_log.read_text("utf-8").splitlines()] == ["first"]
        assert [json.loads(line)["event"] for line in second.read_text("utf-8").splitlines()] == ["second"]
    finally:
        # Failure diagnostics must not themselves leak a descriptor.
        original_handle.close()


def test_invalid_event_destination_is_nonfatal_and_later_valid_path_works(isolated_log, monkeypatch, tmp_path):
    invalid = tmp_path / "missing-parent" / "events.jsonl"
    monkeypatch.setenv(run_log.ENV_VAR, str(invalid))
    run_log.emit("unwritable")
    assert not invalid.exists()
    monkeypatch.setenv(run_log.ENV_VAR, str(isolated_log))
    run_log.emit("recovered")
    records = [json.loads(line) for line in isolated_log.read_text("utf-8").splitlines()]
    assert [record["event"] for record in records] == ["recovered"]


def test_unserializable_event_is_nonfatal_and_does_not_damage_following_line(isolated_log):
    run_log.emit("invalid", value=object())
    run_log.emit("valid", value=7)
    records = [json.loads(line) for line in isolated_log.read_text("utf-8").splitlines()]
    assert len(records) == 1
    assert records[0]["event"] == "valid" and records[0]["value"] == 7


def test_legacy_read_events_is_permissive_and_not_an_acceptance_verifier(tmp_path):
    """Preserve documented legacy behavior without mistaking it for validation."""
    path = tmp_path / "mixed.jsonl"
    path.write_bytes(b'{"mono":1,"event":"valid"}\nnot-json\n[]\n{"event":"missing-time"}\n{"mono":')
    assert run_log.read_events(str(path)) == [{"mono": 1, "event": "valid"}]
    assert run_log.read_events(str(tmp_path / "absent.jsonl")) == []
    # The same bytes are invalid strict evidence and must not get positive credit.
    with pytest.raises(json.JSONDecodeError):
        [json.loads(line) for line in path.read_text("utf-8").splitlines()]


def test_strict_log_sequences_actual_serialized_writes(isolated_log, monkeypatch):
    import os
    monkeypatch.setenv('BTL_LOG_STRICT', '1')
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda index: run_log.emit('observed', index=index), range(24)))
    rows = [json.loads(line) for line in isolated_log.read_text('utf-8').splitlines()]
    assert [r['log_sequence'] for r in rows] == list(range(24))
    assert {r['index'] for r in rows} == set(range(24))
    assert all(r['log_pid'] == os.getpid() and r['log_schema'] == 'btl-log-v1' for r in rows)


def test_strict_log_rejects_existing_destination_without_modification(isolated_log, monkeypatch):
    monkeypatch.setenv('BTL_LOG_STRICT', '1')
    isolated_log.write_bytes(b'existing evidence\n')
    with pytest.raises(FileExistsError):
        run_log.emit('must-not-append')
    assert isolated_log.read_bytes() == b'existing evidence\n'


@pytest.mark.parametrize('fault', ['unwritable', 'nonfinite', 'reserved', 'short-write', 'flush'])
def test_strict_log_surfaces_loss_instead_of_silent_success(isolated_log, monkeypatch, fault):
    monkeypatch.setenv('BTL_LOG_STRICT', '1')
    if fault == 'unwritable':
        monkeypatch.setenv(run_log.ENV_VAR, str(isolated_log.parent / 'missing' / 'events'))
    elif fault in ('short-write', 'flush'):
        class Handle:
            def write(self, text):
                return len(text) - 1 if fault == 'short-write' else len(text)
            def flush(self):
                raise OSError('controlled flush failure')
        monkeypatch.setattr(run_log, '_open', lambda: Handle())
    fields = {'value': float('inf')} if fault == 'nonfinite' else {'log_pid': 1} if fault == 'reserved' else {}
    with pytest.raises((OSError, ValueError)):
        run_log.emit('fault', **fields)


def test_console_logger_is_idempotent_and_formats_the_actual_message(capsys):
    name = "acceptance-isolated-console-logger"
    logger = logging.getLogger(name)
    old_handlers, old_level, old_propagate = logger.handlers[:], logger.level, logger.propagate
    logger.handlers = []
    logger.propagate = False
    try:
        assert get_logger(name) is logger
        assert get_logger(name) is logger
        assert len(logger.handlers) == 1
        logger.info("checked piece %d", 7)
        output = capsys.readouterr().out
        assert output.count("checked piece 7") == 1
        assert name in output and "INFO" in output
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers = old_handlers
        logger.setLevel(old_level)
        logger.propagate = old_propagate
