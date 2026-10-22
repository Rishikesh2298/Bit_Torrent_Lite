"""Phase 03 in-process command handlers; external commands remain Phase 05.

Each fixture is also a versioned Phase 05 stdin/input resource. See the adjacent
procedure for recorder/guardian invocation. These unit tests claim no processes.
"""
import copy
import io
import json
from pathlib import Path

import pytest

from bittorrent_lite.scheduling.request_pipeline.__main__ import ActionError, run
from bittorrent_lite.scheduling.request_pipeline import __main__ as pipeline_cli
from bittorrent_lite.scheduling.recovery import __main__ as recovery_cli
from bittorrent_lite.scheduling.choking_policy import __main__ as choking_cli

FIXTURES = Path(__file__).with_name("fixtures")
PIPELINE_OPERATIONS = ["register_connection", "set_available", "set_permissions", "reserve", "fill",
                       "confirm_sent", "start_verification", "finish_verification", "reject", "send_failed",
                       "cancel", "disconnect", "expire", "snapshot"]


@pytest.mark.parametrize("raw", [b"\xff", b"[" * 4000 + b"0" + b"]" * 4000],
                         ids=["invalid-utf8", "excessive-json-nesting"])
def test_pipeline_malformed_file_returns_controlled_error_without_result(tmp_path, capsys, raw):
    source = tmp_path / "malformed input.json"
    source.write_bytes(raw)
    assert pipeline_cli.main(["--input", str(source)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error: ")
    assert "Traceback" not in captured.err
    assert source.read_bytes() == raw


def test_recovery_deep_json_error_preserves_state_and_continues(monkeypatch, capsys):
    lines = [json.dumps({"op": "create", "num_pieces": 3, "seed": 7}),
             json.dumps({"op": "snapshot", "now": 0}),
             "[" * 4000 + "0" + "]" * 4000,
             json.dumps({"op": "snapshot", "now": 0})]
    monkeypatch.setattr(recovery_cli.sys, "stdin", io.StringIO("\n".join(lines) + "\n"))
    assert recovery_cli.main() == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    rows = [json.loads(line) for line in captured.out.splitlines()]
    assert len(rows) == 4
    assert rows[0] == {"ok": True, "result": None}
    assert rows[1]["ok"] is rows[3]["ok"] is True
    assert rows[1] == rows[3]
    assert rows[2]["ok"] is False and rows[2]["error"] == "RecursionError"
    assert rows[2]["message"]


def assert_pipeline_output(output, actions):
    results = output["results"]
    assert len(results) == len(actions) == 17
    assert [row["action"] for row in results] == list(range(1, 18))
    assert [row["op"] for row in results] == [row["op"] for row in actions]
    assert set(row["op"] for row in results) == set(PIPELINE_OPERATIONS)
    assert results[0]["result"] is None and results[1]["result"] is None
    assert results[2]["result"] == []
    assert results[3]["result"]["request_id"] == 1
    assert results[3]["result"]["piece_index"] == 0
    assert results[4]["result"] is True and results[5]["result"] is True
    assert [(row["kind"], row["piece_index"]) for row in results[6]["result"]] == [("completed", 0)]
    assert [(row["request_id"], row["piece_index"]) for row in results[7]["result"]] == [(2, 1), (3, 2)]
    for index, request, piece, reason in [(8, 2, 1, "rejected"), (9, 3, 2, "diagnostic_send_failure"),
                                         (11, 4, 3, "operator_cancel"), (15, 6, 5, "disconnected")]:
        row, = results[index]["result"]
        assert (row["request_id"], row["piece_index"], row["kind"], row["reason"]) == (request, piece, "canceled", reason)
    for index, request, piece in [(10, 4, 3), (12, 5, 4), (14, 6, 5)]:
        assert (results[index]["result"]["request_id"], results[index]["result"]["piece_index"]) == (request, piece)
    expired, = results[13]["result"]
    assert (expired["request_id"], expired["kind"], expired["reason"]) == (5, "expired", "send_unconfirmed")
    final = output["snapshot"]
    assert results[16]["result"] == final
    assert final["owned"] == [0] and final["pending"] == [] and final["connections"] == []
    assert final["counters"] == {"issued": 6, "completed": 1, "invalid": 0, "expired": 1, "canceled": 4}


def test_pipeline_all_operation_fixture_semantics():
    document = json.loads((FIXTURES / "pipeline-all-operations.json").read_bytes())
    assert_pipeline_output(run(document), document["actions"])


@pytest.mark.parametrize("operation", PIPELINE_OPERATIONS)
def test_pipeline_rejects_extra_argument_for_every_operation(operation):
    document = json.loads((FIXTURES / "pipeline-all-operations.json").read_bytes())
    action = copy.deepcopy(next(row for row in document["actions"] if row["op"] == operation))
    action["unexpected"] = True
    with pytest.raises(ActionError, match="action 1: unknown fields"):
        run({"num_pieces": 6, "actions": [action, {"op": "snapshot"}]})


def run_jsonl_handler(module, monkeypatch, capsys, name):
    raw = (FIXTURES / name).read_bytes()
    monkeypatch.setattr(module.sys, "stdin", io.StringIO(raw.decode("utf-8")))
    module.main()
    captured = capsys.readouterr()
    assert not captured.err
    rows = [json.loads(line) for line in captured.out.splitlines()]
    assert len(rows) == len(raw.splitlines())
    return rows


def assert_recovery_output(rows):
    assert len(rows) == 8
    assert [row["ok"] for row in rows] == [True, True, True, False, True, True, True, True]
    assert rows[0]["result"] is rows[1]["result"] is rows[6]["result"] is None
    assert rows[2]["result"] == [0] and rows[4]["result"] == [2, 0]
    assert rows[3]["error"] == "ValueError" and rows[3]["message"]
    assert rows[5]["result"] is True
    final = rows[7]["result"]
    assert final["owned"] == [2] and final["penalties"] == []
    assert final["counters"]["reject"] == 1 and final["successes"] == 1


def test_recovery_all_operations_and_error_continuation(monkeypatch, capsys):
    assert_recovery_output(run_jsonl_handler(recovery_cli, monkeypatch, capsys, "recovery-all-operations.jsonl"))


@pytest.mark.parametrize("operation", ["create", "rank_candidates", "allow_duplicate", "failed", "succeeded", "snapshot"])
def test_recovery_cli_rejects_unknown_fields_without_losing_state(operation):
    actions = [json.loads(line) for line in (FIXTURES / "recovery-all-operations.jsonl").read_bytes().splitlines()]
    action = copy.deepcopy(next(row for row in actions if row["op"] == operation))
    action["unexpected"] = True
    policy = None
    if operation != "create":
        policy, _ = recovery_cli._handle(actions[0], None)
        before = policy.snapshot(now=0)
    with pytest.raises(ValueError):
        recovery_cli._handle(action, policy)
    if policy is not None:
        assert policy.snapshot(now=0) == before


def assert_choking_output(rows):
    assert len(rows) == 21
    for index in [0, 1, 2, 7, 10, 11, 12, 13, 15, 16]:
        assert rows[index] == {"ok": True}
    assert rows[3]["intents"] == [{"token": "1:1", "peer_id": "alice", "allow": True, "issued_at": 0.0}]
    assert rows[3]["state"]["peers"][0]["recent_bytes"] == 4096
    assert rows[4] == {"accepted": True}
    assert rows[5]["ok"] is False and rows[5]["error"]["type"] == "ValueError"
    assert rows[6]["state"]["now"] == 0 and rows[6]["state"]["peers"][0]["confirmed"]
    assert rows[8]["intents"] == [{"token": "1:2", "peer_id": "alice", "allow": False, "issued_at": 1.0}]
    assert rows[9] == {"accepted": True}
    assert rows[14]["intents"] == [] and rows[14]["state"]["closed"]
    assert rows[17]["intents"] == [{"token": "2:1", "peer_id": "bob", "allow": True, "issued_at": 1.0}]
    assert rows[18] == {"accepted": False} and rows[19] == {"accepted": True}
    final = rows[20]["state"]
    assert not final["closed"] and not final["closing"] and final["upload_enabled"] and not final["seeder"]
    assert final["peers"][0]["pending"] is None and not final["peers"][0]["confirmed"]
    assert not final["peers"][0]["reserved"]


def test_choking_all_operations_error_continuation_and_epoch_safety(monkeypatch, capsys):
    assert_choking_output(run_jsonl_handler(choking_cli, monkeypatch, capsys, "choking-all-operations.jsonl"))


@pytest.mark.parametrize("operation", ["config", "connect", "disconnect", "set_interested", "record_contribution",
                                      "set_seeder", "set_upload_enabled", "tick", "acknowledge", "snapshot", "shutdown", "reset"])
def test_choking_cli_rejects_unknown_fields_for_every_operation(operation):
    actions = [json.loads(line) for line in (FIXTURES / "choking-all-operations.jsonl").read_bytes().splitlines()]
    action = copy.deepcopy(next(row for row in actions if row["op"] == operation))
    action["unexpected"] = True
    session = choking_cli._Session()
    if operation != "config":
        session.handle(actions[0])
        session.handle(actions[1])
        before = session.policy.snapshot(0)
    with pytest.raises(ValueError, match="unexpected keys"):
        session.handle(action)
    if operation != "config":
        assert session.policy.snapshot(0) == before
