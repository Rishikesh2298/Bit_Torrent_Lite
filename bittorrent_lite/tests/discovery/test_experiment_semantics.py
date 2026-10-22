"""Focused unit regressions for original experiment semantics; no child processes."""

import json
from types import SimpleNamespace

import pytest

from bittorrent_lite.experiments.scripts import collect, launcher, matrix, plot


pytestmark = pytest.mark.timeout(20)


@pytest.mark.parametrize("output_ok,exit_code,expected", [
    (True, 0, "ok"), (False, 0, "failed"), (None, 0, "failed"), (True, 7, "failed"),
])
def test_execute_requires_independent_outputs_and_clean_exit(tmp_path, monkeypatch,
                                                            output_ok, exit_code, expected):
    source = tmp_path / "source.bin"
    source.write_bytes(b"source")
    metadata = tmp_path / "metadata.json"
    metadata.write_text("{}", encoding="utf-8")
    config = launcher.load_config(None)
    config.update(L=1, fixture=str(source), metadata=str(metadata), launch_gap_s=0)
    run = launcher.Run(config, tmp_path / "runs")
    monkeypatch.setattr(run, "_preflight", lambda: None)
    monkeypatch.setattr(run, "_start", lambda child: None)
    monkeypatch.setattr(run, "_wait_ready", lambda *args: None)
    monkeypatch.setattr(run, "_monitor", lambda: ("ok", ""))
    def stop():
        for child in run.children:
            child.exit_code = exit_code if child.role == "downloader" else 0
    monkeypatch.setattr(run, "_stop_all", stop)
    monkeypatch.setattr(run, "_check_outputs", lambda: {"peer-01": output_ok})
    monkeypatch.setattr(launcher, "git_revision", lambda: "unit-fixture")
    result = run.execute()
    assert result["status"] == expected
    if expected == "failed":
        assert result["failure_reason"]
    assert json.loads((run.dir / "manifest.json").read_text("utf-8"))["status"] == expected


def failure_run(tmp_path):
    config = launcher.load_config(None)
    config.update(L=2, scenario="failure", timeout_s=1)
    run = launcher.Run(config, tmp_path)
    run.run_start = launcher.time.monotonic()
    target = launcher.Child("peer-02", "downloader", 7002, [], tmp_path / "events.jsonl")
    target.process = SimpleNamespace(poll=lambda: None, kill=lambda: pytest.fail("must not kill"))
    run.children = [target]
    return run, target


@pytest.mark.parametrize("already_consumed", [False, True])
def test_failure_does_not_kill_completed_target_from_fetched_history(tmp_path, monkeypatch,
                                                                   already_consumed):
    run, target = failure_run(tmp_path)
    batch = [{"event": "progress", "pieces": 1, "total": 4},
             {"event": "complete", "final_hash_ok": True}]
    if already_consumed:
        target.events = batch
        monkeypatch.setattr(target, "poll_events", lambda: [])
    else:
        def poll():
            target.events.extend(batch)
            return batch
        monkeypatch.setattr(target, "poll_events", poll)
    status, reason = run._monitor()
    assert status == "not_executed"
    assert "completed" in reason
    assert run.trigger is None and not target.killed_by_harness


@pytest.mark.parametrize("pieces,returncode", [(4, None), (1, 3)])
def test_failure_trigger_requires_live_incomplete_target(tmp_path, monkeypatch, pieces, returncode):
    run, target = failure_run(tmp_path)
    target.process.poll = lambda: returncode
    event = {"event": "progress", "pieces": pieces, "total": 4}
    monkeypatch.setattr(target, "poll_events", lambda: [event])
    status, _ = run._monitor()
    assert status == "not_executed"
    assert run.trigger is None and not target.killed_by_harness


@pytest.mark.parametrize("status", ["failed", "timeout", "not_executed"])
def test_matrix_stops_and_returns_nonzero_for_unsuccessful_run(monkeypatch, status):
    calls = []
    monkeypatch.setattr(matrix, "plan_runs", lambda *args: [{"name": "first"}, {"name": "second"}])
    def fake_run(config, root):
        calls.append(config["name"])
        return SimpleNamespace(execute=lambda: {
            "run_id": config["name"], "status": status, "failure_reason": "controlled unit failure"})
    monkeypatch.setattr(matrix, "Run", fake_run)
    monkeypatch.setattr(matrix, "collect", lambda *args: ([], [], []))
    monkeypatch.setattr(matrix.time, "sleep", lambda *args: None)
    assert matrix.main(["--pause-s", "0"]) == 1
    assert calls == ["first"]


def test_matrix_rejects_empty_repeats():
    with pytest.raises(SystemExit) as error:
        matrix.main(["--repeats", "0", "--dry-run"])
    assert error.value.code == 2


def test_matrix_returns_nonzero_for_collection_problem(monkeypatch):
    monkeypatch.setattr(matrix, "plan_runs", lambda *args: [{"name": "one"}])
    monkeypatch.setattr(matrix, "Run", lambda *args: SimpleNamespace(execute=lambda: {
        "run_id": "one", "status": "ok", "failure_reason": ""}))
    monkeypatch.setattr(matrix, "collect", lambda *args: ([], [], ["controlled inconsistent evidence"]))
    monkeypatch.setattr(matrix.time, "sleep", lambda *args: None)
    assert matrix.main(["--pause-s", "0"]) == 1


