"""Pure preparation controls. These tests do not run build/pip/application commands."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tarfile
import zipfile

import pytest

from bittorrent_lite.acceptance_tools import portability as p
from bittorrent_lite.acceptance_tools.inventory import snapshot, write_json_new


def wheel_lock(tmp_path):
    house = tmp_path / 'offline wheels'
    house.mkdir()
    rows = []
    for name in sorted(p.REQUIRED_TOOLS):
        filename = name.replace('-', '_') + '-1.0-py3-none-any.whl'
        wheel = house / filename
        with zipfile.ZipFile(wheel, 'w') as archive:
            archive.writestr(name.replace('-', '_') + '-1.0.dist-info/METADATA',
                             f'Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n')
        rows.append({'file': filename, 'name': name, 'version': '1.0',
                     'sha256': hashlib.sha256(wheel.read_bytes()).hexdigest()})
    lock = {'schema': 1, 'python_version': '3.12.14', 'wheels': rows}
    path = tmp_path / 'lock.json'
    write_json_new(path, lock)
    return house, path, lock


def test_lock_reads_wheel_bytes_identity_and_required_closure(tmp_path):
    house, path, lock = wheel_lock(tmp_path)
    assert p.validate_wheel_lock(house, path) == lock
    (house / lock['wheels'][0]['file']).write_bytes(b'changed')
    with pytest.raises(ValueError, match='hash differs'):
        p.validate_wheel_lock(house, path)


def test_lock_distinguishes_vendored_metadata_from_duplicate_top_level_identity(tmp_path):
    house, path, lock = wheel_lock(tmp_path)
    row = lock['wheels'][0]
    wheel = house / row['file']
    with zipfile.ZipFile(wheel, 'a') as archive:
        archive.writestr('package/_vendor/dependency-1.0.dist-info/METADATA',
                         'Metadata-Version: 2.1\nName: dependency\nVersion: 1.0\n')
    row['sha256'] = hashlib.sha256(wheel.read_bytes()).hexdigest()
    path.write_text(json.dumps(lock), encoding='utf-8')
    assert p.validate_wheel_lock(house, path) == lock
    with zipfile.ZipFile(wheel, 'a') as archive:
        archive.writestr('other-1.0.dist-info/METADATA',
                         'Metadata-Version: 2.1\nName: other\nVersion: 1.0\n')
    row['sha256'] = hashlib.sha256(wheel.read_bytes()).hexdigest()
    path.write_text(json.dumps(lock), encoding='utf-8')
    with pytest.raises(ValueError, match='unique METADATA'):
        p.validate_wheel_lock(house, path)


@pytest.mark.parametrize('change', ['traversal', 'metadata', 'duplicate', 'missing', 'bom'])
def test_lock_negative_controls(tmp_path, change):
    house, path, lock = wheel_lock(tmp_path)
    if change == 'traversal':
        lock['wheels'][0]['file'] = '../unsafe.whl'
    elif change == 'metadata':
        lock['wheels'][0]['version'] = '2.0'
    elif change == 'duplicate':
        lock['wheels'].append(deepcopy(lock['wheels'][0]))
    elif change == 'missing':
        lock['wheels'].pop()
    raw = json.dumps(lock).encode('utf-8')
    path.write_bytes((b'\xef\xbb\xbf' if change == 'bom' else b'') + raw)
    with pytest.raises((ValueError, p.PrerequisiteBlocked)):
        p.validate_wheel_lock(house, path)


def test_environment_removes_ambient_python_pip_and_coverage(tmp_path):
    env = p.offline_environment(tmp_path, {'PATH': 'keep', 'PYTHONPATH': 'external',
        'PythonHome': 'external', 'PIP_INDEX_URL': 'remote', 'PIP_TARGET': 'source',
        'PYTEST_ADDOPTS': '--skip', 'COVERAGE_PROCESS_START': 'external',
        'BTL_EVENT_LOG': 'old', 'ACCEPTANCE_PROCESS_REGISTRY': 'old', 'VIRTUAL_ENV': 'old'})
    assert env['PATH'] == 'keep'
    assert env['PIP_NO_INDEX'] == '1'
    assert not ({'PYTHONPATH', 'PythonHome', 'PIP_INDEX_URL', 'PIP_TARGET', 'PYTEST_ADDOPTS',
                 'COVERAGE_PROCESS_START', 'BTL_EVENT_LOG', 'ACCEPTANCE_PROCESS_REGISTRY', 'VIRTUAL_ENV'} & env.keys())


def test_copy_preserves_untracked_legacy_unicode_and_rejects_reuse(tmp_path):
    repo = tmp_path / 'repository'
    (repo / 'bittorrent_lite' / 'legacy').mkdir(parents=True)
    (repo / 'bittorrent_lite' / 'legacy' / '\u03a9 module.py').write_bytes(b'# contributor bytes\r\n')
    (repo / 'untracked notes.txt').write_bytes(b'preserve\x00\xff')
    frozen = snapshot(repo)
    destination = tmp_path / 'source with spaces \u03a9'
    p.copy_source(repo, destination, frozen)
    assert snapshot(destination) == frozen
    assert snapshot(repo) == frozen
    with pytest.raises(FileExistsError):
        p.copy_source(repo, destination, frozen)
    with pytest.raises(ValueError, match='outside the source inventory'):
        p.copy_source(repo, repo / 'copy', frozen)


def test_package_inventory_keeps_legacy_and_resources_excludes_tests_and_tool_imports():
    paths = ['bittorrent_lite/__init__.py', 'bittorrent_lite/scheduling/legacy/choking.py',
             'bittorrent_lite/tests/test_something.py', 'bittorrent_lite/acceptance_tools/recording.py',
             'bittorrent_lite/experiments/scripts/launcher.py', *p.RESOURCES]
    frozen = {'files': [{'path': name, 'sha256': 'a' * 64} for name in paths]}
    spec = p.package_inventory(frozen)
    assert {row['module'] for row in spec['modules']} == {
        'bittorrent_lite', 'bittorrent_lite.scheduling.legacy.choking'}
    assert 'bittorrent_lite/acceptance_tools/recording.py' in spec['expected_archive_files']
    assert all('/tests/' not in name for name in spec['expected_archive_files'])
    assert len(spec['source_only']) == 2
    assert all(row['status'] == 'NOT RUN' for row in spec['source_only'])


@pytest.mark.parametrize('kind', ['wheel', 'sdist'])
def test_distribution_compares_real_bytes_and_rejects_missing(tmp_path, kind):
    name = 'bittorrent_lite/legacy.py'
    content = b'preserved legacy bytes\r\n'
    artifact = tmp_path / ('project.whl' if kind == 'wheel' else 'project.tar.gz')
    if kind == 'wheel':
        with zipfile.ZipFile(artifact, 'w') as archive:
            archive.writestr(name, content)
    else:
        with tarfile.open(artifact, 'w:gz') as archive:
            item = tarfile.TarInfo('project-1.0/' + name)
            item.size = len(content)
            archive.addfile(item, io.BytesIO(content))
    expected = {name: hashlib.sha256(content).hexdigest()}
    assert p.verify_distribution(artifact, expected)['verified_files'] == 1
    with pytest.raises(ValueError, match='missing or changed'):
        p.verify_distribution(artifact, {name: 'f' * 64})


@pytest.mark.parametrize('name', ['../outside', '/absolute', 'C:/drive', 'a/../escape', 'a\\escape', 'a/./alias'])
def test_archive_path_controls(name):
    with pytest.raises(ValueError, match='unsafe distribution member'):
        p.archive_name(name)


def test_distribution_rejects_symbolic_link(tmp_path):
    path = tmp_path / 'bad.tar.gz'
    with tarfile.open(path, 'w:gz') as archive:
        item = tarfile.TarInfo('project-1.0/bittorrent_lite/link.py')
        item.type = tarfile.SYMTYPE
        item.linkname = '/outside'
        archive.addfile(item)
    with pytest.raises(ValueError, match='link or nonregular'):
        p.verify_distribution(path, {})


def test_probe_rejects_wrong_origin_missing_module_and_resource(tmp_path):
    prefix = tmp_path / 'venv \u03a9'
    spec = {'modules': [{'module': 'bittorrent_lite', 'sha256': 'a' * 64}],
            'resources': [{'path': p.RESOURCES[0], 'sha256': 'b' * 64}], 'entrypoints': p.ENTRYPOINTS}
    observed = {'prefix': str(prefix), 'modules': [{'module': 'bittorrent_lite',
        'origin': str(prefix / 'site-packages/bittorrent_lite/__init__.py'), 'sha256': 'a' * 64}],
        'resources': [{'path': p.RESOURCES[0], 'installed_path': str(prefix / p.RESOURCES[0]),
                       'sha256': 'b' * 64}], 'entrypoints': dict(p.ENTRYPOINTS)}
    p.validate_probe(observed, spec, prefix)
    wrong = deepcopy(observed)
    wrong['modules'][0]['origin'] = str(tmp_path / 'source' / 'bittorrent_lite/__init__.py')
    with pytest.raises(ValueError, match='source-checkout'):
        p.validate_probe(wrong, spec, prefix)
    wrong = deepcopy(observed)
    wrong['modules'] = []
    with pytest.raises(ValueError, match='module inventory'):
        p.validate_probe(wrong, spec, prefix)
    wrong = deepcopy(observed)
    wrong['resources'][0]['sha256'] = 'f' * 64
    with pytest.raises(ValueError, match='resource inventory'):
        p.validate_probe(wrong, spec, prefix)


def test_missing_offline_prerequisite_reports_blocked_without_commands(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'preserve.txt').write_bytes(b'original')
    interpreter = tmp_path / 'unused-python.exe'
    interpreter.write_bytes(b'never launched')
    def prohibited(*args, **kwargs):
        pytest.fail('blocked prerequisite must never launch commands')
    monkeypatch.setattr(p, 'Driver', prohibited)
    report = p.run_packaging(repo, tmp_path / 'fresh evidence', interpreter,
                             tmp_path / 'missing wheels', tmp_path / 'missing lock.json')
    assert report['status'] == 'BLOCKED'
    assert report['acceptance_ready'] is False and report['commands'] == []
    assert report['source_preserved'] is True


def test_jsonl_expected_negative_requires_recovery_and_unchanged_state():
    state = {'config': {}, 'num_pieces': 3, 'owned': [], 'counters': {}, 'successes': 0,
             'penalty_entry_count': 0, 'penalty_provider_count': 0, 'penalties': [],
             'recent_events': [], 'omitted_events': 0}
    rows = [{'ok': True, 'result': None}, {'ok': True, 'result': deepcopy(state)},
            {'ok': False, 'error': 'ValueError', 'message': 'unknown operation'},
            {'ok': True, 'result': deepcopy(state)}]
    encode = lambda value: b'\n'.join(json.dumps(row).encode() for row in value)
    assert p.verify_jsonl(encode(rows), 'recovery') == rows
    rows[-1]['result']['owned'].append(1)
    with pytest.raises(ValueError, match='changed state'):
        p.verify_jsonl(encode(rows), 'recovery')
    with pytest.raises(ValueError, match='reject invalid op and continue'):
        p.verify_jsonl(encode(rows[:-1]), 'recovery')


def test_scheduler_oracle_requires_real_request_identities():
    # Exact bytes retained from genuine preparation diagnostic030, not a guessed
    # snapshot shape. This regression fixture is never current execution credit.
    raw = (Path(__file__).parent / 'fixtures/scheduler-demo-diagnostic030.stdout.bin').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == 'c6d31889a0949de0429bd2d8bc1586c7a9bb88e4d5d1e3ddf8b2f5608d250d97'
    p.verify_scheduler_demo(raw)
    text = raw.decode('utf-8')
    with pytest.raises(ValueError, match='identities'):
        p.verify_scheduler_demo(text.replace("('HAVE', 1, 0)", "('HAVE', 1, 2)").encode())
    with pytest.raises(ValueError, match='send confirmation'):
        p.verify_scheduler_demo(text.replace("'deadline': 10.1", "'deadline': 10.2").encode())


def test_pipeline_oracle_rejects_empty_success_document():
    with pytest.raises(ValueError, match='six example actions'):
        p.verify_pipeline_output(b'{"results": [], "snapshot": {}}')
