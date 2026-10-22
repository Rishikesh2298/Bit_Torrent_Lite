"""Original R06/R08: bad TCP payload rejected, healthy alternate supplies it."""
import hashlib
import json

import pytest

from .support import Swarm, free_port, wait_for

pytestmark = pytest.mark.timeout(180)


def start_corrupt_seeder(swarm):
    name, port = 'z-corrupt', free_port()
    stop = swarm.root / f'{len(swarm.children):02d}-{name}.stop'
    trace = swarm.root / 'corrupt-seeder-trace.jsonl'
    child = swarm.launch(name, [
        'bittorrent_lite.tests.end_to_end.corrupt_seeder',
        '--fault-trace', str(trace), '--peer-id', name, '--host', '127.0.0.1',
        '--port', str(port), '--tracker', f'http://127.0.0.1:{swarm.tracker_port}',
        '--metadata', str(swarm.meta), '--output-dir', str(swarm.root / 'downloads'),
        '--stop-file', str(stop), '--seeder', '--file', str(swarm.source),
        '--window', '1', '--seed', '42', '--upload-workers', '0'], stop_file=stop)
    child.update(stop=stop, port=port)
    swarm.peers[name] = child  # Existing owned peer teardown applies on failure.
    wait_for(lambda: swarm.has_event(child, 'START'), 10)
    swarm._capture_interpreter(child)
    return child, trace


def test_corrupt_payload_is_not_owned_or_announced_then_recovers_from_healthy_peer(tmp_path):
    with Swarm(tmp_path / 'live corruption', 65536) as swarm:
        original = swarm.source.read_bytes()
        original_metadata = swarm.meta.read_bytes()
        swarm.start_tracker()
        corrupt, trace = start_corrupt_seeder(swarm)
        peer = swarm.start_peer('a-peer', window=1)
        wait_for(lambda: any(
            row.get('event') == 'PIECE_VERIFICATION'
            and row.get('outcome') == 'hash_mismatch'
            and row.get('remote') == 'z-corrupt'
            for row in swarm.events(peer)), 25)

        # No healthy source exists yet: a hash failure cannot become ownership,
        # a HAVE advertisement, verified-byte credit, or a completed output.
        rejected = [row for row in swarm.events(peer)
                    if row.get('event') == 'PIECE_VERIFICATION']
        assert rejected and all(row['outcome'] == 'hash_mismatch' for row in rejected)
        assert all(row['piece'] == 0 and row['bytes'] == 65536 for row in rejected)
        assert not [row for row in swarm.events(peer) if row.get('event') == 'PIECE_VERIFIED']
        assert not [row for row in swarm.structured_events(peer)
                    if row['event'] == 'frame_sent' and row.get('message_type') == 'HAVE']
        assert not list((swarm.root / 'downloads/a-peer/pieces').rglob('*.piece'))
        assert not (swarm.root / 'downloads/a-peer' / swarm.source.name).exists()
        assert not swarm.has_event(peer, 'COMPLETE')

        swarm.start_peer('y-healthy', seed=True)
        output = swarm.complete('a-peer', 60)
        assert output.read_bytes() == original
        assert swarm.stop_peer('a-peer')['verified_download_bytes'] == 65536
        assert swarm.stop_peer('z-corrupt')['uploaded_payload_bytes'] >= 65536
        assert swarm.stop_peer('y-healthy')['uploaded_payload_bytes'] >= 65536
        assert swarm.source.read_bytes() == original
        assert swarm.meta.read_bytes() == original_metadata

        verified = [row for row in swarm.events(peer) if row.get('event') == 'PIECE_VERIFIED']
        assert len(verified) == 1
        assert (verified[0]['remote'], verified[0]['piece'], verified[0]['bytes']) == ('y-healthy', 0, 65536)
        assert any(row['at'] < verified[0]['at'] for row in rejected)
        assert any(row['event'] == 'frame_sent' and row.get('message_type') == 'HAVE'
                   for row in swarm.structured_events(peer))

        rows = [json.loads(line) for line in trace.read_text(encoding='utf-8').splitlines()]
        assert rows[0]['event'] == 'trace_started' and rows[-1]['event'] == 'trace_closed'
        assert [row['sequence'] for row in rows] == list(range(len(rows)))
        assert rows[0]['pid'] == corrupt['interpreter']['pid']
        assert not any(row['event'] == 'fault_process_deadline' for row in rows)
        sent = [row for row in rows if row['event'] == 'corrupt_payload_sent']
        assert sent
        for row in sent:
            payload = bytes.fromhex(row['data_hex'])
            assert row['byte_count'] == len(payload) == len(original)
            assert row['original_sha256'] == hashlib.sha256(original).hexdigest()
            assert row['sha256'] == hashlib.sha256(payload).hexdigest()
            assert payload == bytes((original[0] ^ 1,)) + original[1:]
        assert any((row['request_id'], row['piece']) == (failure['request_id'], failure['piece'])
                   for row in sent for failure in rejected)
