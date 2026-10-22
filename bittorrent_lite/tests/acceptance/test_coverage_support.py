"""Finite negative controls and genuine child-only branch coverage smoke."""
import ast
import json
import os
from pathlib import Path
import sys
from copy import deepcopy

import pytest

from bittorrent_lite.acceptance_tools.coverage_support import (
    HOOK_NAME, inspect_participation, install_hook, write_config,
)
from bittorrent_lite.acceptance_tools.recording import RecordingSession
from bittorrent_lite.acceptance_tools.inventory import digest_file, source_files, write_json_new
from bittorrent_lite.acceptance_tools import coverage_support


def coverage_fixture(tmp_path, *, flushed=True):
    """A verifier unit fixture, explicitly not measured application coverage."""
    import coverage
    source_dir = tmp_path / 'source'
    source_dir.mkdir()
    source = source_dir / 'subject.py'
    source.write_text('answer = 1\n', encoding='utf-8')
    config = tmp_path / 'coverage.ini'
    write_config(config, source_dir)
    root = tmp_path / 'coverage'
    root.mkdir()
    tag = '123-' + 'a' * 32
    identity = {'pid': 123, 'creation_time': 10.0, 'executable': sys.executable}
    start = {**identity, 'schema': 'btl-coverage-v2', 'parent_pid': 1,
             'python_executable': sys.executable, 'argv': ['verifier unit fixture'],
             'cwd': str(tmp_path), 'monotonic': 20.0, 'data_file': '.coverage.' + tag,
             'config_sha256': digest_file(config), 'coverage_version': coverage.__version__,
             'status': 'STARTED'}
    write_json_new(root / f'{tag}.start.json', start)
    if flushed:
        database = root / start['data_file']
        data = coverage.CoverageData(basename=str(database))
        data.add_arcs({str(source): [(-1, 1), (1, -1)]})
        data.write()
        finish = {**start, 'status': 'FLUSHED', 'monotonic_end': 21.0,
                  'measured_files': [str(source)], 'data_sha256': digest_file(database)}
        write_json_new(root / f'{tag}.finish.json', finish)
    options = {'expected_processes': [identity], 'config': config,
               'config_sha256': digest_file(config), 'expected_sources': {str(source): digest_file(source)},
               'coverage_version': coverage.__version__}
    return root, tag, start, options


def test_hook_requires_workspace_venv_and_never_overwrites(tmp_path):
    environment = tmp_path / 'environment'
    environment.mkdir()
    with pytest.raises(ValueError, match='venv'):
        install_hook(environment, tmp_path)
    (environment / 'pyvenv.cfg').write_text('fixture only')
    site = environment / ('Lib/site-packages' if os.name == 'nt' else 'lib/python3.12/site-packages')
    site.mkdir(parents=True)
    result = install_hook(environment, tmp_path)
    before = (site / HOOK_NAME).read_bytes()
    assert len(result['sha256']) == 64
    with pytest.raises(FileExistsError):
        install_hook(environment, tmp_path)
    assert (site / HOOK_NAME).read_bytes() == before
    with pytest.raises(ValueError, match='venv'):
        install_hook(environment, site)


def test_empty_participation_cannot_claim_coverage(tmp_path):
    root, tag, start, options = coverage_fixture(tmp_path, flushed=False)
    # Preserve this unit fixture's bytes outside the empty evidence directory.
    (root / f'{tag}.start.json').rename(tmp_path / 'retained-start.json')
    with pytest.raises(ValueError, match='no covered'):
        inspect_participation(root, **options)


def test_genuine_child_covers_project_root_and_missing_flush_rejected(tmp_path):
    repo = Path(__file__).resolve().parents[3]
    output = tmp_path / 'child coverage'
    output.mkdir()
    config = tmp_path / 'coverage.ini'
    write_config(config, repo / 'bittorrent_lite')
    environment = dict(os.environ)
    environment.pop('PYTHONPATH', None)
    environment['BTL_COVERAGE_ROOT'] = str(output)
    environment['COVERAGE_PROCESS_START'] = str(config)
    recorder = RecordingSession(tmp_path / 'commands', 'preparation', 'child-coverage', {})
    result = recorder.run('smoke', [sys.executable, '-c',
        'import json,os,time; from bittorrent_lite.common.paths import project_root; '
        'from bittorrent_lite.acceptance_tools.recording import process_identity; '
        'print(json.dumps({"root":str(project_root()),"identity":process_identity(os.getpid())})); '
        'time.sleep(0.15)'],
        cwd=tmp_path, env=environment, timeout_s=15,
        oracle='installed child executes project_root and its actual branch data flushes')
    observed = json.loads((recorder.root / 'smoke/stdout.bin').read_text())
    assert Path(observed['root']) == repo
    guardian = json.loads((recorder.root / 'smoke/guardian.jsonl').read_text().splitlines()[0])['identity']
    registration = json.loads((recorder.root / 'smoke/guardian-result.json').read_text())
    assert any((entry['pid'], entry['creation_time'], entry['executable']) ==
               (observed['identity']['pid'], observed['identity']['creation_time'], observed['identity']['executable'])
               for entry in registration['identities'])
    import coverage
    options = {'expected_processes': [guardian, observed['identity']],
               'config': config, 'config_sha256': digest_file(config),
               'expected_sources': {str(path): digest_file(path) for path in source_files(repo)
                                    if path.suffix == '.py' and path.is_relative_to(repo / 'bittorrent_lite')
                                    and 'tests' not in path.relative_to(repo).parts},
               'coverage_version': coverage.__version__}
    participants = inspect_participation(output, **options)
    source = repo / 'bittorrent_lite/common/paths.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'project_root')
    body_lines = {n.lineno for n in ast.walk(fn) if isinstance(n, ast.Return)}
    covered = [(entry, lines) for entry in participants
               for name, lines in entry['executed_lines'].items()
               if Path(name) == source]
    assert covered and any(body_lines.intersection(lines) for _, lines in covered)
    assert all(entry['pid'] != os.getpid() for entry, _ in covered)
    assert all(entry['python_executable'] == sys.executable for entry, _ in covered)
    assert result['exit_code'] == 0
    # Corrupt only this disposable negative-control fixture, retaining bytes.
    finish = next(output.glob('*.finish.json'))
    saved = finish.read_bytes()
    finish.rename(finish.with_suffix('.retained'))
    with pytest.raises(ValueError, match='did not flush'):
        inspect_participation(output, **options)
    assert saved


