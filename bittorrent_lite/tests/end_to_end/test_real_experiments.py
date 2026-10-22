"""Use Debargha's existing launcher/collector with real peers, not stand-ins."""
from pathlib import Path
import random
import pytest

from bittorrent_lite.common.paths import project_root
from bittorrent_lite.common.run_log import read_events
from bittorrent_lite.experiments.scripts.launcher import Run, load_config, port_is_free
from bittorrent_lite.experiments.scripts.collect import collect
from .support import Swarm

pytestmark = pytest.mark.timeout(120)


@pytest.mark.parametrize('scenario', ['baseline', 'free_rider', 'failure'])
def test_existing_experiment_harness_with_real_backend(tmp_path, scenario):
    fixture = Swarm(tmp_path / 'fixture', 65536 * 48 + 11)
    config = load_config(str(project_root() / 'bittorrent_lite/experiments/configs/base.json'))
    rng = random.Random()
    for _ in range(200):
        base = rng.randrange(20000, 50000)
        if all(port_is_free('127.0.0.1', base + n) for n in range(5)):
            break
    else:
        raise AssertionError('no free port block')
    config.update(fixture=str(fixture.source), metadata=str(fixture.meta),
                  L=3, S=1, scenario=scenario, tracker_port=base, base_port=base + 1,
                  timeout_s=70, name='real-' + scenario)
    manifest = Run(config, tmp_path / 'runs').execute()
    assert manifest['status'] == 'ok', manifest['failure_reason']
    assert manifest['environment']['label'] == 'localhost'
    assert not manifest['config']['synthetic']
    expected = ['peer-01', 'peer-02'] if scenario == 'failure' else ['peer-01', 'peer-02', 'peer-03']
    assert all(manifest['output_hash_ok'][p] is True for p in expected)
    assert all(p['exit_code'] == 0 for p in manifest['processes']
               if p['role'] != 'tracker' and not p['killed_by_harness'])
    run_dir = tmp_path / 'runs' / manifest['run_id']
    assert all(not event.get('synthetic', False) for path in (run_dir / 'events').glob('*.jsonl')
               for event in read_events(str(path)))
    runs, peers, problems = collect(tmp_path / 'runs', tmp_path / 'results')
    assert problems == []
    assert runs[0]['status'] == 'ok'
    assert all(row['verified_download_bytes'] == fixture.size for row in peers if row['peer_id'] in expected)
    if scenario == 'free_rider':
        assert next(p for p in peers if p['peer_id'] == 'peer-03')['uploaded_payload_bytes'] == 0
    if scenario == 'failure':
        assert manifest['trigger']['target'] == 'peer-03'
        assert manifest['trigger']['progress_pct'] >= 25
