"""Real storage and scheduler lifecycle with a simulated backend, not TCP."""
from dataclasses import asdict
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from bittorrent_lite.peer.runtime import PeerRuntime, RuntimeConfig, Candidate, Session
from bittorrent_lite.peer.peer_main import main, build_parser, configuration
from bittorrent_lite.protocol import messages as m
from examples.scheduler_dependencies import ManualClock
from tests.test_scheduler_integration import disk_store


class Backend:
    def __init__(self):
        self.connections = []
        self.stops = 0
        self.completions = 0
        self.joined = []
        self.runtime = None

    def start(self, runtime):
        self.runtime = runtime

    def connect(self, candidate):
        self.connections.append(candidate)
        return True

    def completed(self):
        self.completions += 1

    def stop(self):
        self.stops += 1

    def join(self, timeout):
        self.joined.append(timeout)
        return True


def runtime(tmp_path, *, name="a", config=None, seed=False, data=b"abcdefghij"):
    store, pieces = disk_store(tmp_path, data=data)
    if seed:
        for i, piece in enumerate(pieces):
            store.verify_and_store(i, piece)
    backend, clock, log = Backend(), ManualClock(), []
    r = PeerRuntime(name, store, tmp_path / "result.bin", backend,
                    config=config, clock=clock, emit=log.append)
    r.start()
    return r, backend, clock, log


def session(cid, peer, bits, queue, closed):
    def withdraw(message):
        for i, queued in enumerate(queue):
            if queued is message:
                queue.pop(i)
                return True
        return False
    return Session(cid, peer, tuple(bits), queue.append, withdraw, closed.append)


@pytest.mark.parametrize("strategy", ["sequential", "random", "rarest-first"])
@pytest.mark.parametrize("window", [1, 4])
@pytest.mark.parametrize("free_rider", [False, True])
def test_runtime_transfer_finalizes_once_keeps_seeding_and_counts_exact_bytes(
        tmp_path, strategy, window, free_rider):
    seed, sb, _, _ = runtime(tmp_path / "seed", name="z", seed=True)
    target, tb, clock, records = runtime(
        tmp_path / "target", config=RuntimeConfig(strategy=strategy, window=window,
                                                seed=17, free_rider=free_rider))
    to_target, to_seed, closes = [], [], []
    seed.publish_session(session(1, "a", target.advertised_bitfield, to_target, closes))
    target.publish_session(session(1, "z", seed.advertised_bitfield, to_seed, closes))
    try:
        for _ in range(50):
            seed.step()
            target.step()
            for sender, receiver, queue in [(target, seed, to_seed), (seed, target, to_target)]:
                batch, queue[:] = list(queue), []
                for message in batch:
                    # Deliberately deliver response before its send acknowledgement.
                    receiver.bridge.received(1, message)
                    sender.bridge.sent(1, message)
            if target.status()["state"] == "SEEDING":
                break
            clock.advance(.1)
        target.step()
        seed.step()
        assert target.output_path.read_bytes() == b"abcdefghij"
        assert target.status()["verified_download_bytes"] == 10
        assert seed.status()["uploaded_payload_bytes"] == 10
        assert target.status()["completion_seconds"] is not None
        assert tb.completions == 1
        assert sum(r["event"] == "COMPLETE" for r in records) == 1
        target.step()
        assert tb.completions == 1
        assert not target.coordinator.uploads.snapshot()["service"]["closed"]
        if free_rider:
            assert not target.coordinator.uploads.snapshot()["policy"]["upload_enabled"]
            assert target.status()["uploaded_payload_bytes"] == 0
    finally:
        seed.shutdown()
        target.shutdown()
    assert sb.stops == tb.stops == 1
    assert seed.shutdown() == target.shutdown() == ()


def test_discovery_filters_self_lower_ids_and_retries_without_network_events(tmp_path):
    r, backend, clock, records = runtime(tmp_path, name="m")
    try:
        r.publish_candidates([Candidate(p, "127.0.0.1", 9001) for p in ("a", "m", "z")])
        assert r.step()["state"] == "STALLED"
        assert [p.peer_id for p in backend.connections] == ["z"]
        r.publish_tracker_error("tracker down")
        r.step()
        assert len(backend.connections) == 1
        clock.advance(5)
        r.step()
        assert len(backend.connections) == 2
        assert any(x["event"] == "TRACKER_ERROR" for x in records)
    finally:
        r.shutdown()


def test_duplicate_sessions_closed_and_initial_bitfield_copied(tmp_path):
    r, _, _, _ = runtime(tmp_path)
    queues, closed = [], []
    bits = [1, 1, 1]
    try:
        r.publish_session(Session(1, "z", bits, queues.append, lambda x: False, closed.append))
        bits[0] = 0
        r.step()
        assert r.coordinator.snapshot()["availability"] == [1, 1, 1]
        r.publish_session(session(2, "z", [1, 1, 1], queues, closed))
        r.step()
        assert len(closed) == 1
        assert len([n for n in r.coordinator.snapshot()["neighbors"].values() if n["active"]]) == 1
    finally:
        r.shutdown()


