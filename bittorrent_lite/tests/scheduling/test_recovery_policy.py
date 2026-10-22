"""Contracts and adversarial input checks for the supplied recovery policy."""
import json
import subprocess
import sys

import pytest

from bittorrent_lite.scheduling.recovery import RecoveryConfig
from bittorrent_lite.scheduling.recovery import RecoveryPolicy
from bittorrent_lite.scheduling.recovery import CapacityError


def rank(p, now, provider="A", candidates=None):
    return p.rank_candidates(now=now, provider=provider,
                             candidates=[0, 1, 2] if candidates is None else candidates,
                             availability=[2, 1, 3])


def test_backoff_streak_survives_expiry_and_local_failure_cannot_shorten():
    p = RecoveryPolicy(3)
    for now, delay in [(0, 2), (2, 4), (6, 10), (16, 10)]:
        p.failed(now=now, provider="A", piece=1, kind="reject")
        assert 1 not in rank(p, now)
        p.failed(now=now, provider="A", piece=1, kind="enqueue_failed")
        assert p.snapshot(now=now)["penalties"][0]["cooldown_deadline"] == now + delay
        assert 1 not in rank(p, now + delay - .001)
        assert rank(p, now + delay)[0] == 1
    snap = p.snapshot(now=26)
    assert snap["penalties"][0]["streak"] == 4
    assert snap["counters"]["reject"] == 4
    assert snap["counters"]["enqueue_failed"] == 4


def test_exclusion_survives_disconnect_until_success_cleans_all_providers():
    p = RecoveryPolicy(3)
    p.failed(now=0, provider="A", piece=1, kind="invalid_piece")
    p.failed(now=0, provider="B", piece=1, kind="response_timeout")
    before = p.snapshot(now=0)["penalties"]
    p.failed(now=0, provider="A", piece=1, kind="disconnect")
    p.failed(now=0, provider="A", piece=1, kind="choke")
    assert p.snapshot(now=0)["penalties"] == before
    assert 1 not in rank(p, 100)
    assert 1 in rank(p, 100, "B")
    p.succeeded(now=100, provider="B", piece=1)
    snap = p.snapshot(now=100)
    assert snap["owned"] == [1]
    assert snap["penalty_entry_count"] == snap["penalty_provider_count"] == 0
    p.succeeded(now=100, provider="B", piece=1)
    p.failed(now=100, provider="A", piece=1, kind="invalid_piece")
    assert p.snapshot(now=100) == snap
    assert 1 not in rank(p, 100, "C")


@pytest.mark.parametrize("limit", ["max_penalty_entries", "max_penalty_providers"])
def test_capacity_is_atomic_and_success_frees_capacity(limit):
    p = RecoveryPolicy(3, RecoveryConfig(**{limit: 1}))
    p.failed(now=0, provider="A", piece=0, kind="reject")
    before = p.snapshot(now=0)
    with pytest.raises(CapacityError):
        p.failed(now=5, provider="B", piece=1, kind="invalid_piece")
    assert p.snapshot(now=0) == before
    p.failed(now=0, provider="A", piece=0, kind="reject")
    p.failed(now=0, provider="B", piece=1, kind="disconnect")
    p.succeeded(now=0, provider="A", piece=0)
    p.failed(now=0, provider="B", piece=1, kind="invalid_piece")
    assert p.snapshot(now=0)["penalty_provider_count"] == 1


@pytest.mark.parametrize("strategy", ["rarest-first", "sequential", "random"])
def test_selection_is_deterministic_copied_and_filters_owned_zero_and_penalties(strategy):
    config = RecoveryConfig(strategy=strategy)
    p, q = RecoveryPolicy(5, config, seed=37), RecoveryPolicy(5, config, seed=37)
    candidates, availability = [4, 3, 2, 1, 0], [3, 0, 1, 2, 1]
    for obj in (p, q):
        obj.succeeded(now=0, provider="local", piece=4)
        obj.failed(now=0, provider="A", piece=3, kind="reject")
    kwargs = dict(now=0, provider="A", candidates=candidates, availability=availability)
    result = p.rank_candidates(**kwargs)
    assert result == q.rank_candidates(**kwargs)
    assert set(result) == {0, 2}
    if strategy == "rarest-first":
        assert result == [2, 0]
    elif strategy == "sequential":
        assert result == [0, 2]
    assert candidates == [4, 3, 2, 1, 0]
    assert availability == [3, 0, 1, 2, 1]


def duplicate(p, now=5, **overrides):
    args = dict(now=now, piece=0, provider="B", missing_count=1,
                no_unreserved_candidates=True,
                pending=[dict(request_id=1, provider="A", piece=0,
                              queued_at=0, sent_at=0, verifying=False)])
    args.update(overrides)
    return p.allow_duplicate(**args)


