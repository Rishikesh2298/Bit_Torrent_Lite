"""Actual redistribution, concurrency and selection configurations over TCP."""
import pytest
from .support import Swarm

pytestmark = pytest.mark.timeout(180)


def test_downloaded_peer_is_only_source_for_late_joiner(tmp_path):
    with Swarm(tmp_path) as swarm:
        swarm.start_tracker()
        swarm.start_peer('z-seed', seed=True)
        swarm.start_peer('b-first')
        swarm.complete('b-first')
        swarm.stop_peer('z-seed')
        swarm.source.rename(swarm.source.with_suffix('.unavailable'))
        swarm.start_peer('a-late')
        swarm.complete('a-late')
        assert swarm.stop_peer('a-late')['verified_download_bytes'] == swarm.size
        assert swarm.stop_peer('b-first')['uploaded_payload_bytes'] == swarm.size


@pytest.mark.parametrize('seeders', [1, 2])
def test_six_downloaders_with_threaded_uploads(tmp_path, seeders):
    with Swarm(tmp_path, 65536 * 32 + 17) as swarm:
        swarm.start_tracker()
        for index in range(seeders):
            swarm.start_peer(f'z-seed-{index}', seed=True, workers=2)
        names = [f'a-peer-{index}' for index in range(6)]
        for name in names:
            swarm.start_peer(name, workers=2)
        for name in names:
            swarm.complete(name, 120)
        for name in names:
            result = swarm.stop_peer(name)
            assert result['verified_download_bytes'] == swarm.size


@pytest.mark.parametrize('repeat', range(3))
@pytest.mark.parametrize('strategy', ['sequential', 'random', 'rarest-first'])
@pytest.mark.parametrize('window', [1, 4])
def test_strategy_window_repeated(tmp_path, repeat, strategy, window):
    with Swarm(tmp_path, 65536 * 4 + 11) as swarm:
        swarm.start_tracker()
        swarm.start_peer('z-seed', seed=True)
        swarm.start_peer('a-peer', strategy=strategy, window=window)
        swarm.complete('a-peer')
        assert swarm.stop_peer('a-peer')['verified_download_bytes'] == swarm.size


def test_maximum_supported_64_mib_file(tmp_path):
    with Swarm(tmp_path, 64 * 1024 * 1024) as swarm:
        swarm.start_tracker()
        swarm.start_peer('z-seed', seed=True, workers=2)
        swarm.start_peer('a-peer', workers=2)
        swarm.complete('a-peer', 140)
        assert swarm.stop_peer('a-peer')['verified_download_bytes'] == swarm.size