def test_timer_retry_and_shutdown_ignore_late_events(tmp_path):
    r, _, clock, _ = runtime(tmp_path)
    queue, closed = [], []
    r.publish_session(session(1, "z", [1, 1, 1], queue, closed))
    r.step()
    r.bridge.received(1, m.Unchoke())
    r.step()
    first = [x.request_id for x in queue if isinstance(x, m.Request)]
    clock.advance(5)
    r.step()
    assert not any(isinstance(x, m.Request) for x in queue)
    clock.advance(1)
    r.step()
    assert min(x.request_id for x in queue if isinstance(x, m.Request)) > max(first)
    r.shutdown()
    assert closed == ["shutdown"]
    assert not r.coordinator.snapshot()["pending"]
    r.bridge.received(1, m.Piece(1, 0, b"abcd"))
    assert r.step()["verified_download_bytes"] == 0
    assert not r.bridge.events.qsize()


def test_assembly_failure_is_local_and_requires_explicit_resume(tmp_path, monkeypatch):
    r, backend, _, log = runtime(tmp_path, seed=True)
    original = r.store.assemble_file
    calls = []
    def fail(path):
        calls.append(path)
        return False
    monkeypatch.setattr(r.store, "assemble_file", fail)
    try:
        assert r.step()["state"] == "ERROR"
        r.step()
        assert len(calls) == 1
        assert backend.completions == 0
        assert not any(x["event"] == "COMPLETE" for x in log)
        monkeypatch.setattr(r.store, "assemble_file", original)
        r.coordinator.resume_after_storage_error()
        assert r.step()["state"] == "SEEDING"
    finally:
        r.shutdown()


def test_bounded_control_queue_and_shutdown_of_unadmitted_sessions(tmp_path):
    r, _, _, _ = runtime(tmp_path)
    closed = []
    for i in range(32):
        assert r.publish_session(session(i + 1, str(i), [0, 0, 0], [], closed))
    assert not r.publish_session(session(33, "33", [0, 0, 0], [], closed))
    assert len(closed) == 1
    r.shutdown()
    assert len(closed) == 33
    assert not r.publish_session(session(34, "34", [0, 0, 0], [], closed))
    assert len(closed) == 34


def test_shutdown_attempts_all_closers_and_reports_worker_deadline(tmp_path):
    r, backend, _, _ = runtime(tmp_path, config=RuntimeConfig(shutdown_timeout=.05))
    closed = []
    def fail(reason):
        raise OSError("close failure")
    r.publish_session(Session(1, "x", (0, 0, 0), lambda x: None, lambda x: False, fail))
    r.publish_session(session(2, "y", [0, 0, 0], [], closed))
    r.step()
    backend.join = lambda timeout: False
    errors = r.shutdown()
    assert closed == ["shutdown"]
    assert any("close failure" in error for error in errors)
    assert any("deadline" in error for error in errors)
    assert r.coordinator.snapshot()["stopped"]


def test_worker_publications_and_owner_thread_enforcement(tmp_path):
    r, _, _, _ = runtime(tmp_path)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert pool.submit(r.publish_candidates, [Candidate("z", "127.0.0.1", 9)]).result()
            with pytest.raises(RuntimeError):
                pool.submit(r.step).result()
            pool.submit(r.request_stop).result()
        assert r.step()["state"] == "STALLED"
    finally:
        r.shutdown()


def test_run_cleans_backend_after_start_failure(tmp_path):
    store, _ = disk_store(tmp_path)
    backend = Backend()
    def fail(runtime):
        raise OSError("startup failed")
    backend.start = fail
    r = PeerRuntime("a", store, tmp_path / "result", backend)
    with pytest.raises(OSError):
        r.run()
    assert backend.stops == 1
    assert r.status()["state"] == "STOPPED"


@pytest.mark.parametrize("values", [
    {"window": 5}, {"seed": True}, {"free_rider": 1}, {"strategy": "invalid"},
    {"upload_workers": 1}, {"tick_interval": .2}, {"tick_interval": 0},
    {"shutdown_timeout": float("nan")}, {"event_batch": True},
])
def test_runtime_config_rejects_invalid_values(values):
    with pytest.raises(ValueError):
        RuntimeConfig(**values)


