"""Contract and adversarial lifecycle coverage for the submitted Part 2 package."""
import json
import random
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from bittorrent_lite.common.paths import project_root

import pytest

from bittorrent_lite.scheduling.request_pipeline import PipelineManager
from bittorrent_lite.scheduling.request_pipeline import PipelineConfig
from bittorrent_lite.scheduling.request_pipeline import RequestKey
from bittorrent_lite.scheduling.request_pipeline.__main__ import ActionError
from bittorrent_lite.scheduling.request_pipeline.__main__ import run


def ready(n=12, sources=2, config=None):
    manager = PipelineManager(n, config=config)
    for cid in range(1, sources + 1):
        manager.register_connection(cid, f"source-{cid}", now=0)
        manager.set_available(cid, range(n), now=0)
        manager.set_permissions(cid, interested=True, unchoked=True, now=0)
    return manager


def test_fair_fill_rotates_and_respects_candidate_order():
    p = ready()
    first = p.fill({1: list(range(12)), 2: list(range(12))}, now=0)
    assert [r.key.connection_id for r in first] == [1, 2] * 4
    assert [r.key.piece_index for r in first] == list(range(8))
    assert p.reserve(1, 8, now=0) is None
    for r in first:
        p.cancel(r.key, reason="reset", now=0)
    second = p.fill({1: [11, 10], 2: [11, 10]}, now=0)
    assert [(r.key.connection_id, r.key.piece_index) for r in second] == [(2, 11), (1, 10)]


def test_global_bound_and_permission_gates():
    p = ready(100, 10)
    assert len(p.fill({cid: list(range(100)) for cid in range(1, 11)}, now=0)) == 40
    assert all(r["count"] == 4 for r in p.snapshot()["outstanding"])
    with pytest.raises(ValueError):
        p.register_connection(11, "eleven", now=0)
    p.disconnect(1, now=0)
    p.register_connection(11, "source-1", now=0)
    p.set_available(11, [99], now=0)
    assert p.reserve(11, 99, now=0) is None
    p.set_permissions(11, interested=True, unchoked=False, now=0)
    assert p.reserve(11, 99, now=0) is None
    p.set_permissions(11, interested=True, unchoked=True, now=0)
    assert p.reserve(11, 99, now=0)
    with pytest.raises(ValueError):
        p.register_connection(1, "new", now=0)
    with pytest.raises(ValueError):
        p.register_connection(12, "source-1", now=0)


def test_deadline_boundaries_and_delayed_confirmation():
    p = ready(config=PipelineConfig(response_timeout=7, send_confirm_timeout=3))
    a = p.reserve(1, 0, now=0)
    b = p.reserve(1, 1, now=0)
    assert p.expire(now=2.99) == ()
    assert p.confirm_sent(a.key, sent_at=1, now=2.99)
    assert p.confirm_sent(a.key, sent_at=2, now=3)
    expired = p.expire(now=3)
    assert [(o.key, o.reason) for o in expired] == [(b.key, "send_unconfirmed")]
    assert p.expire(now=7.99) == ()
    assert p.expire(now=8)[0].key == a.key
    replacement = p.reserve(1, 0, now=8)
    assert replacement.key.request_id > b.key.request_id
    assert not p.confirm_sent(a.key, sent_at=1, now=8)
    assert p.reject(a.key, now=8) == ()
    assert not p.start_verification(a.key, now=8)
    assert p.snapshot()["pending"][0]["request_id"] == replacement.key.request_id


