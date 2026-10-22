"""Real five-interpreter coverage participation; preparation evidence only.

The recorded worker uses a real tracker, seeder and downloader. Its expected
interpreter population comes from live OS identities and the separate process
registry/readiness records, never from coverage starts. No process is launched
on import. The parent pytest interpreter is outside this nested coverage root.
"""
from __future__ import annotations

import argparse
import ast
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import signal
import sys
import time
import traceback
import uuid

from bittorrent_lite.acceptance_tools import coverage_support, recording
from bittorrent_lite.acceptance_tools.evidence import strict_json, verify_metadata
from bittorrent_lite.acceptance_tools.inventory import (
    compare_snapshots, digest_file, snapshot, source_files, write_json_new,
)
from bittorrent_lite.tests.end_to_end.support import Swarm


REPO = Path(__file__).resolve().parents[3]
CASE_ID = 'real-five-interpreter-coverage'
IDENTITY_FIELDS = ('pid', 'creation_time', 'executable', 'arguments', 'parent_pid')


def _key(identity):
    return (identity['pid'], identity['creation_time'],
            os.path.normcase(str(Path(identity['executable']).resolve())))


def _complete_json(path, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            raw = path.read_bytes()
            if raw.endswith(b'\n'):
                return strict_json(raw)
        time.sleep(.01)
    raise AssertionError(f'complete evidence did not arrive: {path}')


def _first_ready(path, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            first, separator, _ = path.read_bytes().partition(b'\n')
            if separator:
                event = strict_json(first)
                assert event['action'] == 'guardian_ready'
                return event
        time.sleep(.01)
    raise AssertionError('guardian readiness was not recorded')


def _live_chain(actual, supervisor, *, expected_launcher=None):
    """Observe ancestry while alive; classify venv redirectors without coverage."""
    process = recording.matching_process(actual)
    assert process is not None, 'expected interpreter already disappeared'
    reverse = []
    for _ in range(8):
        identity = recording.process_identity(process.pid)
        if not reverse:
            assert all(identity[k] == actual[k] for k in IDENTITY_FIELDS)
        reverse.append(identity)
        if identity['parent_pid'] == supervisor['pid']:
            break
        process = process.parent()
        assert process is not None, 'owned ancestry disappeared'
    else:
        raise AssertionError('owned ancestry exceeds finite bound')
    assert recording.matching_process(supervisor) is not None
    chain = list(reversed(reverse))
    if expected_launcher is not None:
        assert all(chain[0][k] == expected_launcher[k] for k in IDENTITY_FIELDS)
    native = []
    if len(chain) > 1:
        assert os.name == 'nt' and len(chain) == 2, 'unclassified interpreter ancestry'
        wrapper = chain[0]
        assert (Path(sys.prefix) / 'pyvenv.cfg').is_file()
        assert Path(wrapper['executable']).resolve() == Path(sys.executable).resolve()
        assert wrapper['arguments'][1:] == actual['arguments'][1:]
        assert _key(wrapper) != _key(actual)
        native.append({'identity': wrapper, 'classification': 'native-Windows-venv-redirector',
                       'executable_sha256': digest_file(Path(wrapper['executable'])),
                       'basis': 'live parent ancestry, venv executable/config and exact argv tail; not coverage absence'})
    return {'actual': actual, 'chain': chain, 'native_redirectors': native,
            'observed_at_monotonic': time.monotonic()}


def _register_expected(root, identity, role):
    registered = recording.register_process(root / 'expected-interpreters', identity['pid'],
        owner_run=CASE_ID, role=role, expected_identity=identity)
    return {**registered, 'case_id': CASE_ID, 'coverage_role': role}


def _worker(root):
    root = root.resolve(strict=True)
    try:
        registry = Path(os.environ['ACCEPTANCE_PROCESS_REGISTRY']).resolve(strict=True)
        command = registry.parent
        supervisor = _complete_json(command / 'supervisor.json')
        launched = _complete_json(command / 'launched.json')['process']
        actual = recording.process_identity(os.getpid())
        worker_chain = _live_chain(actual, supervisor, expected_launcher=launched)
        # The recorder registered its Popen PID immediately. Register the actual
        # interpreter too if a native redirector sits between it and the parent.
        if _key(actual) != _key(launched):
            recording.register_process(registry, actual['pid'], owner_run=CASE_ID,
                                       role='coverage-worker-interpreter', expected_identity=actual)
        guardian_ready = _first_ready(command / 'guardian.jsonl')
        guardian_actual = recording.process_identity(guardian_ready['identity']['pid'])
        assert all(guardian_actual[k] == guardian_ready['identity'][k] for k in IDENTITY_FIELDS)
        guardian_chain = _live_chain(guardian_actual, supervisor)
        expected = [_register_expected(root, actual, 'worker'),
                    _register_expected(root, guardian_actual, 'guardian')]
        write_json_new(root / 'supervisor-observations.json', {
            'worker': worker_chain, 'guardian': guardian_chain,
            'guardian_ready': guardian_ready, 'parent_supervisor': supervisor})
        declaration_path = root / 'tracker-termination-plan.json'
        # Written before even constructing Swarm and therefore before the
        # tracker interpreter's startup coverage hook can run.
        write_json_new(declaration_path, {
            'schema': 'btl-coverage-termination-plan-v1', 'case_id': CASE_ID,
            'process_role': 'tracker', 'declared_at_monotonic': time.monotonic(),
            'termination_kind': 'forced', 'api': 'psutil.Process.kill',
            'expected_exit_codes': [15 if os.name == 'nt' else -signal.SIGKILL],
            'reason': 'tracker-only abrupt coverage negative control after both peers stop normally',
            'coverage_outcome': 'INTERRUPTED_NOT_COUNTED'})
        with Swarm(root / 'swarm', size=65536 * 4 + 137, fixture_seed=729) as swarm:
            assert swarm.process_supervision['registry_mode'] == 'inherited'
            swarm.start_tracker()
            seed = swarm.start_peer('seed', seed=True)
            downloader = swarm.start_peer('downloader')
            for role, child in [('tracker', swarm.tracker), ('seeder', seed), ('downloader', downloader)]:
                observed = child['interpreter_observation']
                assert observed['method'] == 'live-owned-tree-argv-environment'
                assert recording.matching_process(observed['identity']) is not None
                assert child['interpreter'] == observed['identity']
                expected.append(_register_expected(root, observed['identity'], role))
            write_json_new(root / 'expected-population.json', {
                'method': 'live OS identity/ancestry, process registry and guardian readiness; no coverage records read',
                'expected_interpreters': expected, 'roles': ['worker', 'guardian', 'tracker', 'seeder', 'downloader']})
            output = swarm.complete('downloader', timeout=35)
            verified = verify_metadata(swarm.source, swarm.meta)
            assert output.stat().st_size == verified['size'] == swarm.size
            assert digest_file(output) == verified['sha256'] == swarm.digest
            assert output.read_bytes() == swarm.source.read_bytes()
            swarm.stop_peer('downloader')
            swarm.stop_peer('seed')
            swarm.kill(swarm.tracker)
            tracker = swarm.tracker
            code = tracker['interpreter_exit_code']
            assert type(code) is int and code == tracker['proc'].returncode
            declaration = strict_json(declaration_path.read_bytes())
            assert code in declaration['expected_exit_codes']
            assert tracker['termination_contract']['api'] == declaration['api']
            write_json_new(root / 'tracker-termination-observation.json', {
                'schema': 'btl-coverage-termination-observation-v1', 'case_id': CASE_ID,
                'process_role': 'tracker', 'termination_kind': 'forced',
                'identity': tracker['interpreter'], 'exit_confirmed': True, 'exit_code': code,
                'observed_at_monotonic': time.monotonic(),
                'method': 'Swarm._wait_owned_exit actual interpreter and Popen wrapper statuses agree',
                'wrapper_exit_code': tracker['proc'].returncode,
                'termination_contract': tracker['termination_contract']})
        # Context exit independently checks all strict events and ordinary exits.
        results = strict_json((swarm.root / 'results.json').read_bytes())
        assert results['cleanup_errors'] == []
        assert all(row['interpreter_exit_code'] == row['exit_code'] == 0
                   for row in results['processes'] if row['name'] != 'tracker')
        write_json_new(root / 'worker-result.json', {
            'status': 'VERIFIED_DIAGNOSTIC', 'source': str(swarm.source), 'output': str(output),
            'source_sha256': digest_file(swarm.source), 'output_sha256': digest_file(output),
            'size': output.stat().st_size, 'source_isolation_claimed': False,
            'acceptance_credit': False, 'external_verification_claimed': False})
    except BaseException:
        (root / 'worker-failure-traceback.txt').write_text(traceback.format_exc(), encoding='utf-8')
        raise


def _assert_executed_function(entry, path, name):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    candidates = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and n.name == name]
    assert len(candidates) == 1, f'ambiguous behavioral coverage anchor: {path}:{name}'
    function = candidates[0]
    body = {node.lineno for statement in function.body for node in ast.walk(statement)
            if isinstance(node, ast.stmt)}
    matched = [name for name in entry['executed_lines']
               if os.path.normcase(str(Path(name).resolve())) == os.path.normcase(str(path.resolve()))]
    assert len(matched) == 1, f'behavioral source missing/ambiguous: {path}'
    lines = entry['executed_lines'][matched[0]]
    arcs = entry['executed_arcs'][matched[0]]
    assert body.intersection(lines), f'no executed function-body lines: {path}:{name}'
    assert any(start in body or end in body for start, end in arcs), f'no real function arcs: {path}:{name}'


def _negative_controls(root, options, original_rows):
    """Mutate only named copies; never alter the measured positive corpus."""
    import pytest
    actual_hashes = {p.name: digest_file(p) for p in root.iterdir()}
    normal = next(row for row in original_rows if row['status'] == 'FLUSHED')
    controls = root.parent / 'negative-controls'
    controls.mkdir()
    missing = controls / 'missing-finish'
    shutil.copytree(root, missing)
    tag = normal['data_file'].removeprefix('.coverage.')
    (missing / f'{tag}.finish.json').rename(controls / 'retained-missing-finish.json')
    with pytest.raises(ValueError, match='did not flush'):
        coverage_support.inspect_participation(missing, **options)
    removed = next(row for row in options['expected_processes'] if row['coverage_role'] == 'seeder')
    with pytest.raises(ValueError, match='unexpected/duplicate coverage identity'):
        coverage_support.inspect_participation(root, **{
            **options, 'expected_processes': [r for r in options['expected_processes'] if r is not removed]})
    with pytest.raises(ValueError, match='duplicate expected interpreter identity'):
        coverage_support.inspect_participation(root, **{
            **options, 'expected_processes': [*options['expected_processes'], removed]})
    duplicate = controls / 'duplicate-start'
    shutil.copytree(root, duplicate)
    start = strict_json((duplicate / f'{tag}.start.json').read_bytes())
    extra_tag = f"{start['pid']}-{uuid.uuid4().hex}"
    duplicate_name = '.coverage.' + extra_tag
    write_json_new(duplicate / f'{extra_tag}.start.json', {**start, 'data_file': duplicate_name})
    finish = strict_json((duplicate / f'{tag}.finish.json').read_bytes())
    write_json_new(duplicate / f'{extra_tag}.finish.json', {**finish, 'data_file': duplicate_name})
    shutil.copyfile(duplicate / start['data_file'], duplicate / duplicate_name)
    with pytest.raises(ValueError, match='duplicate coverage identity'):
        # Both copied pairs are internally complete; rejection must specifically
        # identify duplicate process participation, regardless of tag ordering.
        coverage_support.inspect_participation(duplicate, **options)
    assert {p.name: digest_file(p) for p in root.iterdir()} == actual_hashes
    write_json_new(controls / 'control-results.json', {
        'scope': 'intentional verifier controls using retained copies/altered expected population',
        'positive_corpus_unchanged': True, 'missing_flush_rejected': True,
        'unregistered_coverage_rejected': True, 'duplicate_expected_identity_rejected': True,
        'duplicate_start_rejected': True, 'acceptance_credit': False})


def test_real_worker_guardian_tracker_and_peer_coverage_participation(tmp_path):
    before = snapshot(REPO)
    outer = os.environ.get('ACCEPTANCE_PROCESS_REGISTRY')
    parent = Path(outer).resolve(strict=True).parent if outer else tmp_path
    root = parent / ('coverage-lifecycle-' + uuid.uuid4().hex)
    root.mkdir(exist_ok=False)
    coverage_root = root / 'coverage'
    coverage_root.mkdir()
    config = root / 'coverage.ini'
    config_record = coverage_support.write_config(config, REPO / 'bittorrent_lite')
    sites = [Path(sys.prefix) / 'Lib/site-packages'] if os.name == 'nt' else list(Path(sys.prefix).glob('lib/python*/site-packages'))
    assert len(sites) == 1
    hook = sites[0] / coverage_support.HOOK_NAME
    assert hook.read_text(encoding='utf-8') == coverage_support.HOOK, 'required .pth hook missing or changed'
    source_inventory = {str(path): digest_file(path) for path in source_files(REPO)
                        if path.suffix == '.py' and path.is_relative_to(REPO / 'bittorrent_lite')
                        and 'tests' not in path.relative_to(REPO).parts}
    write_json_new(root / 'inputs-before.json', {
        'source_snapshot': before, 'source_inventory': source_inventory, 'config': config_record,
        'hook': {'path': str(hook), 'sha256': digest_file(hook)},
        'coverage_version': importlib.metadata.version('coverage'),
        'python_executable': sys.executable, 'python_executable_sha256': digest_file(Path(sys.executable)),
        'scope': 'PREPARE diagnostic; parent pytest belongs to its own outer campaign coverage'})
    environment = dict(os.environ)
    for name in ('BTL_EVENT_LOG', 'BTL_PROC_ID', 'BTL_RUN_ID', 'BTL_LOG_STRICT', 'PYTHONPATH', 'COVERAGE_FILE'):
        environment.pop(name, None)
    environment.update(BTL_COVERAGE_ROOT=str(coverage_root), COVERAGE_PROCESS_START=str(config),
                       PYTHONIOENCODING='utf-8', PYTHONUTF8='1', PYTHONUNBUFFERED='1')
    recorder = recording.RecordingSession(root / 'recorded', 'preparation', 'coverage-lifecycle',
        {'source': before['sha256'], 'config': config_record['sha256'], 'hook': digest_file(hook)})
    record = recorder.run('worker', [sys.executable, str(Path(__file__).resolve()), '--worker', str(root)],
        cwd=root, env=environment, timeout_s=85, expected_exit_codes=(0,),
        oracle='real 1S/1L exact-output transfer; five independently observed interpreter identities; tracker-only predeclared abrupt interruption; all normal branch coverage flushes; no acceptance credit')
    assert record['status'] == 'PASS' and record['exit_code'] == 0
    assert record['timed_out'] is False and record['cleanup_errors'] == []
    command = recorder.root / 'worker'
    guardian_result = strict_json((command / 'guardian-result.json').read_bytes())
    assert guardian_result['errors'] == [] and guardian_result['alive_before_cleanup'] == []
    observed = strict_json((root / 'supervisor-observations.json').read_bytes())
    assert _key(observed['worker']['chain'][0]) == _key(record['process'])
    assert _key(observed['guardian']['chain'][0]) == _key(record['guardian'])
    population = strict_json((root / 'expected-population.json').read_bytes())
    expected = population['expected_interpreters']
    assert len(expected) == 5 and {r['coverage_role'] for r in expected} == set(population['roles'])
    identity_records = [strict_json(p.read_bytes()) for p in (root / 'expected-interpreters').glob('*.json')]
    assert len(identity_records) == 5 and {_key(r) for r in identity_records} == {_key(r) for r in expected}
    inner_records = [strict_json(p.read_bytes()) for p in (command / 'processes').glob('*.json')]
    assert {_key(r) for r in expected if r['coverage_role'] != 'guardian'} <= {_key(r) for r in inner_records}
    launches = strict_json((root / 'swarm/launches.json').read_bytes())
    assert {row['name'] for row in launches} == {'tracker', 'seed', 'downloader'}
    wrappers = [r['identity'] for kind in ('worker', 'guardian') for r in observed[kind]['native_redirectors']]
    for launch in launches:
        observation = launch['interpreter_observation']
        assert observation['method'] == 'live-owned-tree-argv-environment'
        assert _key(observation['identity']) in {_key(r) for r in expected}
        chain = observation['ancestry']
        if len(chain) > 1:
            assert os.name == 'nt' and len(chain) == 2
            assert Path(chain[0]['executable']).resolve() == Path(sys.executable).resolve()
            assert chain[0]['arguments'][1:] == chain[-1]['arguments'][1:]
            wrappers.append(chain[0])
    all_owned = [*inner_records, *identity_records, *guardian_result['identities'],
                 *observed['guardian']['chain']]
    assert all(recording.matching_process(row) is None for row in all_owned), 'owned process survived'
    tracker = next(row for row in expected if row['coverage_role'] == 'tracker')
    termination = {'identity': tracker}
    for name, filename in [('declaration', 'tracker-termination-plan.json'),
                           ('observation', 'tracker-termination-observation.json')]:
        path = root / filename
        termination[name] = {'path': str(path), 'sha256': digest_file(path)}
    options = {'expected_processes': expected, 'config': config,
               'config_sha256': config_record['sha256'], 'expected_sources': source_inventory,
               'coverage_version': importlib.metadata.version('coverage'), 'expected_terminations': [termination]}
    rows = coverage_support.inspect_participation(coverage_root, **options)
    assert len(rows) == 5 and {_key(r) for r in rows} == {_key(r) for r in expected}
    by_role = {process['coverage_role']: next(r for r in rows if _key(r) == _key(process)) for process in expected}
    assert by_role['tracker']['status'] == 'INTERRUPTED_NOT_COUNTED'
    assert by_role['tracker']['executed_lines'] == by_role['tracker']['executed_arcs'] == {}
    assert all(by_role[role]['status'] == 'FLUSHED' for role in ('worker', 'guardian', 'seeder', 'downloader'))
    assert not {_key(r) for r in wrappers}.intersection(_key(r) for r in rows), 'native redirector counted as interpreter'
    _assert_executed_function(by_role['worker'], REPO / 'bittorrent_lite/storage/metadata.py', 'create_metadata')
    _assert_executed_function(by_role['guardian'], REPO / 'bittorrent_lite/acceptance_tools/recording.py', '_watch')
    for role in ('seeder', 'downloader'):
        _assert_executed_function(by_role[role], REPO / 'bittorrent_lite/application/runtime.py', 'step')
    result = strict_json((root / 'worker-result.json').read_bytes())
    assert result['status'] == 'VERIFIED_DIAGNOSTIC' and result['acceptance_credit'] is False
    source, output = Path(result['source']), Path(result['output'])
    assert source.read_bytes() == output.read_bytes()
    assert source.stat().st_size == output.stat().st_size == result['size']
    assert digest_file(source) == digest_file(output) == result['source_sha256'] == result['output_sha256']
    write_json_new(root / 'participation-verified.json', {'participants': rows,
        'native_redirectors': wrappers, 'acceptance_credit': False, 'full_branch_completeness_claimed': False,
        'external_verification_claimed': False, 'scope': 'real interpreter participation and selected body/arc anchors only'})
    _negative_controls(coverage_root, options, rows)
    compare_snapshots(before, snapshot(REPO))
    assert digest_file(hook) == strict_json((root / 'inputs-before.json').read_bytes())['hook']['sha256']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=Path, required=True)
    _worker(parser.parse_args().worker)
