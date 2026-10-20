"""Tracker-state contracts using real storage, threads and a controlled clock."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from bittorrent_lite.tracker import tracker_state


@pytest.fixture
def state(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(tracker_state, 'time',
                        SimpleNamespace(monotonic=lambda: clock[0]))
    return tracker_state.TrackerState(), clock


def peers(state):
    return {p.peer_id: (p.ip, p.port) for p in state.get_peer_list()}


class TestTrackerState:
    def test_register_peer(self, state):
        tracker, _ = state
        tracker.register_peer('a', '127.0.0.1', 9001)
        assert peers(tracker) == {'a': ('127.0.0.1', 9001)}

    def test_get_peers_excludes_self(self, state):
        tracker, _ = state
        tracker.register_peer('a', '127.0.0.1', 9001)
        tracker.register_peer('b', '127.0.0.2', 9002)
        assert [p.peer_id for p in tracker.get_peer_list(exclude_peer_id='a')] == ['b']
        assert len(tracker.get_peer_list()) == 2

    def test_remove_stale_peers(self, state):
        tracker, clock = state
        tracker.register_peer('old', '127.0.0.1', 9001)
        clock[0] = 110
        tracker.register_peer('fresh', '127.0.0.2', 9002)
        clock[0] = 121
        assert tracker.remove_stale_peers(20) == ['old']
        assert set(peers(tracker)) == {'fresh'}

    def test_update_refreshes_timestamp(self, state):
        tracker, clock = state
        tracker.register_peer('a', '127.0.0.1', 9001)
        clock[0] = 119
        tracker.update_peer('a')
        clock[0] = 121
        assert tracker.remove_stale_peers(20) == []
        clock[0] = 140
        assert tracker.remove_stale_peers(20) == ['a']

    def test_remove_peer_explicit(self, state):
        tracker, _ = state
        tracker.register_peer('a', '127.0.0.1', 9001)
        tracker.remove_peer('a')
        tracker.remove_peer('a')
        assert tracker.get_peer_list() == []

    def test_peer_count(self, state):
        tracker, _ = state
        assert tracker.peer_count() == 0
        tracker.register_peer('a', '127.0.0.1', 9001)
        tracker.register_peer('a', '127.0.0.2', 9002)
        assert tracker.peer_count() == 1
        assert peers(tracker)['a'] == ('127.0.0.2', 9002)
        tracker.remove_peer('a')
        assert tracker.peer_count() == 0

    def test_concurrent_registration(self, state):
        tracker, _ = state
        def register(i):
            tracker.register_peer(f'peer-{i}', '127.0.0.1', 9000 + i)
            tracker.get_peer_list()
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(register, range(100)))
        assert tracker.peer_count() == 100
        assert set(peers(tracker)) == {f'peer-{i}' for i in range(100)}

    def test_unknown_heartbeat_does_not_register_peer(self, state):
        tracker, _ = state
        with pytest.raises(KeyError):
            tracker.update_peer('missing')
        assert tracker.peer_count() == 0

    def test_reannounce_refreshes_endpoint_and_expiry(self, state):
        tracker, clock = state
        tracker.register_peer('a', '127.0.0.1', 9001)
        clock[0] = 119
        tracker.register_peer('a', '127.0.0.2', 9002)
        clock[0] = 139
        assert tracker.remove_stale_peers(20) == []
        assert peers(tracker) == {'a': ('127.0.0.2', 9002)}
        clock[0] = 139.001
        assert tracker.remove_stale_peers(20) == ['a']
        assert tracker.remove_stale_peers(20) == []

    def test_peer_list_is_detached_snapshot(self, state):
        tracker, _ = state
        tracker.register_peer('a', '127.0.0.1', 9001)
        snapshot = tracker.get_peer_list()
        snapshot[0].ip = 'changed'
        snapshot.clear()
        assert peers(tracker) == {'a': ('127.0.0.1', 9001)}

    def test_concurrent_membership_updates(self, state):
        tracker, _ = state

        def lifecycle(i):
            peer_id = f'peer-{i}'
            tracker.register_peer(peer_id, '127.0.0.1', 9000 + i)
            tracker.update_peer(peer_id)
            tracker.remove_stale_peers(20)
            tracker.get_peer_list(exclude_peer_id=peer_id)
            if i % 2 == 0:
                tracker.remove_peer(peer_id)
            tracker.peer_count()

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lifecycle, range(100)))
        assert set(peers(tracker)) == {f'peer-{i}' for i in range(1, 100, 2)}

    @pytest.mark.parametrize("timeout", [-1, True, float('nan'), float('inf'), '20', None])
    def test_invalid_expiry_timeout_preserves_membership(self, state, timeout):
        tracker, _ = state
        tracker.register_peer('a', '127.0.0.1', 9001)
        with pytest.raises(ValueError):
            tracker.remove_stale_peers(timeout)
        assert peers(tracker) == {'a': ('127.0.0.1', 9001)}