def test_cli_checks_configuration_without_claiming_network_support(tmp_path, capsys):
    store, _ = disk_store(tmp_path)
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps(asdict(store.metadata)), encoding="utf8")
    argv = ["--peer-id", "a", "--port", "9001", "--metadata", str(metadata),
            "--window", "1", "--strategy", "random", "--seed", "42", "--free-rider"]
    assert main(argv + ["--check-config"]) == 0
    config = json.loads(capsys.readouterr().out)["config"]
    assert config["free_rider"] and config["window"] == 1 and config["seed"] == 42
    assert main(argv) == 2
    assert "backend" in capsys.readouterr().err


def test_legacy_choking_import_exposes_only_current_policy():
    from bittorrent_lite.piece_manager import choking
    from bittorrent_lite.scheduler.upload_policy import ProjectUploadPolicy
    assert choking.ProjectUploadPolicy is ProjectUploadPolicy
    assert not hasattr(choking, "ChokingManager")


def test_initial_bitfield_handoff_reconciles_only_newly_owned_pieces(tmp_path):
    r, _, _, _ = runtime(tmp_path, seed=True)
    queue, closed = [], []
    try:
        ready = session(1, "z", [0, 0, 0], queue, closed)
        r.publish_session(Session(ready.connection_id, ready.peer_id, ready.bitfield,
                                  ready.send, ready.withdraw, ready.close, (1, 0, 0)))
        r.step()
        assert [x.piece_index for x in queue if isinstance(x, m.Have)] == [1, 2]
    finally:
        r.shutdown()


def test_run_honors_stop_and_always_shuts_down(tmp_path):
    store, _ = disk_store(tmp_path)
    backend = Backend()
    records = []
    def emit(record):
        records.append(record)
        if record["event"] == "STATUS":
            backend.runtime.request_stop()
    r = PeerRuntime("a", store, tmp_path / "result", backend, emit=emit)
    r.run()
    assert r.status()["state"] == "STOPPED"
    assert backend.stops == 1
    assert records[-1]["event"] == "STOPPED"


def test_blocked_upload_shutdown_reports_bound_and_can_be_reaped(tmp_path, monkeypatch):
    from bittorrent_lite.scheduler.uploads import FileStoreUploadSource
    entered, release = threading.Event(), threading.Event()
    original = FileStoreUploadSource.__call__
    def blocked(source, index):
        entered.set()
        assert release.wait(3)
        return original(source, index)
    monkeypatch.setattr(FileStoreUploadSource, "__call__", blocked)
    r, _, _, _ = runtime(tmp_path, seed=True,
                         config=RuntimeConfig(upload_workers=2, shutdown_timeout=.02))
    queue, closed = [], []
    try:
        r.publish_session(session(1, "z", [0, 0, 0], queue, closed))
        r.step()
        r.bridge.received(1, m.Interested())
        r.step()
        allow = next(x for x in queue if isinstance(x, m.Unchoke))
        r.bridge.sent(1, allow)
        r.step()
        r.bridge.received(1, m.Request(1, 0))
        r.step()
        assert entered.wait(1)
        errors = r.shutdown()
        assert any("upload reads still running" in x for x in errors)
        assert r.status()["uploaded_payload_bytes"] == 0
    finally:
        release.set()
        r.shutdown()
        r.coordinator.uploads.service.shutdown(wait=True)
    assert r.coordinator.uploads.service.snapshot().active_jobs == 0


def test_cli_injected_backend_runs_and_cleans_up(tmp_path, capsys):
    store, _ = disk_store(tmp_path)
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps(asdict(store.metadata)), encoding="utf8")
    backend = Backend()
    backend.start = lambda r: r.request_stop()
    code = main(["--peer-id", "a", "--port", "9001", "--metadata", str(metadata),
                 "--output-dir", str(tmp_path / "outputs")],
                backend_factory=lambda args, metadata, file_id: backend)
    assert code == 0 and backend.stops == 1
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["event"] == "STOPPED"


@pytest.mark.parametrize("flag,value", [("--peer-id", "../escape"), ("--port", "0")])
def test_cli_rejects_invalid_runtime_identity(flag, value):
    argv = ["--peer-id", "a", "--port", "9001", "--metadata", "unused.json"]
    argv[argv.index(flag) + 1] = value
    with pytest.raises(ValueError):
        configuration(build_parser().parse_args(argv))


@pytest.mark.parametrize("filename", ["../escape.bin", "C:\\escape.bin", "file:stream", ".."])
def test_cli_rejects_metadata_output_path_escape(tmp_path, filename, capsys):
    store, _ = disk_store(tmp_path)
    values = asdict(store.metadata)
    values["filename"] = filename
    path = tmp_path / "metadata.json"
    path.write_text(json.dumps(values), encoding="utf8")
    assert main(["--peer-id", "a", "--port", "9001", "--metadata", str(path),
                 "--check-config"]) == 2
    assert "plain filename" in capsys.readouterr().err
