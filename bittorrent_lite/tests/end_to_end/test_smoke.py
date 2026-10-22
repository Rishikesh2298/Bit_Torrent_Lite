import pytest
from .support import Swarm

pytestmark = pytest.mark.timeout(120)


@pytest.mark.parametrize('size', [1, 65536, 65536 * 8 + 123])
def test_real_cli_transfer_and_graceful_shutdown(tmp_path, size):
    with Swarm(tmp_path / 'portable run with spaces', size) as swarm:
        swarm.start_tracker()
        swarm.start_peer('z-seed', seed=True)
        swarm.start_peer('a-peer')
        swarm.complete('a-peer')
        peer = swarm.stop_peer('a-peer')
        seed = swarm.stop_peer('z-seed')
        assert peer['verified_download_bytes'] == size
        assert seed['uploaded_payload_bytes'] == size
        assert peer['owned'] == peer['total']