def test_competing_requests_verification_and_winner_cleanup():
    p = ready(sources=3)
    a = p.reserve(1, 0, now=0)
    assert p.reserve(2, 0, now=0) is None
    assert p.reserve(1, 0, allow_duplicate=True, now=0) is None
    b = p.reserve(2, 0, allow_duplicate=True, now=0)
    assert p.reserve(3, 0, allow_duplicate=True, now=0) is None
    assert p.finish_verification(a.key, valid=True, now=0) == ()
    assert p.start_verification(a.key, now=0)
    assert not p.start_verification(a.key, now=0)
    assert not p.start_verification(b.key, now=0)
    assert p.reject(a.key, now=0) == ()
    assert p.send_failed(a.key, reason="late", now=0) == ()
    assert p.confirm_sent(a.key, sent_at=0, now=0)
    assert p.snapshot()["pending"][0]["deadline"] is None
    assert [o.key for o in p.expire(now=5)] == [b.key]
    assert p.snapshot()["piece_state_counts"]["VERIFYING"] == 1
    assert p.finish_verification(a.key, valid=False, now=5)[0].kind == "invalid"
    assert p.snapshot()["piece_state_counts"]["MISSING"] == 12
    a = p.reserve(1, 0, now=5)
    b = p.reserve(2, 0, allow_duplicate=True, now=5)
    assert p.start_verification(b.key, now=5)
    out = p.finish_verification(b.key, valid=True, now=5)
    assert [(o.kind, o.key) for o in out] == [("completed", b.key), ("canceled", a.key)]
    assert out[1].reason == "another_request_completed"
    assert p.snapshot()["owned"] == [0]
    assert all(r["count"] == 0 for r in p.snapshot()["outstanding"])
    assert p.reserve(3, 0, allow_duplicate=True, now=5) is None
    assert p.finish_verification(b.key, valid=True, now=5) == ()


@pytest.mark.parametrize("cleanup", ["invalid", "cancel", "disconnect"])
def test_removing_one_copy_preserves_other_reservation(cleanup):
    p = ready()
    a = p.reserve(1, 0, now=0)
    b = p.reserve(2, 0, allow_duplicate=True, now=0)
    p.start_verification(a.key, now=0)
    if cleanup == "invalid":
        p.finish_verification(a.key, valid=False, now=0)
    elif cleanup == "cancel":
        p.cancel(a.key, reason="user", now=0)
    else:
        p.disconnect(1, now=0)
    snap = p.snapshot()
    assert snap["piece_state_counts"]["REQUESTED"] == 1
    assert [r["request_id"] for r in snap["pending"]] == [b.key.request_id]
    assert p.finish_verification(a.key, valid=True, now=0) == ()
    assert p.start_verification(b.key, now=0)
    p.finish_verification(b.key, valid=True, now=0)
    assert p.snapshot()["owned"] == [0]


def test_permissions_keep_verifying_and_advertisements_are_copied():
    p = ready()
    a, b = p.fill({1: [0, 1]}, now=0)
    p.start_verification(a.key, now=0)
    bits = [2, 3]
    p.set_available(1, bits, now=0)
    bits.clear()
    assert len(p.snapshot()["pending"]) == 2
    out = p.set_permissions(1, interested=False, unchoked=True, now=0)
    assert [o.key for o in out] == [b.key]
    assert p.expire(now=100) == ()
    snap = p.snapshot()
    snap["connections"][0]["available"].clear()
    assert p.snapshot()["connections"][0]["available"] == [2, 3]
    with pytest.raises(FrozenInstanceError):
        a.verifying = True
    assert not a.verifying  # returned snapshot did not change with live state


@pytest.mark.parametrize("operation", [
    lambda p: p.reserve(True, 0, now=1),
    lambda p: p.reserve(1, True, now=1),
    lambda p: p.reserve(1, 12, now=1),
    lambda p: p.reserve(1, 0, allow_duplicate=1, now=1),
    lambda p: p.set_available(1, [0, 12], now=1),
    lambda p: p.set_permissions(1, interested=1, unchoked=True, now=1),
    lambda p: p.fill({1: [0], 2: [1, 1]}, now=1),
    lambda p: p.fill({1: [0], 99: [1]}, now=1),
    lambda p: p.confirm_sent(RequestKey(1, 1, 0), sent_at=2, now=1),
    lambda p: p.finish_verification(RequestKey(1, 1, 0), valid=1, now=1),
    lambda p: p.cancel(RequestKey(1, 1, 0), reason="", now=1),
    lambda p: p.expire(now=float("nan")),
    lambda p: p.expire(now=-1),
])
def test_invalid_calls_are_atomic(operation):
    p = ready()
    before = p.snapshot()
    with pytest.raises(ValueError):
        operation(p)
    assert p.snapshot() == before
    assert p.reserve(1, 0, now=0)  # invalid call did not advance global time