def test_participation_reconciles_registry_and_frozen_inputs(tmp_path):
    root, tag, start, options = coverage_fixture(tmp_path)
    rows = inspect_participation(root, **options)
    assert rows[0]['status'] == 'FLUSHED'
    assert list(rows[0]['executed_lines'].values()) == [[1]]
    missing = deepcopy(options)
    missing['expected_processes'].append({**start, 'pid': 124})
    with pytest.raises(ValueError, match='missing coverage start'):
        inspect_participation(root, **missing)
    with pytest.raises(ValueError, match='config differs'):
        inspect_participation(root, **{**options, 'config_sha256': 'f' * 64})
    with pytest.raises(ValueError, match='config or version'):
        inspect_participation(root, **{**options, 'coverage_version': 'wrong-version'})
    source = Path(next(iter(options['expected_sources'])))
    source.write_text('changed = 2\n', encoding='utf-8')
    with pytest.raises(ValueError, match='source inventory differs'):
        inspect_participation(root, **options)


@pytest.mark.parametrize('suffix', ['finish.json', 'error.json'])
def test_orphan_terminal_records_fail(tmp_path, suffix):
    root, tag, start, options = coverage_fixture(tmp_path)
    write_json_new(root / ('999-' + 'f' * 32 + '.' + suffix), {'fixture': 'orphan'})
    with pytest.raises(ValueError, match='unmatched or stale'):
        inspect_participation(root, **options)


def test_duplicate_identity_and_database_reuse_fail(tmp_path):
    root, tag, start, options = coverage_fixture(tmp_path)
    other_tag = '123-' + 'b' * 32
    write_json_new(root / (other_tag + '.start.json'), start)
    with pytest.raises(ValueError, match='duplicate coverage identity'):
        inspect_participation(root, **options)
    # Retain the rejected unit fixture before constructing a distinct identity.
    (root / (other_tag + '.start.json')).rename(tmp_path / 'retained-duplicate.json')
    other_tag = '124-' + 'c' * 32
    other = {**start, 'pid': 124}
    options['expected_processes'].append(other)
    write_json_new(root / (other_tag + '.start.json'), other)
    with pytest.raises(ValueError, match='reused coverage data filename'):
        inspect_participation(root, **options)


def test_coverage_json_duplicate_keys_are_rejected(tmp_path):
    root, tag, start, options = coverage_fixture(tmp_path)
    path = root / (tag + '.start.json')
    raw = path.read_bytes()
    path.write_bytes(raw.replace(b'"pid": 123', b'"pid": 123, "pid": 123'))
    with pytest.raises(ValueError, match='duplicate'):
        inspect_participation(root, **options)


def test_measured_file_outside_frozen_source_set_is_rejected(tmp_path):
    root, tag, start, options = coverage_fixture(tmp_path)
    other = tmp_path / 'different-source.py'
    other.write_text('other = 2\n', encoding='utf-8')
    options['expected_sources'] = {str(other): digest_file(other)}
    with pytest.raises(ValueError, match='unfrozen source'):
        inspect_participation(root, **options)


def test_each_coverage_child_path_is_checked_for_redirection(tmp_path, monkeypatch):
    root, tag, start, options = coverage_fixture(tmp_path)
    blocked = root / start['data_file']
    original = coverage_support.checked_path
    def reject_child(path, **kwargs):
        if Path(path) == blocked:
            raise ValueError('path redirection unit fixture')
        return original(path, **kwargs)
    monkeypatch.setattr(coverage_support, 'checked_path', reject_child)
    with pytest.raises(ValueError, match='path redirection'):
        inspect_participation(root, **options)


