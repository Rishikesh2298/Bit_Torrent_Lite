"""Faults injected into real processes; preserve all logs and partial stores."""
import socket
import time
import pytest
from .support import Swarm, wait_for

pytestmark = pytest.mark.timeout(180)


def test_free_rider_stays_disabled_after_completion_and_no_false_complete(tmp_path):
    with Swarm(tmp_path) as swarm:
        swarm.start_tracker()
        swarm.start_peer('z-seed', seed=True)
        swarm.start_peer('b-free', free_rider=True)
        swarm.complete('b-free')
        swarm.stop_peer('z-seed')
        swarm.source.rename(swarm.source.with_suffix('.offline'))
        late = swarm.start_peer('a-late')
        wait_for(lambda: swarm.has_event(late, 'CONNECTED'))
        time.sleep(6)  # cross an upload rotation interval after completion
        assert not swarm.has_event(late, 'COMPLETE')
        assert not list((swarm.root / 'downloads/a-late/pieces').rglob('*.piece'))
        assert swarm.stop_peer('b-free')['uploaded_payload_bytes'] == 0
        # Y03: after the final advertised provider leaves, missing data must
        # become an explicit stall. A connected free rider still advertises
        # its pieces, so the preceding no-upload interval alone is not Y03.
        provider_lost_at = time.monotonic()
        wait_for(lambda: any(
            row.get('event') == 'STATUS' and row.get('at', 0) >= provider_lost_at
            and row.get('state') == 'STALLED' and row.get('connected_peers') == 0
            and row.get('pending_requests') == 0 and row['owned'] < row['total']
            for row in swarm.events(late)), 15)
        assert not swarm.has_event(late, 'COMPLETE')
        assert not (swarm.root / 'downloads/a-late' / swarm.source.name).exists()
        assert not list((swarm.root / 'downloads/a-late/pieces').rglob('*.piece'))
        assert swarm.stop_peer('a-late')['verified_download_bytes'] == 0


def test_tracker_outage_does_not_stop_transfer_and_restart_admits_late_peer(tmp_path):
    with Swarm(tmp_path, 65536 * 128 + 17) as swarm:
        swarm.start_tracker()
        swarm.start_peer('z-seed', seed=True)
        peer = swarm.start_peer('b-first')
        wait_for(lambda: len(list((swarm.root / 'downloads/b-first/pieces').rglob('*.piece'))) >= 4)
        owned_before_loss = len(list((swarm.root / 'downloads/b-first/pieces').rglob('*.piece')))
        assert 0 < owned_before_loss < (swarm.size + 65535) // 65536
        assert not swarm.has_event(peer, 'COMPLETE'), 'transfer finished before tracker-loss injection'
        swarm.kill(swarm.tracker)
        tracker_lost_at = time.monotonic()
        wait_for(lambda: swarm.has_event(peer, 'TRACKER_ERROR'), 20)
        # Y04 requires actual progress after the tracker has exited, not just
        # an already completed output that remains readable during the outage.
        wait_for(lambda: any(
            row.get('event') == 'PROGRESS' and row.get('at', 0) >= tracker_lost_at
            and row['pieces'] > owned_before_loss
            for row in swarm.events(peer)), 20)
        swarm.complete('b-first', 60)
        assert next(row for row in swarm.events(peer)
                    if row.get('event') == 'COMPLETE')['at'] >= tracker_lost_at
        swarm.start_tracker()
        swarm.start_peer('a-late')
        swarm.complete('a-late', 60)
        assert swarm.stop_peer('a-late')['verified_download_bytes'] == swarm.size


def test_killed_downloader_restarts_from_verified_pieces(tmp_path):
    with Swarm(tmp_path, 65536 * 128 + 31) as swarm:
        swarm.start_tracker()
        swarm.start_peer('z-seed', seed=True)
        peer = swarm.start_peer('a-peer')
        pieces = swarm.root / 'downloads/a-peer/pieces'
        wait_for(lambda: len(list(pieces.rglob('*.piece'))) >= 4)
        swarm.kill(peer)
        stored = sum(p.stat().st_size for p in pieces.rglob('*.piece'))
        assert 0 < stored < swarm.size
        swarm.start_peer('a-peer', port=peer['port'])
        swarm.complete('a-peer', 80)
        assert swarm.stop_peer('a-peer')['verified_download_bytes'] == swarm.size - stored


def test_malformed_client_does_not_damage_healthy_transfer(tmp_path):
    with Swarm(tmp_path) as swarm:
        swarm.start_tracker()
        seed = swarm.start_peer('z-seed', seed=True)
        with socket.create_connection(('127.0.0.1', seed['port'])) as bad:
            bad.sendall(b'\xff\xff\xff\xff')
            bad.settimeout(2)
            # The server can send its handshake before observing the bad prefix.
            try:
                while bad.recv(65536):
                    pass
            except ConnectionResetError:
                pass
        swarm.start_peer('a-peer')
        swarm.complete('a-peer')


def test_tracker_absent_at_start_recovers(tmp_path):
    with Swarm(tmp_path) as swarm:
        seed = swarm.start_peer('z-seed', seed=True)
        peer = swarm.start_peer('a-peer')
        wait_for(lambda: swarm.has_event(peer, 'TRACKER_ERROR'))
        assert not swarm.has_event(peer, 'COMPLETE')
        swarm.start_tracker()
        swarm.complete('a-peer')
