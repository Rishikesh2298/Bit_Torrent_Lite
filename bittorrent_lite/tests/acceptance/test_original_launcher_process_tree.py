"""Actual process regression for the preserved launcher; no network credit."""
import json
import os
from pathlib import Path
import sys
import time

import pytest

from bittorrent_lite.acceptance_tools import recording
from bittorrent_lite.experiments.scripts.launcher import Child, Run
from bittorrent_lite.tests.acceptance.test_guardian_crash import NonChildExitObservation


WORKER = """
import json, os, sys, time
from pathlib import Path
ready, stop = map(Path, sys.argv[1:])
print('worker-ready', flush=True)
ready.write_text(json.dumps({'pid': os.getpid()}), encoding='utf-8')
deadline = time.monotonic() + 25
while not stop.exists():
    if time.monotonic() >= deadline:
        raise RuntimeError('finite owned fixture lifetime exceeded')
    time.sleep(.02)
print('worker-stopped', flush=True)
"""


@pytest.mark.timeout(40)
def test_original_launcher_kill_stops_actual_interpreter_and_preserves_control(tmp_path):
    run = Run({'name': 'actual-process-tree', 'repeat': 1}, tmp_path / 'runs')
    (run.dir / 'logs').mkdir(parents=True)
    (run.dir / 'events').mkdir()
    local = run.dir / 'test-owned-processes'
    owned = []
    observers = {}
    children = {}
    identities = {}
    try:
        for name in ('target', 'unrelated-control'):
            ready, stop = run.dir / (name + '.ready'), run.dir / (name + '.stop')
            child = Child(name, 'downloader', 0,
                          [sys.executable, '-c', WORKER, str(ready), str(stop)],
                          run.dir / 'events' / (name + '.jsonl'))
            run.children.append(child)
            children[name] = child
            run._start(child)
            launch = recording.process_identity(child.process.pid)
            owned.append(recording.register_process(local, child.process.pid,
                owner_run=run.run_id, role=name + '-launcher', stop_file=stop,
                expected_identity=launch))
            deadline = time.monotonic() + 5
            while not ready.is_file():
                assert child.process.poll() is None
                assert time.monotonic() < deadline, 'fixture startup deadline exceeded'
                time.sleep(.02)
            observed_pid = json.loads(ready.read_text(encoding='utf-8'))['pid']
            parent = recording.matching_process(launch)
            assert parent is not None
            tree = [parent, *parent.children(recursive=True)]
            observed = [recording.observed_child_identity(proc) for proc in tree]
            observed = [identity for identity in observed if identity is not None]
            actual, = [identity for identity in observed if identity['pid'] == observed_pid]
            assert actual['arguments'][1:] == child.command[1:]
            identities[name] = actual
            for identity in observed:
                if identity['pid'] != launch['pid']:
                    owned.append(recording.register_process(local, identity['pid'],
                        owner_run=run.run_id, role=name + '-descendant', stop_file=stop,
                        expected_identity=identity))
                outer = os.environ.get('ACCEPTANCE_PROCESS_REGISTRY')
                if outer:
                    recording.register_process(outer, identity['pid'], owner_run=run.run_id,
                        role=name + '-fixture', stop_file=stop, expected_identity=identity)
            observers[name] = NonChildExitObservation(actual)
        run.run_start = time.monotonic()
        recording._write_new(run.dir / 'expected-action.json', {
            'action': 'original Run._kill_target on target only',
            'target': identities['target'], 'control': identities['unrelated-control'],
            'expected': 'target actual interpreter exits; separate control stays alive',
            'at': recording._times()})
        run._kill_target(children['target'], 25.0)
        children['target'].process.wait(timeout=3)
        deadline = time.monotonic() + 2
        while recording.matching_process(identities['target']) is not None and time.monotonic() < deadline:
            time.sleep(.02)
        alive = recording.matching_process(identities['target']) is not None
        control_alive = recording.matching_process(identities['unrelated-control']) is not None
        recording._write_new(run.dir / 'actual-kill-observation.json', {
            'target_actual_still_alive': alive, 'control_actual_still_alive': control_alive,
            'target_launcher_exit': children['target'].process.returncode,
            'target_actual_exit': None if alive else observers['target'].wait(1),
            'at': recording._times(), 'network_credit': False})
        assert not alive, 'original launcher killed only the native wrapper; actual interpreter survived'
        assert control_alive, 'unrelated owned control was incorrectly stopped'
        assert not (run.dir / 'target.stop').exists(), 'cleanup masked the intended crash'
        assert (run.dir / 'logs/target.out').read_bytes().splitlines() == [b'worker-ready']
        assert (run.dir / 'logs/target.err').read_bytes() == b''
        assert children['target'].killed_by_harness
    finally:
        for name in children:
            (run.dir / (name + '.stop')).touch(exist_ok=True)
        for child in children.values():
            if child.process is not None:
                try:
                    child.process.wait(timeout=2)
                except Exception:
                    pass
        errors = recording.stop_owned(owned, run.dir / 'test-finally-cleanup.jsonl',
                                      grace_s=.3, terminate_s=.5)
        for child in children.values():
            if child.process is not None:
                child.process.wait(timeout=3)
            for stream in child.files:
                stream.close()
        for observer in observers.values():
            observer.close()
        assert not errors
        assert all(recording.matching_process(identity) is None for identity in owned)