def test_declared_abrupt_termination_retains_bytes_without_coverage_credit(tmp_path):
    root, tag, start, options = coverage_fixture(tmp_path, flushed=False)
    with pytest.raises(ValueError, match='did not flush'):
        inspect_participation(root, **options)
    options['expected_processes'][0].update(case_id='fixture-kill', coverage_role='downloader-1')
    declaration = {'schema': 'btl-coverage-termination-plan-v1', 'case_id': 'fixture-kill',
                   'process_role': 'downloader-1', 'declared_at_monotonic': 19.0,
                   'termination_kind': 'forced'}
    observation = {'schema': 'btl-coverage-termination-observation-v1', 'case_id': 'fixture-kill',
                   'process_role': 'downloader-1', 'termination_kind': 'forced',
                   'identity': options['expected_processes'][0], 'exit_confirmed': True,
                   'exit_code': -9, 'observed_at_monotonic': 21.0}
    refs = {}
    for name, value in [('declaration', declaration), ('observation', observation)]:
        path = tmp_path / (name + '.json')
        write_json_new(path, value)
        refs[name] = {'path': str(path), 'sha256': digest_file(path)}
    interruption = {**refs, 'identity': options['expected_processes'][0]}
    options['expected_terminations'] = [interruption]
    database = root / start['data_file']
    database.write_bytes(b'interrupted unit fixture bytes, not a valid database')
    rows = inspect_participation(root, **options)
    assert rows[0]['status'] == 'INTERRUPTED_NOT_COUNTED'
    assert rows[0]['executed_lines'] == {} and rows[0]['executed_arcs'] == {}
    assert rows[0]['interrupted_files'] == {start['data_file']: digest_file(database)}
    bad = deepcopy(options)
    bad['expected_terminations'][0]['observation']['sha256'] = 'f' * 64
    with pytest.raises(ValueError, match='evidence hash mismatch'):
        inspect_participation(root, **bad)


def test_startup_snapshots_argv_before_module_execution_rewrites_it(tmp_path, monkeypatch):
    """Collector/process doubles check identity capture; no real coverage credit."""
    from types import SimpleNamespace

    output = tmp_path / 'mock-collector-records'
    output.mkdir()
    config = tmp_path / 'mock-coverage.ini'
    config.write_text('[run]\nbranch = True\n', encoding='utf-8')
    calls, finishes, collectors = [], [], []

    class CollectorDouble:
        def __init__(self, *, config_file, data_file, data_suffix):
            assert config_file == str(config) and data_suffix is False
            self.data_file = Path(data_file)
            collectors.append(self)

        def start(self):
            calls.append('start')

        def stop(self):
            calls.append('stop')

        def save(self):
            calls.append('save')
            self.data_file.write_bytes(b'mocked collector bytes; not a coverage database')

        def get_data(self):
            calls.append('get_data')
            return SimpleNamespace(measured_files=lambda: [])

    monkeypatch.setitem(sys.modules, 'coverage', SimpleNamespace(
        Coverage=CollectorDouble, __version__='unit-double-no-measured-coverage'))
    monkeypatch.setitem(sys.modules, 'psutil', SimpleNamespace(Process=lambda: SimpleNamespace(
        create_time=lambda: 123.0, exe=lambda: sys.executable)))
    monkeypatch.setattr(coverage_support, '_active', None)
    monkeypatch.setattr(coverage_support.atexit, 'register', finishes.append)
    monkeypatch.setattr(coverage_support.os, '_exit', lambda code: pytest.fail(f'unexpected startup failure {code}'))
    monkeypatch.setenv('BTL_COVERAGE_ROOT', str(output))
    monkeypatch.setenv('COVERAGE_PROCESS_START', str(config))
    argv = ['-m', '--peer-id', 'unit-peer']
    monkeypatch.setattr(sys, 'argv', argv)
    coverage_support.startup()
    assert calls == ['start'] and len(collectors) == len(finishes) == 1
    start_path, = output.glob('*.start.json')
    original_bytes = start_path.read_bytes()
    start = json.loads(original_bytes)
    assert start['argv'] == ['-m', '--peer-id', 'unit-peer']

    # Python -m rewrites element zero after .pth startup; user code may append
    # arguments too. The retained startup identity must alias neither mutation.
    argv[0] = str(tmp_path / '__main__.py')
    argv.append('--later-runtime-argument')
    finishes[0]()
    finish_path, = output.glob('*.finish.json')
    finish = json.loads(finish_path.read_bytes())
    assert finish['argv'] == start['argv'] == ['-m', '--peer-id', 'unit-peer']
    assert finish['argv'] != sys.argv
    assert all(finish[key] == value for key, value in start.items() if key != 'status')
    assert start_path.read_bytes() == original_bytes
    assert finish['status'] == 'FLUSHED' and finish['monotonic_end'] >= start['monotonic']
    assert finish['data_sha256'] == digest_file(collectors[0].data_file)
    assert calls == ['start', 'stop', 'save', 'get_data']
    assert not list(output.glob('*.error.json'))