def test_endgame_age_provider_penalty_and_cap_gates():
    p = RecoveryPolicy(3)
    assert not duplicate(p, now=4.99)
    assert duplicate(p)
    assert not duplicate(p, provider="A")
    assert not duplicate(p, no_unreserved_candidates=False)
    assert not duplicate(p, missing_count=0)
    assert not duplicate(p, pending=[])
    assert not duplicate(p, pending=[dict(request_id=1, provider="A", piece=0,
                                         queued_at=0, sent_at=None, verifying=False)])
    assert not duplicate(p, pending=[dict(request_id=1, provider="A", piece=0,
                                         queued_at=0, sent_at=0, verifying=True)])
    assert not duplicate(p, pending=[dict(request_id=i, provider=str(i), piece=0,
                                         queued_at=0, sent_at=0, verifying=False) for i in (1, 2)])
    p.failed(now=5, provider="B", piece=0, kind="send_failed")
    assert not duplicate(p)
    assert duplicate(p, now=6)
    p.succeeded(now=6, provider="A", piece=0)
    assert not duplicate(p, now=6)


@pytest.mark.parametrize("config", [RecoveryConfig(endgame_enabled=False),
    RecoveryConfig(max_copies=1), RecoveryConfig(endgame_remaining=1)])
def test_endgame_configuration_limits(config):
    assert not duplicate(RecoveryPolicy(3, config), missing_count=2)


@pytest.mark.parametrize("operation", [
    lambda p: p.failed(now=1, provider="A", piece=True, kind="reject"),
    lambda p: p.failed(now=1, provider="", piece=0, kind="reject"),
    lambda p: p.failed(now=1, provider="x" * 129, piece=0, kind="reject"),
    lambda p: p.failed(now=1, provider="A", piece=0, kind="unknown"),
    lambda p: p.succeeded(now=1, provider="A", piece=3),
    lambda p: p.snapshot(now=float("nan")),
    lambda p: p.snapshot(now=-1),
    lambda p: p.rank_candidates(now=1, provider="A", candidates=[0, 0], availability=[1] * 3),
    lambda p: p.rank_candidates(now=1, provider="A", candidates=[0], availability=[True, 1, 1]),
    lambda p: duplicate(p, now=1, pending=[dict(request_id=1, provider="A", piece=0,
                                               queued_at=0, sent_at=2, verifying=False)]),
    lambda p: duplicate(p, now=1, missing_count=True),
    lambda p: duplicate(p, now=1, pending=[{"request_id": 1}]),
])
def test_invalid_inputs_leave_state_time_and_rng_unchanged(operation):
    p, reference = RecoveryPolicy(3, seed=9), RecoveryPolicy(3, seed=9)
    before = p.snapshot(now=0)
    with pytest.raises(ValueError):
        operation(p)
    assert p.snapshot(now=0) == before
    assert rank(p, 0) == rank(reference, 0)


@pytest.mark.parametrize("limit", [0, 2])
def test_history_is_bounded_and_snapshots_are_detached(limit):
    p = RecoveryPolicy(3, RecoveryConfig(recent_event_limit=limit))
    for i in range(10):
        p.failed(now=i, provider="A", piece=0, kind="disconnect")
    snap = p.snapshot(now=9)
    assert len(snap["recent_events"]) == limit
    assert snap["omitted_events"] == 10 - limit
    assert snap["counters"]["disconnect"] == 10
    snap["config"]["retry_delays"].clear()
    snap["recent_events"].clear()
    snap["counters"]["disconnect"] = -1
    assert p.snapshot(now=9)["config"]["retry_delays"] == [2, 4, 10]
    assert p.snapshot(now=9)["counters"]["disconnect"] == 10
    with pytest.raises(ValueError):
        p.snapshot(now=8)


@pytest.mark.parametrize("kwargs", [dict(retry_delays=[2, 4]), dict(retry_delays=()),
    dict(retry_delays=(4, 2)), dict(retry_delays=(float("inf"),)),
    dict(local_send_cooldown=0), dict(endgame_enabled=1), dict(endgame_remaining=True),
    dict(max_copies=3), dict(max_penalty_entries=0), dict(recent_event_limit=-1)])
def test_invalid_config(kwargs):
    with pytest.raises(ValueError):
        RecoveryConfig(**kwargs)


def test_json_lines_cli_errors_do_not_lose_session():
    lines = [dict(op="create", num_pieces=3, config={"retry_delays": [2, 4]}),
             dict(op="failed", now=0, provider="A", piece=0, kind="reject"),
             dict(op="create", num_pieces=1), dict(op=[]),
             dict(op="snapshot", now=0)]
    result = subprocess.run([sys.executable, "-m", "bittorrent_lite.scheduling.recovery"],
                            input="\n".join(json.dumps(x) for x in lines) + "\n{bad\n",
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    rows = [json.loads(x) for x in result.stdout.splitlines()]
    assert [r["ok"] for r in rows] == [True, True, False, False, True, False]
    assert rows[4]["result"]["counters"]["reject"] == 1
    assert "Traceback" not in result.stderr
