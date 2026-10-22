"""Isolated original-plan narrative oracles; these are not real-network tests."""
import hashlib
import random

import pytest

from bittorrent_lite.common import events as ev
from bittorrent_lite.examples.scheduler_dependencies import InMemoryStore, ManualClock, RecordingTransport
from bittorrent_lite.scheduling import Coordinator, SchedulerConfig
from bittorrent_lite.scheduling.recovery import RecoveryConfig, RecoveryPolicy
from bittorrent_lite.scheduling.upload_policy import ProjectUploadPolicy
from bittorrent_lite.scheduling.choking_policy import PeerInfo


def make_scheduler(count, strategy="rarest-first", window=1):
    pieces = [bytes((index, 0, 255, 128)) for index in range(count)]
    store = InMemoryStore([hashlib.sha256(piece).digest() for piece in pieces], 4)
    clock, transport = ManualClock(), RecordingTransport()
    config = SchedulerConfig(request_window=window, recovery=RecoveryConfig(
        strategy=strategy, endgame_enabled=False, max_copies=1))
    coordinator = Coordinator(count, transport, store, clock, config, rng=random.Random(1))
    return coordinator, transport, pieces


def advertise(coordinator, connection, bits):
    coordinator.handle_event(ev.ConnectionReady(connection, f"source-{connection}"))
    coordinator.handle_event(ev.BitfieldReceived(connection, bits))


def test_fixed_seed_reproduces_equal_rarity_tie_without_mutating_inputs():
    config = RecoveryConfig(strategy='rarest-first')
    first, second = RecoveryPolicy(6, config, seed=37), RecoveryPolicy(6, config, seed=37)
    candidates, availability = [5, 4, 3, 2, 1, 0], [2] * 6
    histories = [[], []]
    for now in range(4):
        for history, policy in zip(histories, (first, second)):
            result = policy.rank_candidates(now=now, provider='source-A',
                candidates=candidates, availability=availability)
            assert len(result) == 6 and set(result) == set(range(6))
            history.append(result)
    assert histories[0] == histories[1]
    assert candidates == [5, 4, 3, 2, 1, 0] and availability == [2] * 6
    # A fixed finite seed domain must expose genuine tie randomization.
    alternatives = {tuple(RecoveryPolicy(6, config, seed=seed).rank_candidates(
        now=0, provider='source-A', candidates=candidates, availability=availability))
        for seed in range(16)}
    assert len(alternatives) > 1


def test_interest_survives_reservation_on_another_connection():
    """NC02: REQUESTED remains useful; only local HAVE removes interest."""
    coordinator, transport, pieces = make_scheduler(1)
    advertise(coordinator, 1, [1])
    coordinator.handle_event(ev.UnchokeReceived(1))
    pending = coordinator.snapshot()["pending"][0]
    advertise(coordinator, 2, [1])
    coordinator.handle_event(ev.UnchokeReceived(2))
    for _ in range(3):
        coordinator.schedule()
    assert len(coordinator.snapshot()["pending"]) == 1
    assert all(row["am_interested"] for row in coordinator.snapshot()["neighbors"].values())
    assert [(row[0], row[1]) for row in transport.log if "INTERESTED" in row[0]] == [
        ("INTERESTED", 1), ("INTERESTED", 2)]
    coordinator.handle_event(ev.PieceReceived(1, pending["request_id"], 0, pieces[0]))
    assert coordinator.snapshot()["owned"] == 1
    assert all(not row["am_interested"] for row in coordinator.snapshot()["neighbors"].values())
    assert [row for row in transport.log if row[0] == "NOT_INTERESTED"] == [
        ("NOT_INTERESTED", 1), ("NOT_INTERESTED", 2)]
    coordinator.schedule()
    assert len([row for row in transport.log if row[0] == "NOT_INTERESTED"]) == 2


def test_choked_advertiser_changes_rarity_without_becoming_a_source():
    """NC03: source 2 increases piece 0 replication despite withholding permission."""
    coordinator, transport, _ = make_scheduler(2)
    advertise(coordinator, 1, [1, 1])
    advertise(coordinator, 2, [1, 0])
    assert coordinator.snapshot()["availability"] == [2, 1]
    coordinator.handle_event(ev.UnchokeReceived(1))
    assert [row for row in transport.log if row[0] == "REQUEST"] == [("REQUEST", 1, 1, 1)]
    assert coordinator.snapshot()["neighbors"][2]["peer_choking"]


@pytest.mark.parametrize("strategy", ["sequential", "random", "rarest-first"])
def test_strategies_share_source_permission_and_reservation_rules(strategy):
    coordinator, transport, _ = make_scheduler(3, strategy)
    advertise(coordinator, 1, [1, 1, 0])
    advertise(coordinator, 2, [0, 0, 1])
    coordinator.handle_event(ev.UnchokeReceived(1))
    pending = coordinator.snapshot()["pending"]
    assert len(pending) == 1
    assert pending[0]["connection_id"] == 1
    assert pending[0]["piece_index"] in (0, 1)
    assert coordinator.snapshot()["availability"] == [1, 1, 1]
    coordinator.schedule()
    assert len([row for row in transport.log if row[0] == "REQUEST"]) == 1


@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_project_policy_sparse_population_and_transition_only_controls(count):
    """NC07: fill min(2, interested) permissions, then fill a vacated slot."""
    policy = ProjectUploadPolicy()
    for index in range(count):
        policy.connect(PeerInfo(str(index), True), 0)
    decision = policy.tick(0)
    assert len(decision.intents) == min(2, count)
    assert all(intent.allow for intent in decision.intents)
    for intent in decision.intents:
        assert policy.acknowledge(intent.token, True, 0)
    assert policy.tick(0).intents == ()
    assert sum(peer.confirmed for peer in policy.snapshot(0).peers) == min(2, count)
    if count == 3:
        departing = decision.intents[0].peer_id
        waiting = next(peer.peer_id for peer in decision.state.peers if not peer.desired)
        policy.disconnect(departing, 1)
        replacement = policy.tick(1)
        assert [(intent.peer_id, intent.allow) for intent in replacement.intents] == [(waiting, True)]

