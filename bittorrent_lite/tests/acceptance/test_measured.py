"""Pure PREPARE oracles; all artificial events/results are unit fixtures.

No test here starts a process/socket or supplies real experiment credit.
"""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bittorrent_lite.acceptance_tools import measured
from bittorrent_lite.experiments.scripts.launcher import DEFAULTS


def plan_fixture(tmp_path):
    base = tmp_path / "base.json"
    base.write_text(json.dumps({"seed": 11, "peer_command": [*DEFAULTS["peer_command"],
                                                              "--resource-metrics", "--upload-workers", "0"]}), encoding="utf-8")
    return measured.make_plan(str(base), [], order_seed=2026, source_freeze="f" * 64,
                              revision="unit-fixture-revision", lane="diagnostic")


def reseal(plan):
    raw = json.dumps({k: v for k, v in plan.items() if k != "sha256"}, sort_keys=True,
                     separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()
    plan["sha256"] = hashlib.sha256(raw).hexdigest()


def result_fixture(plan, config):
    identity = f"{config['name']}-r{config['repeat']}"
    return {"status": "VERIFIED", "lane": "diagnostic", "configuration_id": identity,
            "run_id": f"unit-only-{identity}", "source_freeze": plan["source_freeze"],
            "revision": plan["revision"], "unit_fixture": True}


def test_exact_original_matrix_has_nine_configs_three_seeds_and_shared_baseline(tmp_path):
    plan = plan_fixture(tmp_path)
    configs = measured.validate_plan(plan)
    assert len(configs) == 27
    assert {c["name"] for c in configs} == {"swarm-L2", "swarm-L4", "swarm-L6", "swarm-L8",
                                            "select-random", "select-sequential", "seeders-S2", "free-rider", "failure"}
    assert plan["run_seeds"] == [11001, 11002, 11003]
    assert sum(c["name"] == "swarm-L6" for c in configs) == 3
    assert {c["repeat"] for c in configs if c["name"] == "swarm-L6"} == {1, 2, 3}
    assert all(c["synthetic"] is False for c in configs)
    assert configs == measured.make_plan(str(tmp_path / "base.json"), [], order_seed=2026,
                                         source_freeze="f" * 64, revision="unit-fixture-revision",
                                         lane="diagnostic")["configs"]


@pytest.mark.parametrize("change", ["missing", "duplicate", "order", "population", "synthetic",
                                     "fixed-window", "seed", "fake-command", "method"],
                         ids=lambda value: value)
def test_matrix_rejects_semantically_invalid_even_resealed_plan(tmp_path, change):
    plan = plan_fixture(tmp_path)
    if change == "missing":
        plan["configs"].pop()
    elif change == "duplicate":
        plan["configs"][1] = copy.deepcopy(plan["configs"][0])
    elif change == "order":
        plan["configs"][0], plan["configs"][1] = plan["configs"][1], plan["configs"][0]
    elif change == "population":
        plan["configs"][0]["L"] += 1
    elif change == "synthetic":
        for config in plan["configs"]:
            config["synthetic"] = True
    elif change == "fixed-window":
        plan["configs"][0]["window"] = 1
    elif change == "seed":
        plan["configs"][0]["seed"] += 100
    elif change == "fake-command":
        for config in plan["configs"]:
            config["peer_command"] = ["{python}", "-m", "bittorrent_lite.experiments.scripts.stand_in_peer", "--resource-metrics"]
    else:
        plan["method"]["distribution_origin"] = "tracker_start"
    reseal(plan)
    with pytest.raises(ValueError):
        measured.validate_plan(plan)


def test_matrix_missing_resource_instrumentation_is_blocked(tmp_path):
    plan = plan_fixture(tmp_path)
    for config in plan["configs"]:
        config["peer_command"].remove("--resource-metrics")
    reseal(plan)
    with pytest.raises(measured.PreparationBlocked, match="resource-metrics"):
        measured.validate_plan(plan)


@pytest.mark.parametrize("failure_stage", ["launch", "semantic-exception", "false-semantic-status"])
def test_driver_stops_before_second_run_on_first_unexpected_failure(tmp_path, failure_stage):
    plan = plan_fixture(tmp_path)
    calls = []
    def launch(config):
        calls.append(("launch", config["name"], config["repeat"]))
        if failure_stage == "launch":
            raise RuntimeError("declared unit negative control")
        return Path("unit-fixture-only")
    def verify(path, config):
        calls.append(("verify", config["name"], config["repeat"]))
        if failure_stage == "semantic-exception":
            raise ValueError("declared unit semantic negative control")
        result = result_fixture(plan, config)
        result["status"] = "failed"
        return result
    with pytest.raises((RuntimeError, ValueError)):
        measured.execute_schedule(plan, launch, verify)
    assert sum(row[0] == "launch" for row in calls) == 1
    assert len({row[1:] for row in calls}) == 1


def test_driver_and_final_inventory_reconcile_every_mock_identity(tmp_path):
    plan = plan_fixture(tmp_path)
    order = []
    def launch(config):
        order.append((config["name"], config["repeat"]))
        return Path("unit-fixture-only")
    results = measured.execute_schedule(plan, launch, lambda path, config: result_fixture(plan, config))
    assert order == [(c["name"], c["repeat"]) for c in plan["configs"]]
    assert measured.verify_result_inventory(plan, results) is True
    for malformed in ([], results[:-1], [results[0], *results[:-1]]):
        with pytest.raises(ValueError):
            measured.verify_result_inventory(plan, malformed)
    altered = copy.deepcopy(results)
    altered[-1]["revision"] = "different-revision"
    with pytest.raises(ValueError, match="mixed-revision"):
        measured.verify_result_inventory(plan, altered)


def row(event, mono, *, proc="peer-01", runtime=False, **fields):
    return {"event": event, "mono": mono, "proc": proc,
            **({"peer_id": proc, "at": mono} if runtime else {}), **fields}


def frame_row(event, mono, kind, *, proc="peer-01", request_id=1, piece=0, payload=0):
    seed = proc == "seed-01"
    return row(event, mono, proc=proc, connection_id=1, remote="peer-01" if seed else "seed-01",
               expected_remote="peer-01" if seed else "seed-01", local_endpoint=["127.0.0.1", 1001 if seed else 1002],
               remote_endpoint=["127.0.0.1", 1002 if seed else 1001], message_type=kind,
               request_id=request_id, piece=piece, payload_bytes=payload, frame_bytes=100 + payload, frame_complete=True)


def ordinary_peer_events():
    identity = {"connection_id": 1, "request_id": 1, "piece": 0, "remote": "seed-01"}
    return [
        row("listening", 1, port=1002),
        row("writer_queue", 2, connection_id=1, remote="seed-01", reason="enqueue", depth=1, capacity=64),
        frame_row("frame_sent", 3, "REQUEST"),
        frame_row("frame_received", 4, "PIECE", payload=4),
        row("piece_verification", 5, runtime=True, **identity, outcome="stored", bytes=4),
        row("piece_verified", 6, runtime=True, **identity, bytes=4),
        row("scheduler_snapshot", 7, runtime=True, reason="PieceReceived", event_queue_depth=0,
            event_queue_capacity=128, connected_peers=1, neighbors={}, pending=[],
            pipeline_counters={}, uploads={}, owned=1),
        row("resource_sample", 8, runtime=True, metrics={"rss_bytes": 1024, "thread_count": 2,
            "tcp_socket_count": 1, "cpu_user_s": 0.1, "cpu_system_s": 0.2, "handle_count": 4}),
        row("complete", 9, final_hash_ok=True),
        row("counters", 10, verified_download_bytes=4, uploaded_payload_bytes=0),
        row("exit", 11, reason="stopped"),
    ]


ORACLE = {"size": 4, "pieces": [{"index": 0, "size": 4, "sha256": hashlib.sha256(b"data").hexdigest()}],
          "piece_size": 65536, "sha256": hashlib.sha256(b"data").hexdigest()}


def test_metric_arithmetic_counts_actual_senders_unique_commits_and_complete_lifetime():
    result = measured.derive_peer_metrics(ordinary_peer_events(), "peer-01", ORACLE)
    assert {key: result[key] for key in measured.METRICS} == {
        "messages_sent": 1, "requests_sent": 1, "retries": 0, "hash_failures": 0,
        "verified_download_bytes": 4, "uploaded_payload_bytes": 0}
    assert result["writer_queue_max"] == 1 and result["event_queue_max"] == 0
    assert result["pending_total_max"] == 0 and result["lifetime_end"] == 11
    assert result["resource_maxima"]["rss_bytes"] == 1024


def test_retry_definition_and_hash_failure_are_recomputed_from_events():
    events = ordinary_peer_events()
    events.insert(3, frame_row("frame_sent", 3.1, "REQUEST", request_id=2))
    events.insert(4, row("piece_verification", 3.2, runtime=True, connection_id=1, request_id=2,
                         piece=0, remote="seed-01", outcome="hash_mismatch", bytes=4))
    result = measured.derive_peer_metrics(events, "peer-01", ORACLE)
    assert (result["messages_sent"], result["requests_sent"], result["retries"], result["hash_failures"]) == (2, 2, 1, 1)
    assert result["verified_download_bytes"] == 4


@pytest.mark.parametrize("change", ["unknown-event", "unknown-field", "unknown-counter", "duplicate-commit",
                                     "wrong-piece-bytes", "false-final-counter", "missing-counters", "missing-exit",
                                     "duplicate-request", "missing-verification", "queue-overflow", "unknown-resource-field"])
def test_metric_verifier_rejects_malformed_inconsistent_or_missing_evidence(change):
    events = ordinary_peer_events()
    if change == "unknown-event":
        events[1]["event"] = "invented_zero_counter"
    elif change == "unknown-field":
        events[1]["fabricated"] = 0
    elif change == "unknown-counter":
        events[-2]["unknown_messages"] = 0
    elif change == "duplicate-commit":
        events.insert(6, copy.deepcopy(events[5]))
    elif change == "wrong-piece-bytes":
        events[5]["bytes"] = 3
    elif change == "false-final-counter":
        events[-2]["verified_download_bytes"] = 0
    elif change == "missing-counters":
        events.pop(-2)
    elif change == "missing-exit":
        events.pop()
    elif change == "duplicate-request":
        events.insert(3, copy.deepcopy(events[2]))
    elif change == "missing-verification":
        events.pop(4)
    elif change == "queue-overflow":
        events[1]["depth"] = 65
    else:
        events[7]["metrics"]["invented_rss"] = 0
    with pytest.raises(ValueError):
        measured.derive_peer_metrics(events, "peer-01", ORACLE)


@pytest.mark.parametrize("missing", ["writer_queue", "scheduler_snapshot", "resource_sample"])
def test_missing_required_telemetry_remains_blocked(missing):
    events = [event for event in ordinary_peer_events() if event["event"] != missing]
    with pytest.raises(measured.PreparationBlocked, match="telemetry"):
        measured.derive_peer_metrics(events, "peer-01", ORACLE)


def test_killed_peer_without_independent_full_interval_observer_is_blocked():
    events = ordinary_peer_events()[:-3]
    with pytest.raises(measured.PreparationBlocked, match="separately validated observer"):
        measured.derive_peer_metrics(events, "peer-01", ORACLE, killed=True)


def test_commit_provenance_requires_matching_remote_frame_endpoints():
    streams = {"peer-01": ordinary_peer_events(), "seed-01": [frame_row("frame_sent", 3.5, "PIECE", proc="seed-01", payload=4)]}
    measured.verify_network_provenance(streams)
    for changed in ("missing-send", "wrong-endpoint", "missing-receive"):
        altered = copy.deepcopy(streams)
        if changed == "missing-send":
            altered["seed-01"] = []
        elif changed == "wrong-endpoint":
            altered["seed-01"][0]["remote_endpoint"][1] = 2002
        else:
            altered["peer-01"] = [r for r in altered["peer-01"] if r["event"] != "frame_received"]
        with pytest.raises(ValueError):
            measured.verify_network_provenance(altered)


def test_availability_uses_commits_and_actual_lifetimes_instead_of_missing_as_zero():
    streams = {"seed-01": [], "peer-01": ordinary_peer_events()}
    result = measured.availability_rows(streams, {"seed-01": "seeder", "peer-01": "downloader"},
                                        {"seed-01": (1, 8), "peer-01": (2, 11)},
                                        origin=1, finish=10, pieces=1)
    assert [(r["at_mono"], r["live_peers"], r["min_owners"]) for r in result] == [(1, 1, 1), (2, 2, 1), (6, 2, 2), (8, 1, 1)]
    with pytest.raises(ValueError, match="outside"):
        measured.availability_rows(streams, {"seed-01": "seeder", "peer-01": "downloader"},
                                   {"seed-01": (1, 8), "peer-01": (7, 11)}, origin=1, finish=10, pieces=1)


def test_live_parser_never_skips_bad_complete_lines_or_consumes_partial_tail(tmp_path):
    path = tmp_path / "peer.jsonl"
    valid = json.dumps(row("listening", 1, port=1002)).encode() + b"\n"
    path.write_bytes(valid + b'{"event":')
    child = measured.StrictChild("peer-01", "downloader", 1002, [], path)
    assert child.poll_events() == [row("listening", 1, port=1002)]
    assert child._offset == len(valid)
    assert child.poll_events() == []
    with path.open("ab") as stream:
        stream.write(b"bad}\n")
    with pytest.raises(ValueError):
        child.poll_events()
    assert child._offset == len(valid)


@pytest.mark.parametrize("layout", ["loose", "packed", "detached", "worktree"])
def test_revision_identity_reads_and_hashes_git_files_without_subprocesses(tmp_path, monkeypatch, layout):
    repo = tmp_path / "repo"
    repo.mkdir()
    git = repo / ".git"
    if layout == "worktree":
        git = tmp_path / "git-admin"
        git.mkdir()
        (repo / ".git").write_text("gitdir: ../git-admin\n", encoding="utf-8")
    else:
        git.mkdir()
    commit = "a" * 40
    if layout == "detached":
        (git / "HEAD").write_text(commit + "\n", encoding="utf-8")
    else:
        (git / "HEAD").write_text("ref: refs/heads/unit\n", encoding="utf-8")
        if layout == "packed":
            (git / "packed-refs").write_text("# unit fixture\n" + commit + " refs/heads/unit\n", encoding="utf-8")
        else:
            (git / "refs" / "heads").mkdir(parents=True)
            (git / "refs" / "heads" / "unit").write_text(commit + "\n", encoding="utf-8")
    def forbidden(*args, **kwargs):
        raise AssertionError("revision identity must never spawn a helper")
    monkeypatch.setattr(measured.subprocess, "Popen", forbidden)
    identity = measured.revision_identity(repo, commit + "-dirty", "f" * 64)
    assert identity["commit"] == commit
    assert identity["dirty_status_recomputed"] is False
    assert identity["source_freeze"] == "f" * 64
    assert identity["files"]
    for item in identity["files"]:
        content = Path(item["path"]).read_bytes()
        assert item["size"] == len(content)
        assert item["sha256"] == hashlib.sha256(content).hexdigest()
    with pytest.raises(ValueError, match="does not match"):
        measured.revision_identity(repo, "b" * 40, "f" * 64)


def _json_file(path, value):
    path.write_text(json.dumps(value, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def _events_file(path, events, pid):
    # Explicitly artificial diagnostic unit fixture, not collected telemetry.
    path.write_text("".join(json.dumps({**event, "log_schema": "btl-log-v1", "log_sequence": index,
                                      "log_pid": pid}) + "\n" for index, event in enumerate(events)), encoding="utf-8")


def artifact_fixture(tmp_path, monkeypatch):
    """Artificial three-process artifact tree for semantic negative controls.

    No OS process exists, and matching_process is stubbed explicitly. This
    fixture is diagnostic only and cannot satisfy the exact 27-run inventory.
    """
    repo = tmp_path / "unit-repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    revision = "a" * 40
    (repo / ".git" / "HEAD").write_text(revision + "\n", encoding="utf-8")
    monkeypatch.setattr(measured, "REPO_ROOT", repo)
    monkeypatch.setattr(measured, "matching_process", lambda identity: None)
    source = repo / "fixture.bin"
    source.write_bytes(b"data")
    oracle = measured.file_oracle(source)
    metadata = repo / "fixture.torrent.json"
    _json_file(metadata, {"format_version": 1, "filename": source.name, "file_size": 4,
                          "piece_size": 65536, "file_sha256": oracle["sha256"],
                          "piece_hashes": [oracle["sha256"]]})
    executable = repo / "unit-placeholder-executable"
    executable.write_bytes(b"This is an unexecuted unit fixture, not a process binary.\n")
    run = repo / "unit-artifacts"
    run.mkdir()
    for name in ("events", "logs", "registry", "peers"):
        (run / name).mkdir()
    for proc in ("seed-01", "peer-01"):
        (run / "peers" / proc).mkdir()
        (run / "peers" / proc / source.name).write_bytes(source.read_bytes())
    config = copy.deepcopy(DEFAULTS)
    config.update(name="unit-only", L=1, S=1, repeat=1, fixture=str(source), metadata=str(metadata))
    manifest = {"unit_fixture": True, "run_id": "unit-only", "status": "ok", "failure_reason": "",
                "config": config, "revision": revision, "environment": {"hostname": "unit-host", "label": "localhost"},
                "file_sha256": oracle["sha256"], "file_bytes": 4, "target": None, "trigger": None,
                "output_hash_ok": {"peer-01": True}, "run_start_mono": 0.1, "duration_s": 9.0, "processes": []}
    supervision = {"schema": 1, "lane": "diagnostic", "run_id": "unit-only", "source_freeze": "f" * 64,
                   "revision": revision, "host": "unit-host", "cleanup_errors": [], "kills": [], "cleanup": [],
                   "source_before": oracle, "source_after": oracle, "processes": {}, "raw_logs": {},
                   "started_mono": 0.0, "finished_mono": 13.0,
                   "revision_identity": measured.revision_identity(repo, revision, "f" * 64)}
    audit = []
    def fact(event, at, **fields):
        value = {"schema": "btl-measured-supervisor-v1", "event": event, "mono": at,
                 "utc": "2000-01-01T00:00:00+00:00", "run_id": "unit-only", "source_freeze": "f" * 64, **fields}
        audit.append(value)
        return value
    fact("launcher_started", 0)
    fact("source_checked_for_seeder", 0.4, proc_id="seed-01", oracle=oracle)
    probe = b'{"interval":5,"peers":[]}'
    request = json.dumps({"file_id": measured.digest_file(metadata), "peer_id": "acceptance-readiness-probe",
                          "listen_port": 65535, "event": "stopped"}).encode()
    request_fields = {"method": "POST", "path": "/announce", "host": "127.0.0.1", "port": 8000,
        "request_headers": {"Content-Type": "application/json", "Content-Length": str(len(request))},
        "request_body_hex": request.hex(), "request_body_sha256": hashlib.sha256(request).hexdigest()}
    fact("tracker_http_requested", 0.29, **request_fields)
    fact("tracker_http_response", 0.3, **request_fields, status=200, body_hex=probe.hex(),
         body_sha256=hashlib.sha256(probe).hexdigest(),
         response_headers=[["Content-Type", "application/json"], ["Content-Length", str(len(probe))]])
    for index, (proc, role, launch, listening, code) in enumerate([
            ("tracker", "tracker", 0.1, 0.2, 15), ("seed-01", "seeder", 0.5, 1.0, 0),
            ("peer-01", "downloader", 0.8, 1.0, 0)]):
        pid = 1000000 + index
        argv = [str(executable), "-m", "unit-only-not-executed", "--peer", proc]
        if role == "seeder":
            argv.extend(["--seeder", "--file", str(source)])
        identity = {"pid": pid, "creation_time": 1000.0 + index, "parent_pid": 0,
                    "executable": str(executable), "arguments": argv, "owner_run": "unit-only", "role": role,
                    "registration": "explicit", "stop_file": None}
        registry = run / "registry" / f"{pid}-{identity['creation_time']:.9f}.json"
        _json_file(registry, identity)
        environment = {"BTL_PROC_ID": proc, "BTL_RUN_ID": "unit-only", "BTL_LOG_STRICT": "1",
                       "BTL_EVENT_LOG": str(run / "events" / f"{proc}.jsonl")}
        entry = {"identity": identity, "registry_file": str(registry), "registry_sha256": measured.digest_file(registry),
                 "argv": argv, "launch_mono": launch, "environment": environment,
                 "executable_sha256": measured.digest_file(executable), "exit_code": code,
                 "observed_exit_mono": 12 + index / 10}
        registered = copy.deepcopy(entry)
        registered.update(exit_code=None, observed_exit_mono=None)
        fact("child_registered", launch + .01, proc_id=proc, **registered)
        interpreter = {"method": "independent-live-process-tree-and-environment-v1", "identity": identity,
                       "ancestry": [identity], "registry_file": str(registry), "registry_sha256": measured.digest_file(registry),
                       "executable_sha256": measured.digest_file(executable), "environment": environment}
        entry["interpreter"] = interpreter
        fact("interpreter_observed", listening + .01, proc_id=proc, observation=interpreter)
        fact("child_ready", listening + .02, proc_id=proc, ready_mono=listening)
        fact("child_exit_observed", entry["observed_exit_mono"], proc_id=proc, exit_code=code)
        supervision["processes"][proc] = entry
        manifest["processes"].append({"proc_id": proc, "role": role, "command": argv,
            "launch_mono": launch, "ready_mono": listening, "exit_code": code, "killed_by_harness": False})
        for suffix in ("out", "err"):
            path = run / "logs" / f"{proc}.{suffix}"
            path.write_bytes(b"")
            supervision["raw_logs"][f"logs/{proc}.{suffix}"] = {"size": 0, "sha256": measured.digest_file(path)}
        if role == "tracker":
            events = [row("tracker_ready", listening, proc=proc, port=8000)]
        elif role == "downloader":
            events = ordinary_peer_events()
        else:
            template = ordinary_peer_events()
            events = [row("listening", 1, proc=proc, port=1001),
                      row("scheduler_snapshot", 1.1, proc=proc, runtime=True, reason="tick", event_queue_depth=0,
                          event_queue_capacity=128, connected_peers=0, neighbors={}, pending=[],
                          pipeline_counters={}, uploads={}, owned=1),
                      row("complete", 1.2, proc=proc, final_hash_ok=True),
                      row("status", 1.2, proc=proc, runtime=True, state="SEEDING", owned=1, total=1,
                          connected_peers=0, pending_requests=0, control_queue_depth=0, event_queue_depth=0,
                          verified_download_bytes=0, uploaded_payload_bytes=0, completion_seconds=.7,
                          storage_error=None, recovery_error=None),
                      row("writer_queue", 2, proc=proc, connection_id=1, remote="peer-01", reason="enqueue", depth=1, capacity=64),
                      frame_row("frame_sent", 3.5, "PIECE", proc=proc, payload=4),
                      row("piece_uploaded", 3.6, proc=proc, connection_id=1, request_id=1, piece=0, bytes=4, to="peer-01")]
            for sample in template[6:8]:
                sample.update(proc=proc, peer_id=proc)
                events.append(sample)
            events += [row("counters", 10, proc=proc, verified_download_bytes=0, uploaded_payload_bytes=4),
                       row("exit", 11, proc=proc, reason="stopped")]
        _events_file(run / "events" / f"{proc}.jsonl", events, pid)
    cleanup = fact("tracker_termination_requested", 11.9, proc_id="tracker",
                   identity=supervision["processes"]["tracker"]["identity"], mechanism="psutil-TerminateProcess-SIGTERM")
    supervision["cleanup"] = [cleanup]
    fact("launcher_finished", 13)
    state = {"run": run, "config": config, "revision": revision, "manifest": manifest,
             "supervision": supervision, "audit": audit}
    save_artifact_fixture(state)
    return state


def save_artifact_fixture(state):
    run = state["run"]
    audit = sorted(state["audit"], key=lambda item: item["mono"])
    (run / "supervision.jsonl").write_text("".join(json.dumps(value) + "\n" for value in audit), encoding="utf-8")
    state["supervision"]["audit_sha256"] = measured.digest_file(run / "supervision.jsonl")
    _json_file(run / "manifest.json", state["manifest"])
    _json_file(run / "supervision.json", state["supervision"])


def verify_artifact_fixture(state):
    return measured.verify_run(state["run"], state["config"], source_freeze="f" * 64,
                               revision=state["revision"], lane="diagnostic")


def test_artificial_semantic_fixture_exercises_oracles_and_separate_timing_origins(tmp_path, monkeypatch):
    state = artifact_fixture(tmp_path, monkeypatch)
    result = verify_artifact_fixture(state)
    assert result["status"] == "VERIFIED" and result["lane"] == "diagnostic"
    assert result["expected_complete"] == ["peer-01"]
    assert result["distribution_origin_mono"] == .5
    assert result["distribution_s"] == 8.5
    assert result["peer_completion_s"] == {"peer-01": 8.2}
    assert result["launcher_raw_tracker_origin_duration_s"] == 9.0
    assert result["supervisor_duration_with_cleanup_s"] == 13.0
    assert result["metrics"]["seed-01"]["uploaded_payload_bytes"] == 4
    assert result["useful_aggregate_throughput_Bps"] == 4 / 8.5


def test_initial_seeder_source_ready_event_has_no_download_completion_or_useful_byte_credit(tmp_path, monkeypatch):
    """065's real CLI event shape, reproduced here only as an artificial oracle fixture."""
    state = artifact_fixture(tmp_path, monkeypatch)
    result = verify_artifact_fixture(state)
    assert result["expected_complete"] == ["peer-01"]
    assert result["peer_completion_s"] == {"peer-01": 8.2}
    assert result["distribution_s"] == 8.5
    assert result["useful_aggregate_throughput_Bps"] == 4 / 8.5
    assert {key: result["metrics"]["seed-01"][key] for key in measured.METRICS} == {
        "messages_sent": 1, "requests_sent": 0, "retries": 0, "hash_failures": 0,
        "verified_download_bytes": 0, "uploaded_payload_bytes": 4}
    # Initial seed ownership exists at listener readiness, without a new commit.
    initial = [item for item in result["availability"] if item["at_mono"] == 1][-1]
    assert (initial["live_peers"], initial["min_owners"], initial["max_owners"]) == (2, 1, 1)
    assert result["availability"][-1]["min_owners"] == 2


@pytest.mark.parametrize("change,message", [
    ("duplicate-ready", "duplicate or false complete"),
    ("false-ready-hash", "duplicate or false complete"),
    ("nonboolean-ready-hash", "duplicate or false complete"),
    ("missing-ready", "exactly one verified source-ready"),
    ("invented-download-counter", "final verified_download_bytes disagrees"),
    ("invented-download-commit", "invented download/request/commit credit"),
    ("invented-download-request", "invented download/request/commit credit"),
    ("partial-initial-ownership", "full pre-completion ownership"),
    ("missing-initial-ownership", "full pre-completion ownership"),
    ("invented-status-download-credit", "status contradicts"),
    ("false-status-ownership", "status contradicts"),
    ("late-source-validation", "checked before launch"),
])
def test_initial_seeder_rejects_false_readiness_ownership_and_download_credit(tmp_path, monkeypatch, change, message):
    state = artifact_fixture(tmp_path, monkeypatch)
    path = state["run"] / "events" / "seed-01.jsonl"
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    complete = next(item for item in events if item["event"] == "complete")
    counter = next(item for item in events if item["event"] == "counters")
    status = next(item for item in events if item["event"] == "status")
    snapshot = next(item for item in events if item["event"] == "scheduler_snapshot")
    if change == "duplicate-ready":
        events.append({**complete, "mono": 1.25})
    elif change in {"false-ready-hash", "nonboolean-ready-hash"}:
        complete["final_hash_ok"] = False if change == "false-ready-hash" else 1
    elif change == "missing-ready":
        events.remove(complete)
    elif change == "invented-download-counter":
        counter["verified_download_bytes"] = 4
    elif change == "invented-download-commit":
        identity = {"connection_id": 1, "request_id": 1, "piece": 0, "remote": "peer-01"}
        events.extend([row("piece_verification", 1.12, proc="seed-01", runtime=True, **identity, outcome="stored", bytes=4),
                       row("piece_verified", 1.15, proc="seed-01", runtime=True, **identity, bytes=4)])
        counter["verified_download_bytes"] = 4
    elif change == "invented-download-request":
        events.append(frame_row("frame_sent", 1.12, "REQUEST", proc="seed-01"))
    elif change == "partial-initial-ownership":
        snapshot["owned"] = 0
    elif change == "missing-initial-ownership":
        events.remove(snapshot)
    elif change == "invented-status-download-credit":
        status["verified_download_bytes"] = 4
    elif change == "false-status-ownership":
        status["owned"] = 0
    else:
        next(item for item in state["audit"] if item["event"] == "source_checked_for_seeder")["mono"] = 1.1
    _events_file(path, sorted(events, key=lambda item: item["mono"]),
                 state["supervision"]["processes"]["seed-01"]["identity"]["pid"])
    save_artifact_fixture(state)
    with pytest.raises(ValueError, match=message):
        verify_artifact_fixture(state)


def test_initial_seeder_claimed_ready_output_is_independently_byte_verified(tmp_path, monkeypatch):
    state = artifact_fixture(tmp_path, monkeypatch)
    (state["run"] / "peers" / "seed-01" / "fixture.bin").write_bytes(b"dAta")
    with pytest.raises(ValueError):
        verify_artifact_fixture(state)


@pytest.mark.parametrize("change", ["failed-manifest", "false-hash", "source-hash", "output-byte", "missing-stream",
    "empty-stream", "truncated-stream", "sequence-gap", "wrong-pid", "mixed-revision", "duplicate-process",
    "missing-interpreter", "false-registered-pid", "unexpected-exit", "raw-log-change", "source-changed", "synthetic"])
def test_semantic_verifier_rejects_false_success_and_inconsistent_artifacts(tmp_path, monkeypatch, change):
    state = artifact_fixture(tmp_path, monkeypatch)
    run, manifest, supervision = state["run"], state["manifest"], state["supervision"]
    peer_stream = run / "events" / "peer-01.jsonl"
    if change == "failed-manifest":
        manifest["status"] = "failed"
    elif change == "false-hash":
        manifest["output_hash_ok"]["peer-01"] = False
    elif change == "source-hash":
        manifest["file_sha256"] = "0" * 64
    elif change == "output-byte":
        (run / "peers" / "peer-01" / "fixture.bin").write_bytes(b"dAta")
    elif change == "missing-stream":
        peer_stream.rename(peer_stream.with_suffix(".missing"))
    elif change == "empty-stream":
        peer_stream.write_bytes(b"")
    elif change == "truncated-stream":
        peer_stream.write_bytes(peer_stream.read_bytes()[:-1])
    elif change in {"sequence-gap", "wrong-pid"}:
        rows = [json.loads(line) for line in peer_stream.read_text(encoding="utf-8").splitlines()]
        rows[3]["log_sequence" if change == "sequence-gap" else "log_pid"] += 1
        peer_stream.write_text("".join(json.dumps(value) + "\n" for value in rows), encoding="utf-8")
    elif change == "mixed-revision":
        supervision["revision"] = "b" * 40
    elif change == "duplicate-process":
        manifest["processes"].append(copy.deepcopy(manifest["processes"][-1]))
    elif change == "missing-interpreter":
        supervision["processes"]["peer-01"].pop("interpreter")
    elif change == "false-registered-pid":
        supervision["processes"]["peer-01"]["identity"]["pid"] += 999
    elif change == "unexpected-exit":
        manifest["processes"][-1]["exit_code"] = 1
    elif change == "raw-log-change":
        (run / "logs" / "peer-01.out").write_bytes(b"unrecorded append")
    elif change == "source-changed":
        Path(state["config"]["fixture"]).write_bytes(b"dAta")
    else:
        state["config"]["synthetic"] = True
    save_artifact_fixture(state)
    with pytest.raises((ValueError, FileNotFoundError)):
        verify_artifact_fixture(state)


def test_full_matrix_blocks_before_first_launch_without_killed_observer(tmp_path, monkeypatch):
    plan = plan_fixture(tmp_path)
    source = tmp_path / "diagnostic.bin"
    source.write_bytes(b"data")
    metadata = tmp_path / "diagnostic.torrent.json"
    oracle = measured.file_oracle(source)
    _json_file(metadata, {"format_version": 1, "filename": source.name, "file_size": 4,
        "piece_size": 65536, "file_sha256": oracle["sha256"], "piece_hashes": [oracle["sha256"]]})
    _json_file(source.with_suffix(".bin.oracle.json"), {"lane": "diagnostic", "source_freeze": "f" * 64,
        "provider": "unit fixture only", "token_sha256": "a" * 64, "oracle": oracle})
    for config in plan["configs"]:
        config.update(fixture=str(source), metadata=str(metadata))
    reseal(plan)
    monkeypatch.setattr(measured, "snapshot", lambda repo: {"sha256": "f" * 64})
    monkeypatch.setattr(measured, "compare_snapshots", lambda expected, actual: None)
    def forbidden(*args, **kwargs):
        raise AssertionError("blocked preflight must not construct or launch a Run")
    monkeypatch.setattr(measured, "GuardedRun", forbidden)
    output = tmp_path / "blocked-unit-attempt"
    with pytest.raises(measured.PreparationBlocked, match="independent observer"):
        measured.supervise(plan, output, {"sha256": "f" * 64})
    result = json.loads((output / "campaign-outcome.json").read_text(encoding="utf-8"))
    assert result["status"] == "BLOCKED" and result["acceptance_credit"] is False
    assert result["verified_configurations"] == [] and len(result["remaining"]) == 27
    assert not (output / "runs").exists()


def test_guarded_execute_uses_original_stage_apis_without_legacy_execute_or_git_spawn(tmp_path, monkeypatch):
    state = artifact_fixture(tmp_path, monkeypatch)
    config = copy.deepcopy(state["config"])
    config["launch_gap_s"] = 0
    events = []
    run = measured.GuardedRun(config, tmp_path / "mock-runs", source_freeze="f" * 64,
                              revision=state["revision"], registry=state["run"] / "registry", lane="diagnostic")
    child = SimpleNamespace(proc_id="tracker", role="tracker", port=8000, command=["unit-only"],
                            launch_mono=None, ready_mono=None, exit_code=None, killed_by_harness=False)
    def planned():
        events.append("plan")
        run.children = [child]
    def start(value):
        assert value is child
        events.append("start")
        child.launch_mono = measured.time.monotonic()
    def ready(value, name):
        assert value is child and name == "tracker_ready"
        events.append("ready")
        child.ready_mono = measured.time.monotonic()
    def stop():
        events.append("stop")
        child.exit_code = 1
        run.supervision["cleanup_errors"] = []
    def forbidden(*args, **kwargs):
        raise AssertionError("legacy execute/git helpers must never run")
    monkeypatch.setattr(measured.Run, "execute", forbidden)
    monkeypatch.setattr(measured.subprocess, "Popen", forbidden)
    monkeypatch.setattr(run, "_plan_children", planned)
    monkeypatch.setattr(run, "_preflight", lambda: events.append("preflight"))
    monkeypatch.setattr(run, "_start", start)
    monkeypatch.setattr(run, "_wait_ready", ready)
    monkeypatch.setattr(run, "_monitor", lambda: (events.append("monitor") or "ok", ""))
    monkeypatch.setattr(run, "_stop_all", stop)
    monkeypatch.setattr(run, "_check_outputs", lambda: {"peer-01": False})
    result = run.execute()
    assert events == ["plan", "preflight", "start", "ready", "monitor", "stop"]
    assert result["revision"] == state["revision"]
    assert result["output_hash_ok"] == {"peer-01": False}
    assert (run.dir / "manifest.json").is_file() and (run.dir / "supervision.json").is_file()
    # This proves stage dispatch only. False output is retained for strict
    # semantic rejection; it is never converted into successful measurement.


@pytest.mark.parametrize("change", ["sequence", "pid"])
def test_live_strict_parser_checks_sequence_and_independently_supplied_pid(tmp_path, change):
    path = tmp_path / "strict-peer.jsonl"
    first = row("listening", 1, port=1002, log_schema="btl-log-v1", log_sequence=0, log_pid=123)
    path.write_text(json.dumps(first) + "\n", encoding="utf-8")
    child = measured.StrictChild("peer-01", "downloader", 1002, [], path)
    child.require_sequence, child.interpreter_pid = True, 123
    assert child.poll_events() == [first]
    previous_offset = child._offset
    second = row("counters", 2, verified_download_bytes=0, uploaded_payload_bytes=0,
                 log_schema="btl-log-v1", log_sequence=1, log_pid=123)
    second["log_sequence" if change == "sequence" else "log_pid"] += 1
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(second) + "\n")
    with pytest.raises(ValueError, match="interpreter PID"):
        child.poll_events()
    assert child._offset == previous_offset and child.events == [first]


def test_acceptance_cannot_bypass_unvalidated_os_source_isolation_by_calling_api_directly(tmp_path):
    with pytest.raises(measured.PreparationBlocked, match="source-denial"):
        measured.GuardedRun({}, tmp_path, source_freeze="f" * 64, revision="a" * 40,
                            registry=tmp_path, lane="acceptance")
    with pytest.raises(measured.PreparationBlocked, match="source-denial"):
        measured.verify_run(tmp_path, {}, source_freeze="f" * 64, revision="a" * 40)


def test_tracker_readiness_probe_posts_exact_stopped_json_and_retains_bytes(tmp_path, monkeypatch):
    """Regression for diagnostic049: GET/query could never satisfy POST API."""
    state = artifact_fixture(tmp_path, monkeypatch)
    run = measured.GuardedRun(state["config"], tmp_path / "unused-runs", source_freeze="f" * 64,
                              revision=state["revision"], registry=state["run"] / "registry", lane="diagnostic")
    child = SimpleNamespace(proc_id="tracker", role="tracker", port=8000, ready_mono=None)
    calls, audit = [], []
    response_bytes = b'{"interval":5,"peers":[]}'
    class Response:
        status = 200
        def read(self, cap):
            assert cap == 65537
            return response_bytes
        def getheaders(self):
            return [("Content-Type", "application/json"), ("Content-Length", str(len(response_bytes)))]
    class Connection:
        def __init__(self, host, port, timeout):
            calls.append(("connect", host, port, timeout))
        def request(self, method, path, *, body, headers):
            calls.append(("request", method, path, body, copy.deepcopy(headers)))
        def getresponse(self):
            return Response()
        def close(self):
            calls.append(("close",))
    def ready(self, value, event):
        assert value is child and event == "tracker_ready"
        value.ready_mono = 1
    def record(event, **fields):
        value = {"event": event, **fields}
        audit.append(value)
        return value
    monkeypatch.setattr(measured.Run, "_wait_ready", ready)
    monkeypatch.setattr(run, "_observe_interpreter", lambda value: calls.append(("observe", value.proc_id)))
    monkeypatch.setattr(run, "_audit", record)
    monkeypatch.setattr(measured.http.client, "HTTPConnection", Connection)
    run._wait_ready(child, "tracker_ready")
    assert calls[0] == ("observe", "tracker") and calls[1] == ("connect", "127.0.0.1", 8000, 2)
    sent = calls[2]
    assert sent[:3] == ("request", "POST", "/announce")
    assert json.loads(sent[3]) == {"file_id": measured.digest_file(Path(state["config"]["metadata"])),
        "peer_id": "acceptance-readiness-probe", "listen_port": 65535, "event": "stopped"}
    assert sent[4] == {"Content-Type": "application/json", "Content-Length": str(len(sent[3]))}
    assert calls[-1] == ("close",)
    assert [item["event"] for item in audit] == ["tracker_http_requested", "tracker_http_response", "child_ready"]
    assert bytes.fromhex(audit[0]["request_body_hex"]) == sent[3]
    assert audit[0]["request_body_sha256"] == hashlib.sha256(sent[3]).hexdigest()
    assert bytes.fromhex(audit[1]["body_hex"]) == response_bytes
    assert audit[1]["body_sha256"] == hashlib.sha256(response_bytes).hexdigest()


@pytest.mark.parametrize("change", ["GET", "query-path", "wrong-port-field", "started-membership",
                                     "request-digest", "interval", "nonempty-membership", "response-length"])
def test_tracker_readiness_verifier_rejects_wrong_http_contract_even_with_valid_json(tmp_path, monkeypatch, change):
    state = artifact_fixture(tmp_path, monkeypatch)
    probe = copy.deepcopy(next(item for item in state["audit"] if item["event"] == "tracker_http_response"))
    if change == "GET":
        probe["method"] = "GET"
    elif change == "query-path":
        probe["path"] = "/announce?event=stopped"
    elif change in {"wrong-port-field", "started-membership"}:
        body = json.loads(bytes.fromhex(probe["request_body_hex"]))
        if change == "wrong-port-field":
            body["port"] = body.pop("listen_port")
        else:
            body["event"] = "started"
        raw = json.dumps(body).encode()
        probe.update(request_body_hex=raw.hex(), request_body_sha256=hashlib.sha256(raw).hexdigest())
        probe["request_headers"]["Content-Length"] = str(len(raw))
    elif change == "request-digest":
        probe["request_body_sha256"] = "0" * 64
    elif change in {"interval", "nonempty-membership"}:
        body = {"interval": 30 if change == "interval" else 5,
                "peers": [{}] if change == "nonempty-membership" else []}
        raw = json.dumps(body).encode()
        probe.update(body_hex=raw.hex(), body_sha256=hashlib.sha256(raw).hexdigest())
        probe["response_headers"][1][1] = str(len(raw))
    else:
        probe["response_headers"][1][1] = "0"
    with pytest.raises(ValueError, match="tracker readiness"):
        measured._verify_tracker_probe(probe, measured.digest_file(Path(state["config"]["metadata"])), 8000)


@pytest.mark.parametrize("mechanism,code", [
    ("psutil-TerminateProcess-SIGTERM", 1),
    ("TerminateProcess", 15),
    ("TerminateProcess", 1),
], ids=["psutil-cannot-claim-popen-exit1", "unspecified-mechanism-exit15", "unspecified-mechanism-exit1"])
def test_tracker_psutil_termination_requires_exact_mechanism_and_exit(tmp_path, monkeypatch, mechanism, code):
    """049 recorded psutil Windows termination exit 15, not Popen's exit 1."""
    state = artifact_fixture(tmp_path, monkeypatch)
    assert verify_artifact_fixture(state)["status"] == "VERIFIED"
    state["manifest"]["processes"][0]["exit_code"] = code
    state["supervision"]["processes"]["tracker"]["exit_code"] = code
    state["supervision"]["cleanup"][0]["mechanism"] = mechanism
    for item in state["audit"]:
        if item["event"] == "child_exit_observed" and item["proc_id"] == "tracker":
            item["exit_code"] = code
        if item["event"] == "tracker_termination_requested":
            item["mechanism"] = mechanism
    save_artifact_fixture(state)
    with pytest.raises(ValueError, match="tracker exit differs from declared termination mechanism"):
        verify_artifact_fixture(state)