@pytest.mark.parametrize("cfg", [dict(window=0), dict(window=5), dict(window=True),
    dict(max_connections=0), dict(max_copies=3), dict(response_timeout=float("inf")),
    dict(send_confirm_timeout=False)])
def test_config_rejects_invalid_limits(cfg):
    with pytest.raises(ValueError):
        PipelineConfig(**cfg)


def test_clock_cannot_go_backward_and_historical_send_is_valid():
    p = ready()
    a = p.reserve(1, 0, now=10)
    before = p.snapshot()
    with pytest.raises(ValueError):
        p.expire(now=9)
    with pytest.raises(ValueError):
        p.confirm_sent(a.key, sent_at=9, now=11)
    assert p.snapshot() == before
    assert p.confirm_sent(a.key, sent_at=10, now=12)


def test_randomized_lifecycle_accounting():
    rng = random.Random(20261017)
    p = ready(20, 4)
    expected_owned = set()
    for step in range(1500):
        now = step / 10
        snap = p.snapshot()
        if snap["pending"] and rng.random() < .65:
            r = rng.choice(snap["pending"])
            key = RequestKey(r["connection_id"], r["request_id"], r["piece_index"])
            op = rng.randrange(6)
            if op == 0:
                p.confirm_sent(key, sent_at=now, now=now)
            elif op == 1:
                p.start_verification(key, now=now)
            elif op == 2:
                valid = rng.random() < .7
                outcomes = p.finish_verification(key, valid=valid, now=now)
                if any(o.kind == "completed" for o in outcomes):
                    expected_owned.add(key.piece_index)
            elif op == 3:
                p.cancel(key, reason="random", now=now)
            elif op == 4:
                p.reject(key, now=now)
            else:
                p.expire(now=now)
        else:
            p.reserve(rng.randrange(1, 5), rng.randrange(20),
                      allow_duplicate=bool(rng.randrange(2)), now=now)
        snap = p.snapshot()
        assert set(snap["owned"]) == expected_owned
        pending = snap["pending"]
        assert not expected_owned.intersection(r["piece_index"] for r in pending)
        assert len({r["request_id"] for r in pending}) == len(pending)
        for count in snap["outstanding"]:
            assert count["count"] == sum(r["connection_id"] == count["connection_id"] for r in pending)
            assert 0 <= count["count"] <= 4
        states = dict.fromkeys(["MISSING", "REQUESTED", "VERIFYING", "HAVE"], 0)
        for piece in range(20):
            records = [r for r in pending if r["piece_index"] == piece]
            assert len(records) <= 2
            assert sum(r["verifying"] for r in records) <= 1
            state = "HAVE" if piece in expected_owned else "VERIFYING" if any(r["verifying"] for r in records) else "REQUESTED" if records else "MISSING"
            states[state] += 1
        assert snap["piece_state_counts"] == states
        stats = snap["counters"]
        assert stats["issued"] == len(pending) + sum(stats[k] for k in ("completed", "invalid", "expired", "canceled"))
        json.dumps(snap, allow_nan=False)


@pytest.mark.parametrize("action", [{"op": []}, {"op": {}}, {"op": "nope"},
    {"op": "snapshot", "extra": 0}, {"op": "fill", "candidate_orders": {"01": []}, "now": 0}])
def test_cli_invalid_actions_report_action_number(action):
    with pytest.raises(ActionError, match="action 1:"):
        run({"num_pieces": 3, "actions": [action, {"op": "snapshot"}]})


def test_cli_example_and_error_exit(tmp_path):
    root = project_root()
    result = subprocess.run([sys.executable, "-m", "bittorrent_lite.scheduling.request_pipeline", "--input",
                             str(root / "bittorrent_lite/scheduling/request_pipeline/example.json")],
                            cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["snapshot"]["counters"]["expired"] == 1
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"num_pieces": 1, "actions": [{"op": []}]}))
    result = subprocess.run([sys.executable, "-m", "bittorrent_lite.scheduling.request_pipeline", "--input", str(bad)],
                            cwd=root, capture_output=True, text=True)
    assert result.returncode == 2
    assert "action 1:" in result.stderr
    assert "Traceback" not in result.stderr
