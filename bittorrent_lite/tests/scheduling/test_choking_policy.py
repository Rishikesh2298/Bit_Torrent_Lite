"""Permission selection, reserved-slot safety, delayed ACKs and bounded state."""
import json
import random
import subprocess
import sys

import pytest

from bittorrent_lite.scheduling.choking_policy import Config
from bittorrent_lite.scheduling.choking_policy import PeerInfo
from bittorrent_lite.scheduling.choking_policy import Policy


def populated(count=4, config=None):
    p = Policy(config or Config())
    for i in range(count):
        p.connect(PeerInfo(str(i), True), 0)
    return p


def test_regular_contribution_and_optimistic_use_only_two_total_slots():
    p = populated()
    p.record_contribution('0', 1000, 0)
    d = p.tick(0)
    assert d.state.regular == ('0',)
    assert d.state.optimistic not in (None, '0')
    assert len(d.intents) == sum(peer.reserved for peer in d.state.peers) == 2
    assert not any(peer.confirmed for peer in d.state.peers)
    assert p.tick(0).intents == ()
    for intent in d.intents:
        assert p.acknowledge(intent.token, True, 1)
    assert sum(peer.confirmed for peer in p.snapshot(1).peers) == 2
    assert all(peer.allowed_seconds == 0 for peer in p.snapshot(1).peers)
    assert sum(peer.allowed_seconds for peer in p.snapshot(3).peers) == 4


def test_pending_allow_then_disable_waits_for_ack_before_deny():
    p = populated(1)
    grant, = p.tick(0).intents
    p.set_upload_enabled(False, 1)
    assert p.tick(1).intents == ()
    assert p.snapshot(1).peers[0].reserved
    assert p.acknowledge(grant.token, True, 2)
    deny, = p.tick(2).intents
    assert not deny.allow
    assert p.snapshot(2).peers[0].reserved
    p.acknowledge(deny.token, True, 3)
    assert not p.snapshot(3).peers[0].reserved
    assert not p.acknowledge(grant.token, True, 3)


def test_failed_commands_get_fresh_tokens_overdue_does_not_free_slots():
    p = populated()
    grants = p.tick(0).intents
    p.acknowledge(grants[0].token, False, 0)
    replacement, = p.tick(0).intents
    assert replacement.token != grants[0].token
    state = p.tick(11).state
    assert sum(peer.reserved for peer in state.peers) == 2
    assert sum(d.code == 'confirmation_overdue' for d in state.diagnostics) == 2
    assert len(p.tick(12).state.diagnostics) == len(state.diagnostics)
    assert p.acknowledge(grants[1].token, True, 12)
    assert p.acknowledge(replacement.token, True, 12)


def test_contribution_bucket_boundaries_and_seeder_fairness():
    p = populated(3)
    p.record_contribution('0', 100, .9)
    p.record_contribution('0', 200, 1.1)
    assert p.snapshot(4.99).peers[0].recent_bytes == 300
    assert p.snapshot(5).peers[0].recent_bytes == 200
    assert p.snapshot(6).peers[0].recent_bytes == 0
    p.set_seeder(True, 6)
    first = p.tick(6)
    for intent in first.intents:
        p.acknowledge(intent.token, True, 6)
    untouched = next(peer.peer_id for peer in first.state.peers if not peer.desired)
    assert untouched in p.tick(11).state.regular


def test_shutdown_blocks_mutation_preserves_inflight_allow_and_epoch_reset():
    p = populated(1)
    old, = p.tick(0).intents
    p.shutdown(1)
    assert not p.snapshot(1).closed
    with pytest.raises(RuntimeError):
        p.reset(1)
    with pytest.raises(RuntimeError):
        p.set_interested('0', False, 1)
    with pytest.raises(RuntimeError):
        p.record_contribution('0', 1, 1)
    assert p.acknowledge(old.token, True, 2)
    deny, = p.tick(2).intents
    p.acknowledge(deny.token, True, 2)
    assert p.snapshot(2).closed
    p.reset(2)
    p.connect(PeerInfo('0', True), 2)
    new, = p.tick(2).intents
    assert new.token.startswith('2:')
    assert not p.acknowledge(old.token, True, 2)


def test_reconnect_discards_stale_token_without_reusing_counter():
    p = populated(1)
    old, = p.tick(0).intents
    p.disconnect('0', 0)
    p.disconnect('0', 0)
    p.connect(PeerInfo('0', True), 0)
    new, = p.tick(0).intents
    assert old.token != new.token
    assert not p.acknowledge(old.token, True, 0)
    assert not p.snapshot(0).peers[0].confirmed


@pytest.mark.parametrize('operation', [
    lambda p: p.set_interested('0', 1, 1),
    lambda p: p.record_contribution('0', True, 1),
    lambda p: p.record_contribution('0', 16777217, 1),
    lambda p: p.connect(PeerInfo('0'), 1),
    lambda p: p.set_seeder(1, 1),
    lambda p: p.tick(float('nan')),
    lambda p: p.tick(-1),
    lambda p: p.acknowledge(1, True, 1),
])
def test_invalid_call_preserves_clock_and_state(operation):
    p = populated(1)
    state = p.snapshot(0)
    with pytest.raises(ValueError):
        operation(p)
    assert p.snapshot(0) == state


@pytest.mark.parametrize('kwargs', [dict(max_slots=1), dict(max_peers=True),
    dict(contribution_window=5.0), dict(contribution_window=True),
    dict(optimistic_interval=1), dict(confirmation_timeout=float('inf'))])
def test_config_validation(kwargs):
    with pytest.raises(ValueError):
        Config(**kwargs)


def test_seeded_randomized_permission_invariants_and_diagnostic_bound():
    config = Config(random_seed=19, diagnostic_capacity=8)
    p, other = populated(6, config), populated(6, config)
    rng = random.Random(17)
    for step in range(500):
        now = step / 4
        pid = str(rng.randrange(6))
        action = rng.randrange(4)
        argument = rng.randrange(1, 50)
        for policy in (p, other):
            if action == 0:
                policy.set_interested(pid, bool(argument % 2), now)
            elif action == 1:
                policy.record_contribution(pid, argument, now)
            elif action == 2:
                policy.set_upload_enabled(bool(argument % 2), now)
            else:
                policy.set_seeder(bool(argument % 2), now)
        decision = p.tick(now)
        assert decision == other.tick(now)
        assert sum(peer.reserved for peer in decision.state.peers) <= 2
        for intent in decision.intents:
            applied = bool(rng.randrange(2))
            p.acknowledge(intent.token, applied, now)
            other.acknowledge(intent.token, applied, now)
        assert len(p.snapshot(now).diagnostics) <= 8


def test_cli_expected_intent_and_error_recovery():
    rows = [dict(op='connect', peer=dict(peer_id='alice', interested=True), now=0),
            dict(op='record_contribution', peer_id='alice', verified_bytes=4096, now=0),
            dict(op='tick', now=0), dict(op='acknowledge', token='1:1', applied=True, now=0),
            dict(op=[]), dict(op='snapshot', now=0)]
    result = subprocess.run([sys.executable, '-m', 'bittorrent_lite.scheduling.choking_policy'],
                            input='\n'.join(json.dumps(row) for row in rows),
                            text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    out = [json.loads(line) for line in result.stdout.splitlines()]
    assert out[2]['intents'] == [dict(token='1:1', peer_id='alice', allow=True, issued_at=0.0)]
    assert out[3] == {'accepted': True}
    assert not out[4]['ok']
    assert out[5]['state']['peers'][0]['confirmed']