def observed_run(tmp_path, killed=False, final=True):
    config = launcher.load_config(None)
    config.update(L=1, S=1)
    manifest = {
        "run_id": "unit-evidence", "config": config, "status": "ok", "target": None,
        "file_bytes": 4, "run_start_mono": 1, "distribution_start_mono": 10,
        "distribution_origin": "first_peer_launch", "output_hash_ok": {"peer-01": True},
        "processes": [
            {"proc_id": "seed-01", "role": "seeder", "launch_mono": 10,
             "exit_code": 0, "killed_by_harness": False},
            {"proc_id": "peer-01", "role": "downloader", "launch_mono": 11,
             "exit_code": 1 if killed else 0, "killed_by_harness": killed},
        ],
    }
    events = [
        {"event": "listening", "mono": 11.1},
        {"event": "frame_sent", "frame_complete": True, "message_type": "REQUEST",
         "piece": 0, "payload_bytes": 0},
        {"event": "frame_sent", "frame_complete": True, "message_type": "REQUEST",
         "piece": 0, "payload_bytes": 0},
        {"event": "frame_sent", "frame_complete": True, "message_type": "PIECE",
         "piece": 1, "payload_bytes": 5},
        {"event": "piece_verification", "outcome": "hash_mismatch"},
        {"event": "piece_verified", "piece": 0, "bytes": 4},
        {"event": "piece_verified", "piece": 0, "bytes": 4},
    ]
    if final:
        events += [
            {"event": "complete", "mono": 14, "final_hash_ok": True},
            {"event": "counters", "mono": 14.1, "verified_download_bytes": 4, "uploaded_payload_bytes": 0},
            {"event": "exit", "mono": 14.2, "reason": "stopped"},
        ]
    for index, event in enumerate(events):
        event.setdefault("mono", 11.2 + index / 10)
    (tmp_path / "events").mkdir()
    (tmp_path / "events" / "peer-01.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in events), encoding="utf-8")
    return manifest, events


def test_collector_uses_actual_event_names_and_first_peer_timing(tmp_path):
    manifest, events = observed_run(tmp_path)
    row = collect.peer_rows(manifest, tmp_path)[1]
    assert collect.logged_metrics(events) == {
        "messages_sent": 3, "requests_sent": 2, "retries": 1,
        "uploaded_payload_bytes": 5, "verified_download_bytes": 4, "hash_failures": 1,
    }
    assert row["metrics_scope"] == "final_logged"
    assert row["messages_sent"] == 3 and row["requests_sent"] == 2
    assert row["uploaded_payload_bytes"] == 5
    assert row["hash_failures"] == 1 and row["retries"] == 1
    assert row["completion_s"] == 3 and row["finish_s"] == 4
    assert row["final_hash_ok"] is True


@pytest.mark.parametrize("killed,final", [(True, False), (True, True), (False, False)])
def test_killed_or_unclean_metrics_are_only_observed_prefix(tmp_path, killed, final):
    manifest, _ = observed_run(tmp_path, killed=killed, final=final)
    row = collect.peer_rows(manifest, tmp_path)[1]
    assert row["metrics_scope"] == "observed_prefix"
    assert all(row[key] == "" for key in collect.COUNTER_KEYS)
    assert row["observed_messages_sent"] == 3
    assert row["observed_requests_sent"] == 2
    assert row["observed_retries"] == 1
    assert row["observed_hash_failures"] == 1
    assert row["observed_verified_download_bytes"] == 4


def test_peer_hash_claim_cannot_replace_independent_output_check(tmp_path):
    manifest, _ = observed_run(tmp_path)
    manifest["output_hash_ok"]["peer-01"] = None
    peers = collect.peer_rows(manifest, tmp_path)
    assert peers[1]["final_hash_ok"] == ""
    problems = collect.validate([collect.run_row(manifest, peers)], peers)
    assert any("independent output hash not verified" in problem for problem in problems)


def test_failure_requires_exact_survivor_identities(tmp_path):
    manifest, _ = observed_run(tmp_path)
    manifest["config"]["scenario"] = "failure"
    manifest["target"] = "peer-01"
    peers = collect.peer_rows(manifest, tmp_path)
    problems = collect.validate([collect.run_row(manifest, peers)], peers)
    assert any("completed peer identities differ" in problem for problem in problems)


def test_collect_empty_input_is_not_success(tmp_path):
    runs, peers, problems = collect.collect(tmp_path / "missing", tmp_path / "results")
    assert runs == [] and peers == []
    assert "no run manifests collected" in problems


def test_free_rider_comparison_has_one_matched_population_mean_per_repeat():
    runs = [{"run_id": f"r{i}", "L": 6, "status": "ok"} for i in range(3)]
    peers = {r["run_id"]: [
        {"peer_id": f"peer-{j:02d}", "role_at_start": "downloader",
         "completion_s": j + i if j != 6 else 1000, "finish_s": j + i}
        for j in range(1, 7)] for i, r in enumerate(runs)}
    assert plot.completion_means(runs, peers, "peer-06", False) == [3, 4, 5]
    assert plot.completion_means(runs, peers, "peer-06", True) == [1000, 1000, 1000]
    assert plot.survivor_finish(peers, runs[0], "peer-06") == 5
    peers["r0"].pop(0)
    assert plot.survivor_finish(peers, runs[0], "peer-06") is None
    assert plot.completion_means(runs, peers, "peer-06", False) == [4, 5]


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_nonfinite_plot_values_are_undefined(value):
    assert plot._num(value) is None
