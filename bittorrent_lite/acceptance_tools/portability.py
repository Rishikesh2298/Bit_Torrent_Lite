"""Recorded offline packaging diagnostics; never a whole-campaign READY gate.

All application processes are started through RecordingSession. The packaging
and functional standalone stages are separate so the campaign coordinator can
preserve its unit/integration/system phase ordering. Nothing runs on import.
"""
from __future__ import annotations

import argparse
import ast
from email.parser import BytesParser
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tarfile
import traceback
import zipfile

from .evidence import strict_json
from .inventory import (checked_path, compare_snapshots, digest_file, snapshot,
                        source_files, write_json_new)


class PrerequisiteBlocked(RuntimeError):
    """A required resource has not been provided; no execution credit."""


REQUIRED_TOOLS = frozenset({'pip', 'build', 'setuptools', 'wheel', 'packaging',
                            'pyproject-hooks'})
RESOURCES = ('bittorrent_lite/scheduling/request_pipeline/example.json',
             'bittorrent_lite/experiments/configs/base.json',
             'bittorrent_lite/experiments/configs/stand_in.json')
HELP_MODULES = ('bittorrent_lite', 'bittorrent_lite.application.cli',
                'bittorrent_lite.storage.generate_metadata',
                'bittorrent_lite.discovery.tracker_server',
                'bittorrent_lite.scheduling.request_pipeline',
                'bittorrent_lite.scheduling.upload_service')
ENTRYPOINTS = {'bittorrent-lite': 'bittorrent_lite.application.cli:main',
               'bittorrent-metadata': 'bittorrent_lite.storage.generate_metadata:main'}
INSTALLED_TRANSFER_SIZES = (1, 65536, 524411)


def canonical_name(value):
    return re.sub(r'[-_.]+', '-', value).lower()


def validate_wheel_lock(wheelhouse: Path, lock_path: Path):
    """Verify actual wheel bytes and METADATA, not only filenames or a manifest."""
    if not wheelhouse.is_dir() or not lock_path.is_file():
        raise PrerequisiteBlocked('offline wheelhouse and hash lock must both exist')
    wheelhouse, lock_path = checked_path(wheelhouse, strict=True), checked_path(lock_path, strict=True)
    lock = strict_json(lock_path.read_bytes())
    if (not isinstance(lock, dict) or set(lock) != {'schema', 'python_version', 'wheels'}
            or type(lock['schema']) is not int or lock['schema'] != 1
            or not isinstance(lock['python_version'], str)
            or not re.fullmatch(r'3\.[0-9]+\.[0-9]+', lock['python_version'])
            or not isinstance(lock['wheels'], list)):
        raise ValueError('invalid offline wheel lock schema')
    seen = set()
    for item in lock['wheels']:
        if not isinstance(item, dict) or set(item) != {'file', 'name', 'version', 'sha256'}:
            raise ValueError('invalid offline wheel entry')
        if any(not isinstance(item[k], str) for k in item):
            raise ValueError('wheel entry fields must be strings')
        filename = item['file']
        if (not re.fullmatch(r'[A-Za-z0-9_.+!-]+\.whl', filename)
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', item['name'])
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+!]*', item['version'])
                or not re.fullmatch(r'[0-9a-f]{64}', item['sha256'])):
            raise ValueError('unsafe or unpinned wheel entry')
        name = canonical_name(item['name'])
        if name in seen:
            raise ValueError(f'duplicate locked distribution: {name}')
        seen.add(name)
        wheel = checked_path(wheelhouse / filename)
        if not wheel.is_file():
            raise PrerequisiteBlocked(f'missing locked wheel: {filename}')
        if digest_file(wheel) != item['sha256']:
            raise ValueError(f'locked wheel hash differs: {filename}')
        with zipfile.ZipFile(wheel) as archive:
            metadata = [n for n in archive.namelist()
                        if n.endswith('.dist-info/METADATA') and len(PurePosixPath(n).parts) == 2]
            if len(metadata) != 1:
                raise ValueError(f'wheel lacks unique METADATA: {filename}')
            parsed = BytesParser().parsebytes(archive.read(metadata[0]))
            if (canonical_name(parsed.get('Name', '')) != name
                    or parsed.get('Version') != item['version']):
                raise ValueError(f'wheel identity differs from lock: {filename}')
    if REQUIRED_TOOLS - seen:
        raise PrerequisiteBlocked(f'missing locked tools: {sorted(REQUIRED_TOOLS - seen)}')
    return lock


def offline_environment(scratch: Path, inherited=None):
    """Remove ambient Python/pip injection; local generated paths are evidence."""
    environment = dict(os.environ if inherited is None else inherited)
    for key in list(environment):
        upper = key.upper()
        if (upper.startswith(('PYTHON', 'PYTEST', 'PIP_', 'COVERAGE_', 'BTL_'))
                or upper in {'VIRTUAL_ENV', '__PYVENV_LAUNCHER__', 'ACCEPTANCE_PROCESS_REGISTRY'}):
            del environment[key]
    environment.update(PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1',
                       PIP_NO_INDEX='1', PIP_DISABLE_PIP_VERSION_CHECK='1',
                       PIP_CONFIG_FILE=os.devnull, TEMP=str(scratch), TMP=str(scratch),
                       TMPDIR=str(scratch), MPLCONFIGDIR=str(scratch / 'matplotlib'),
                       PIP_CACHE_DIR=str(scratch / 'pip-cache'))
    return environment


def copy_source(repo: Path, destination: Path, frozen: dict):
    """Copy every inventoried file, including untracked contributor files."""
    repo, destination = checked_path(repo, strict=True), checked_path(destination)
    if destination.is_relative_to(repo) and not destination.is_relative_to(repo / '.validation'):
        raise ValueError('staged source must be outside the source inventory')
    compare_snapshots(frozen, snapshot(repo))
    destination.mkdir(parents=True, exist_ok=False)
    for original in source_files(repo):
        target = destination / original.relative_to(repo)
        target.parent.mkdir(parents=True, exist_ok=True)
        with original.open('rb') as src, target.open('xb') as dst:
            shutil.copyfileobj(src, dst)
        shutil.copystat(original, target)
    compare_snapshots(frozen, snapshot(destination))
    compare_snapshots(frozen, snapshot(repo))


def package_inventory(frozen):
    modules, expected, source_only = [], {}, []
    files = {entry['path']: entry for entry in frozen['files']}
    for name, entry in files.items():
        parts = PurePosixPath(name).parts
        if not parts or parts[0] != 'bittorrent_lite' or 'tests' in parts or not name.endswith('.py'):
            continue
        expected[name] = entry['sha256']
        if 'acceptance_tools' in parts:
            source_only.append({'path': name, 'status': 'NOT RUN',
                                'reason': 'Acceptance tooling has separate pinned dependency/import diagnostics; not a product import.'})
            continue
        if name.startswith('bittorrent_lite/experiments/scripts/') and not name.endswith('/__init__.py'):
            source_only.append({'path': name, 'status': 'NOT RUN',
                                'reason': 'Experiment scripts require a source checkout; separate source invocation required.'})
            continue
        module = name[:-3].replace('/', '.')
        if module.endswith('.__init__'):
            module = module[:-9]
        modules.append({'module': module, 'path': name, 'sha256': entry['sha256']})
    for name in RESOURCES:
        if name not in files:
            raise PrerequisiteBlocked(f'missing declared package resource: {name}')
        expected[name] = files[name]['sha256']
    return {'modules': modules, 'expected_archive_files': expected,
            'resources': [{'path': name, 'sha256': files[name]['sha256']} for name in RESOURCES],
            'entrypoints': ENTRYPOINTS, 'source_only': source_only}


def archive_name(name):
    parts = PurePosixPath(name).parts
    if (not name or '\\' in name or ':' in name or name.startswith('/')
            or '..' in parts or '.' in name.split('/') or not parts
            or '' in name.rstrip('/').split('/')):
        raise ValueError(f'unsafe distribution member: {name!r}')
    return parts


def verify_distribution(path: Path, expected):
    """Read archives without extracting; require every production file/resource."""
    content = {}
    if path.name.endswith('.whl'):
        with zipfile.ZipFile(path) as archive:
            for item in archive.infolist():
                archive_name(item.filename)
                if (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('wheel contains a symlink')
                if item.is_dir():
                    continue
                if item.filename in content:
                    raise ValueError('duplicate wheel member')
                content[item.filename] = hashlib.sha256(archive.read(item)).hexdigest()
    elif path.name.endswith('.tar.gz'):
        roots = set()
        with tarfile.open(path, 'r:gz') as archive:
            for item in archive.getmembers():
                parts = archive_name(item.name)
                roots.add(parts[0])
                if item.isdir():
                    continue
                if not item.isfile() or len(parts) < 2:
                    raise ValueError('sdist contains a link or nonregular member')
                name = '/'.join(parts[1:])
                if name in content:
                    raise ValueError('duplicate sdist member')
                with archive.extractfile(item) as handle:
                    content[name] = hashlib.sha256(handle.read()).hexdigest()
        if len(roots) != 1:
            raise ValueError('sdist must have one root')
    else:
        raise ValueError('expected a wheel or tar.gz sdist')
    missing = [name for name, digest in expected.items() if content.get(name) != digest]
    if missing:
        raise ValueError(f'packaged bytes missing or changed: {missing}')
    return {'file': path.name, 'sha256': digest_file(path), 'verified_files': len(expected)}


PROBE_SOURCE = r'''
import hashlib, importlib, importlib.metadata, importlib.resources, importlib.util, json, os, pathlib, sys
spec = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))
prefix = pathlib.Path(sys.prefix).resolve()
assert prefix == pathlib.Path(sys.argv[2]).resolve(), (prefix, sys.argv[2])
assert 'PYTHONPATH' not in os.environ and 'PYTHONHOME' not in os.environ
assert importlib.util.find_spec('bittorrent_lite.tests') is None, 'tests unexpectedly installed'
observations = []
for item in spec['modules']:
    module = importlib.import_module(item['module'])
    origin = pathlib.Path(module.__file__).resolve()
    assert origin.is_relative_to(prefix), (item['module'], origin, prefix)
    digest = hashlib.sha256(origin.read_bytes()).hexdigest()
    assert digest == item['sha256'], (item['module'], digest)
    exports = list(getattr(module, '__all__', []))
    assert all(isinstance(name, str) and hasattr(module, name) for name in exports), (item['module'], exports)
    observations.append({'module': item['module'], 'origin': str(origin), 'sha256': digest, 'declared_exports': exports})
resources = []
for item in spec['resources']:
    relative = item['path'].split('/')[1:]
    resource = importlib.resources.files('bittorrent_lite').joinpath(*relative)
    digest = hashlib.sha256(resource.read_bytes()).hexdigest()
    assert digest == item['sha256'], item['path']
    resources.append({'path': item['path'], 'installed_path': str(resource), 'sha256': digest})
distribution = importlib.metadata.distribution('bittorrent-lite')
entrypoints = {e.name: e.value for e in distribution.entry_points if e.group == 'console_scripts'}
assert entrypoints == spec['entrypoints'], entrypoints
from bittorrent_lite.networking import session, messages
assert session.Handshake is messages.Handshake, 'Handshake compatibility identity changed'
print(json.dumps({'prefix': str(prefix), 'modules': observations, 'resources': resources, 'entrypoints': entrypoints}))
'''


def validate_probe(value, spec, prefix):
    if set(value) != {'prefix', 'modules', 'resources', 'entrypoints'}:
        raise ValueError('installed probe schema differs')
    prefix = Path(prefix).resolve()
    if Path(value['prefix']).resolve() != prefix or value['entrypoints'] != spec['entrypoints']:
        raise ValueError('installed prefix or entrypoints differ')
    expected = {row['module']: row['sha256'] for row in spec['modules']}
    actual = {}
    for row in value['modules']:
        if row['module'] in actual or not Path(row['origin']).resolve().is_relative_to(prefix):
            raise ValueError('duplicate or source-checkout module origin')
        actual[row['module']] = row['sha256']
    if actual != expected:
        raise ValueError('imported module inventory differs')
    resources = {}
    for row in value['resources']:
        if row['path'] in resources or not Path(row['installed_path']).resolve().is_relative_to(prefix):
            raise ValueError('duplicate or external installed resource')
        resources[row['path']] = row['sha256']
    if resources != {row['path']: row['sha256'] for row in spec['resources']}:
        raise ValueError('installed resource inventory differs')


def env_python(folder):
    return folder / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def _fresh_out(repo, out):
    repo, out = checked_path(repo, strict=True), checked_path(out)
    if out.is_relative_to(repo) and not out.is_relative_to(repo / '.validation'):
        raise ValueError('diagnostic output must be outside inventory, or under repository .validation')
    out.mkdir(parents=True, exist_ok=False)
    return repo, out


class Driver:
    def __init__(self, out, frozen):
        if importlib.util.find_spec('psutil') is None:
            raise PrerequisiteBlocked('recorder dependency psutil is unavailable in supervisor environment')
        from .recording import RecordingSession
        self.out = out
        self.commands = []
        self.cwd = out / 'unrelated working directory \u03a9'
        self.cwd.mkdir()
        scratch = out / 'temporary files \u03a9'
        scratch.mkdir()
        self.environment = offline_environment(scratch)
        self.session = RecordingSession(out / 'commands', 'portability', 'diagnostic',
                                        {'source': frozen['sha256']})

    def run(self, case, argv, oracle, *, stdin=None, timeout=180):
        # Append before execution so failures retain the attempted record location.
        self.commands.append({'case_id': case, 'record': f'commands/{case}/record.json',
                              'semantic_oracle': oracle, 'semantic_status': 'NOT RUN'})
        self.session.run(case, [str(a) for a in argv], cwd=self.cwd,
                         env=self.environment, stdin_bytes=stdin, timeout_s=timeout, oracle=oracle)
        return (self.out / 'commands' / case / 'stdout.bin').read_bytes()

    def verified(self):
        self.commands[-1]['semantic_status'] = 'PASS'


def run_packaging(repo, out, python, wheelhouse, wheel_lock):
    repo, out = _fresh_out(repo, out)
    frozen = snapshot(repo)
    write_json_new(out / 'source-before.json', frozen)
    report = {'schema': 1, 'stage': 'offline-packaging', 'status': 'NOT RUN',
              'acceptance_ready': False, 'source_root': str(repo), 'source_sha256': frozen['sha256'],
              'commands': [], 'installations': {}, 'limitations': [
                  'This host only; second OS and human/source-isolation gates remain separate.',
                  'Source-only experiment commands and standalone functional cases are separate stages.',
                  'Build backends execute trusted frozen source; pip network lookup is disabled, not an OS network sandbox.',
                  'Guardian observation of build/pip descendants is polling; explicit descendant registration remains a campaign gate.']}
    driver = None
    try:
        if not Path(python).is_absolute():
            raise ValueError('interpreter must be an absolute path, not a PATH alias')
        if not Path(python).is_file():
            raise PrerequisiteBlocked('absolute interpreter file is unavailable')
        python = checked_path(python, strict=True)
        if not python.is_file():
            raise PrerequisiteBlocked('absolute interpreter file is unavailable')
        lock = validate_wheel_lock(Path(wheelhouse), Path(wheel_lock))
        report['wheel_lock_sha256'] = digest_file(Path(wheel_lock))
        write_json_new(out / 'wheel-lock.json', lock)
        spec = package_inventory(frozen)
        write_json_new(out / 'installed-spec.json', spec)
        driver = Driver(out, frozen)
        identity = strict_json(driver.run('interpreter', [python, '-I', '-c',
            'import json,platform,sys; print(json.dumps({"version":platform.python_version(),"executable":sys.executable}))'],
            'Exact interpreter version equals pinned wheel lock; executable identity is recorded.'))
        if identity['version'] != lock['python_version']:
            raise PrerequisiteBlocked('interpreter version does not match pinned wheel lock')
        driver.verified()
        report['interpreter'] = identity
        stage = out / 'source copy with spaces \u03a9'
        copy_source(repo, stage, frozen)
        wheels = out / 'offline wheels'
        wheels.mkdir()
        for item in lock['wheels']:
            target = wheels / item['file']
            with (Path(wheelhouse) / item['file']).open('rb') as src, target.open('xb') as dst:
                shutil.copyfileobj(src, dst)
            if digest_file(target) != item['sha256']:
                raise ValueError('copied wheel hash differs')
        requirements = out / 'offline-requirements.txt'
        with requirements.open('x', encoding='utf-8', newline='\n') as handle:
            for item in lock['wheels']:
                handle.write(f"{item['name']}=={item['version']} --hash=sha256:{item['sha256']}\n")
        envs = {kind: out / f'{kind} environment \u03a9' for kind in ('build', 'wheel', 'sdist')}
        for kind, folder in envs.items():
            driver.run(kind + '-venv', [python, '-I', '-m', 'venv', '--copies', folder],
                       'Fresh venv created; subsequent installed-prefix and pip checks must pass.')
            if not env_python(folder).is_file() or not (folder / 'pyvenv.cfg').is_file():
                raise ValueError('venv did not create interpreter/configuration')
            driver.verified()
            driver.run(kind + '-dependencies', [env_python(folder), '-I', '-m', 'pip', 'install',
                       '--no-index', '--no-deps', '--only-binary=:all:', '--require-hashes',
                       '--find-links', wheels, '-r', requirements],
                       'Offline pinned dependencies install with required wheel hashes.', timeout=360)
            driver.verified()
            driver.run(kind + '-pip-check', [env_python(folder), '-I', '-m', 'pip', 'check'],
                       'Pinned environment has no unsatisfied declared dependencies.')
            driver.verified()
            versions = strict_json(driver.run(kind + '-versions', [env_python(folder), '-I', '-c',
                'import importlib.metadata,json; print(json.dumps({d.metadata["Name"]:d.version for d in importlib.metadata.distributions()}))'],
                'Installed distributions exactly equal the hash-verified lock.'))
            if {canonical_name(k): v for k, v in versions.items()} != {
                    canonical_name(item['name']): item['version'] for item in lock['wheels']}:
                raise ValueError('installed dependency versions differ from lock')
            driver.verified()
        dist = out / 'built distributions'
        driver.run('build-distributions', [env_python(envs['build']), '-I', '-m', 'build',
                   '--no-isolation', '--wheel', '--sdist', '--outdir', dist, stage],
                   'Build one wheel and one sdist; verify all production module/resource bytes.', timeout=360)
        artifacts = {'wheel': list(dist.glob('*.whl')), 'sdist': list(dist.glob('*.tar.gz'))}
        if any(len(paths) != 1 for paths in artifacts.values()) or len(list(dist.iterdir())) != 2:
            raise ValueError('build must produce exactly one wheel and one sdist')
        report['archives'] = [verify_distribution(paths[0], spec['expected_archive_files'])
                              for paths in artifacts.values()]
        driver.verified()
        for kind in ('wheel', 'sdist'):
            folder, artifact = envs[kind], artifacts[kind][0]
            exe = env_python(folder)
            driver.run(kind + '-install', [exe, '-I', '-m', 'pip', 'install', '--no-index',
                       '--no-deps', '--no-build-isolation', artifact],
                       'Fresh environment installs the actual built artifact.', timeout=360)
            driver.verified()
            observed = strict_json(driver.run(kind + '-origins', [exe, '-I', '-c', PROBE_SOURCE,
                                   out / 'installed-spec.json', folder],
                                   'Every mapped import comes from this venv with frozen bytes; resources, aliases and entrypoints agree.'))
            validate_probe(observed, spec, folder)
            driver.verified()
            write_json_new(out / f'{kind}-origins.json', observed)
            report['installations'][kind] = {'prefix': str(folder), 'python': str(exe),
                                            'origins': f'{kind}-origins.json'}
            for index, module in enumerate(HELP_MODULES):
                raw = driver.run(f'{kind}-module-help-{index}', [exe, '-I', '-m', module, '--help'],
                                 f'Supported {module} help exits zero and contains usage/options.')
                if b'usage:' not in raw.lower() or b'--help' not in raw:
                    raise ValueError(f'empty or malformed help: {module}')
                driver.verified()
            for index, name in enumerate(ENTRYPOINTS):
                entry = folder / ('Scripts' if os.name == 'nt' else 'bin') / (name + ('.exe' if os.name == 'nt' else ''))
                raw = driver.run(f'{kind}-entry-help-{index}', [entry, '--help'],
                                 f'Installed console entrypoint {name} emits real usage.')
                if b'usage:' not in raw.lower() or b'--help' not in raw:
                    raise ValueError(f'empty console entrypoint help: {name}')
                driver.verified()
        report['status'] = 'PASS'
    except PrerequisiteBlocked as exc:
        report.update(status='BLOCKED', reason=str(exc))
    except Exception:
        report.update(status='FAIL', exception=traceback.format_exc())
    finally:
        if driver:
            report['commands'] = driver.commands
        try:
            after = snapshot(repo)
            write_json_new(out / 'source-after.json', after)
            compare_snapshots(frozen, after)
            report['source_preserved'] = True
        except Exception:
            report.update(status='FAIL', source_preserved=False, source_exception=traceback.format_exc())
        write_json_new(out / 'report.json', report)
    return report


def verify_pipeline_output(raw):
    value = strict_json(raw)
    if set(value) != {'results', 'snapshot'} or len(value['results']) != 6:
        raise ValueError('pipeline response must cover all six example actions')
    expected_ops = ['register_connection', 'set_available', 'set_permissions',
                    'reserve', 'confirm_sent', 'expire']
    for index, (row, op) in enumerate(zip(value['results'], expected_ops), 1):
        if row['action'] != index or row['op'] != op:
            raise ValueError('pipeline action identity mismatch')
    if [row['result'] for row in value['results'][:3]] != [None, None, []]:
        raise ValueError('pipeline setup action results differ')
    reserve = value['results'][3]['result']
    if reserve != {'connection_id': 1, 'request_id': 1, 'piece_index': 0,
                   'provider_id': 'source-A', 'queued_at': 0, 'sent_at': None,
                   'deadline': None, 'verifying': False}:
        raise ValueError('pipeline reservation differs')
    if value['results'][4]['result'] is not True:
        raise ValueError('pipeline send confirmation failed')
    if value['results'][5]['result'] != [{'connection_id': 1, 'request_id': 1, 'piece_index': 0,
                                        'kind': 'expired', 'reason': 'response_timeout', 'at': 11}]:
        raise ValueError('pipeline expiry identity/result differs')
    state = value['snapshot']
    if state['num_pieces'] != 3 or state['owned'] != [] or state['pending'] != []:
        raise ValueError('pipeline final ownership/pending state differs')
    if state['outstanding'] != [{'connection_id': 1, 'count': 0}]:
        raise ValueError('pipeline outstanding request leaked')
    if state['connections'] != [{'connection_id': 1, 'provider_id': 'source-A',
                                 'available': [0, 1, 2], 'interested': True, 'unchoked': True}]:
        raise ValueError('pipeline connection state differs')


def verify_jsonl(raw, kind):
    rows = [strict_json(line) for line in raw.splitlines()]
    if kind == 'recovery':
        if len(rows) != 4 or [row.get('ok') for row in rows] != [True, True, False, True]:
            raise ValueError('recovery must reject invalid op and continue')
        if (rows[0]['result'] is not None or rows[1]['result'] != rows[3]['result']
                or rows[2].get('error') != 'ValueError' or not rows[2].get('message')):
            raise ValueError('recovery rejection changed state or lacked structured error')
        state = rows[1]['result']
        if (set(state) != {'config', 'num_pieces', 'owned', 'counters', 'successes',
                          'penalty_entry_count', 'penalty_provider_count', 'penalties',
                          'recent_events', 'omitted_events'} or state['num_pieces'] != 3
                or state['owned'] != [] or state['penalties'] != []
                or state['penalty_entry_count'] != 0 or state['penalty_provider_count'] != 0):
            raise ValueError('recovery snapshot schema or initialized state differs')
    elif kind == 'choking':
        if (len(rows) != 6 or rows[0] != {'ok': True} or rows[1] != {'ok': True}
                or set(rows[2]) != {'state'} or rows[2] != rows[4]
                or rows[3].get('ok') is not False or rows[5] != {'ok': True}
                or rows[3].get('error', {}).get('type') != 'ValueError'
                or not rows[3].get('error', {}).get('message')):
            raise ValueError('choking response/rejection/continued state differs')
        state = rows[2]['state']
        if (set(state) != {'now', 'upload_enabled', 'seeder', 'closing', 'closed', 'peers',
                          'regular', 'optimistic', 'diagnostics'} or state['now'] != 0
                or state['closed'] is not False or len(state['peers']) != 1
                or state['peers'][0]['peer_id'] != 'peer-A'
                or state['peers'][0]['interested'] is not True):
            raise ValueError('choking snapshot schema or connected peer differs')
    else:
        raise ValueError('unknown JSONL verifier kind')
    return rows


def verify_scheduler_demo(raw):
    lines = raw.decode('utf-8').splitlines()
    outputs = [ast.literal_eval(line.split('out:', 1)[1].strip()) for line in lines if 'out:' in line]
    pending = [ast.literal_eval(line.split('pending:', 1)[1].strip()) for line in lines if 'pending:' in line]
    requests = [msg for msg in outputs if msg[0] == 'REQUEST']
    haves = [msg for msg in outputs if msg[0] == 'HAVE']
    if (len(requests) != 2 or len(haves) != 1 or len(pending) != 3
            or len(pending[-1]) != 1 or not any('owned: 1 / 4 ' in line for line in lines)):
        raise ValueError('scheduler demo lacks completed piece and next request')
    first, confirmed, next_request = pending[0], pending[1], pending[2][0]
    fields = {'connection_id', 'request_id', 'piece_index', 'sent', 'verifying', 'deadline'}
    if any(set(row) != fields for row in (first, confirmed, next_request)):
        raise ValueError('scheduler pending snapshot schema differs')
    # Coordinator.snapshot preserves the standalone sent/deadline schema, not
    # PipelineManager's sent_at field. The example confirms at t=0.1 with the
    # declared ten-second response timeout, so its observable deadline is 10.1.
    if (first['piece_index'] == next_request['piece_index']
            or first['request_id'] >= next_request['request_id']
            or any(row['connection_id'] != 1 or row['verifying'] is not False
                   for row in (first, confirmed, next_request))
            or first['sent'] is not False or first['deadline'] is not None
            or confirmed['sent'] is not True or confirmed['deadline'] != 10.1
            or any(first[key] != confirmed[key]
                   for key in ('connection_id', 'request_id', 'piece_index'))
            or next_request['sent'] is not False or next_request['deadline'] is not None
            or haves[0] != ('HAVE', 1, first['piece_index'])
            or requests != [('REQUEST', 1, first['request_id'], first['piece_index']),
                            ('REQUEST', 1, next_request['request_id'], next_request['piece_index'])]):
        raise ValueError('scheduler request/HAVE identities or send confirmation differ')


def run_standalone(packaging_root, out):
    """Phase-05 smoke procedures only; local demos are not network evidence."""
    packaging_root = checked_path(packaging_root, strict=True)
    package_report = strict_json((packaging_root / 'report.json').read_bytes())
    repo = checked_path(Path(package_report['source_root']), strict=True)
    repo, out = _fresh_out(repo, out)
    frozen = snapshot(repo)
    write_json_new(out / 'source-before.json', frozen)
    report = {'schema': 1, 'stage': 'installed-standalone-smoke', 'status': 'NOT RUN',
              'acceptance_ready': False, 'commands': [],
              'packaging_report_sha256': digest_file(packaging_root / 'report.json'),
              'limitations': ['These demos are local simulation/API evidence, not real-network transfers.',
                              'Full standalone negative/API ledgers and legacy comparisons remain separate.']}
    driver = None
    try:
        if package_report['status'] != 'PASS' or package_report['stage'] != 'offline-packaging':
            raise PrerequisiteBlocked('prior packaging diagnostic did not pass')
        if frozen['sha256'] != package_report['source_sha256']:
            raise ValueError('source differs from packaged diagnostic revision')
        spec = strict_json((packaging_root / 'installed-spec.json').read_bytes())
        if spec != package_inventory(frozen):
            raise ValueError('installed specification differs from frozen source inventory')
        driver = Driver(out, frozen)
        for kind in ('wheel', 'sdist'):
            installation = package_report['installations'][kind]
            prefix = checked_path(Path(installation['prefix']), strict=True)
            exe = checked_path(Path(installation['python']), strict=True)
            if not prefix.is_relative_to(packaging_root) or exe != env_python(prefix):
                raise ValueError('installation paths escape packaging evidence')
            observed = strict_json(driver.run(kind + '-origins', [exe, '-I', '-c', PROBE_SOURCE,
                packaging_root / 'installed-spec.json', prefix],
                'Recheck actual installed imports/resources against original package snapshot.'))
            validate_probe(observed, spec, prefix)
            driver.verified()
            resource = next(row['installed_path'] for row in observed['resources']
                            if row['path'] == RESOURCES[0])
            raw = driver.run(kind + '-pipeline-example', [exe, '-I', '-m',
                'bittorrent_lite.scheduling.request_pipeline', '--input', resource],
                'Actual packaged example reserves, confirms, expires same request, leaving zero pending.')
            verify_pipeline_output(raw)
            driver.verified()
            cases = {
                'recovery': ('bittorrent_lite.scheduling.recovery', [
                    {'op': 'create', 'num_pieces': 3, 'seed': 1}, {'op': 'snapshot', 'now': 0},
                    {'op': 'invalid-operation'}, {'op': 'snapshot', 'now': 0}]),
                'choking': ('bittorrent_lite.scheduling.choking_policy', [
                    {'op': 'config', 'random_seed': 1},
                    {'op': 'connect', 'peer': {'peer_id': 'peer-A', 'interested': True}, 'now': 0},
                    {'op': 'snapshot', 'now': 0}, {'op': 'invalid-operation', 'now': 0},
                    {'op': 'snapshot', 'now': 0}, {'op': 'shutdown', 'now': 1}]),
            }
            for name, (module, inputs) in cases.items():
                stdin = b''.join((json.dumps(row) + '\n').encode('utf-8') for row in inputs)
                raw = driver.run(kind + '-' + name + '-jsonl', [exe, '-I', '-m', module],
                    'One expected structured negative response, unchanged snapshot and continued successful processing; process exit zero alone is insufficient.', stdin=stdin)
                verify_jsonl(raw, name)
                driver.verified()
            demo_dir = out / (kind + ' upload demo \u03a9')
            raw = driver.run(kind + '-upload-demo', [exe, '-I', '-m',
                'bittorrent_lite.scheduling.upload_service', 'demo', '--directory', demo_dir],
                'Local simulated delivery: two real fixture files, exact hashes, 65536 acknowledged bytes and closed/no active jobs.')
            if not raw.decode('utf-8').rstrip().endswith('snapshot: sent_bytes=65536 sent_pieces=2 active_jobs=0 closed=True'):
                raise ValueError('upload demo final counters differ')
            manifest = strict_json((demo_dir / 'manifest.json').read_bytes())
            expected_pieces = [bytes(range(256)) * 128, bytes(reversed(range(256))) * 128]
            if manifest != {'version': 1, 'pieces': [
                    {'index': i, 'length': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                    for i, data in enumerate(expected_pieces)]}:
                raise ValueError('upload demo manifest differs')
            for index, data in enumerate(expected_pieces):
                if (demo_dir / f'piece-{index:06d}.bin').read_bytes() != data:
                    raise ValueError('upload demo fixture bytes differ')
            driver.verified()
            raw = driver.run(kind + '-scheduler-demo', [exe, '-I', '-m',
                'bittorrent_lite.examples.scheduler_demo'],
                'Demo verifies one piece, emits its HAVE, confirms sent/deadline=10.1 for the t=0.1 confirmation and schedules a distinct next request.')
            verify_scheduler_demo(raw)
            driver.verified()
        report['status'] = 'PASS'
    except PrerequisiteBlocked as exc:
        report.update(status='BLOCKED', reason=str(exc))
    except Exception:
        report.update(status='FAIL', exception=traceback.format_exc())
    finally:
        if driver:
            report['commands'] = driver.commands
        try:
            after = snapshot(repo)
            write_json_new(out / 'source-after.json', after)
            compare_snapshots(frozen, after)
            report['source_preserved'] = True
        except Exception:
            report.update(status='FAIL', source_preserved=False, source_exception=traceback.format_exc())
        write_json_new(out / 'report.json', report)
    return report


def installed_contract(packaging_root, kind, frozen):
    """Bind the installation to a successful packaging run of these exact sources."""
    if kind not in {'wheel', 'sdist'}:
        raise ValueError('unknown installation kind')
    packaging_root = checked_path(packaging_root, strict=True)
    report = strict_json((packaging_root / 'report.json').read_bytes())
    if report.get('status') != 'PASS' or report.get('stage') != 'offline-packaging':
        raise PrerequisiteBlocked('prior packaging diagnostic did not pass')
    if report['source_sha256'] != frozen['sha256']:
        raise ValueError('source differs from installed package revision')
    spec = strict_json((packaging_root / 'installed-spec.json').read_bytes())
    if spec != package_inventory(frozen):
        raise ValueError('installed specification differs from current frozen source inventory')
    installation = report['installations'][kind]
    prefix = checked_path(installation['prefix'], strict=True)
    exe = checked_path(installation['python'], strict=True)
    if not prefix.is_relative_to(packaging_root) or exe != env_python(prefix) or not exe.is_file():
        raise ValueError('installation paths escape packaging evidence')
    return prefix, exe, spec


def verify_installed_bytes(observed, spec, prefix):
    validate_probe(observed, spec, prefix)
    for row in observed['modules'] + observed['resources']:
        path = checked_path(row.get('origin', row.get('installed_path')), strict=True)
        if not path.is_relative_to(prefix) or digest_file(path) != row['sha256']:
            raise ValueError('actual installed file differs from observed frozen bytes')


def transfer_provenance(source, output, downloader, seeder, *, piece_root):
    """Read-only exact bytes and send/receive/commit oracle for actual event rows."""
    size = source.stat().st_size
    if output.stat().st_size != size or digest_file(output) != digest_file(source):
        raise ValueError('installed transfer final size/hash mismatch')
    with source.open('rb') as left, output.open('rb') as right:
        while True:
            a, b = left.read(1024 * 1024), right.read(1024 * 1024)
            if a != b:
                raise ValueError('installed transfer final byte comparison failed')
            if not a:
                break
    completed = [r for r in downloader if r['event'] == 'complete']
    if len(completed) != 1 or completed[0]['final_hash_ok'] is not True:
        raise ValueError('installed downloader completion must be unique and hash-verified')
    commits = [r for r in downloader if r['event'] == 'piece_verified']
    expected = list(range((size + 65535) // 65536))
    if sorted(r['piece'] for r in commits) != expected:
        raise ValueError('installed ownership commits are missing or duplicated')
    proofs = []
    for commit in commits:
        receive = [r for r in downloader if r['event'] == 'frame_received'
            and r['message_type'] == 'PIECE' and r['frame_complete'] is True
            and r['mono'] <= commit['mono'] and r['payload_bytes'] == commit['bytes']
            and all(r[k] == commit[k] for k in ('connection_id', 'request_id', 'piece', 'remote'))]
        if len(receive) != 1:
            raise ValueError('installed commit lacks a unique actual received PIECE')
        receive = receive[0]
        send = [r for r in seeder if r['event'] == 'frame_sent'
            and r['message_type'] == 'PIECE' and r['frame_complete'] is True
            and r['remote'] == 'downloader' and receive['remote'] == 'seeder'
            and r['local_endpoint'] == receive['remote_endpoint']
            and r['remote_endpoint'] == receive['local_endpoint']
            and all(r[k] == receive[k] for k in ('request_id', 'piece', 'payload_bytes'))]
        if len(send) != 1:
            raise ValueError('installed received PIECE lacks a unique matching source send')
        path = checked_path(piece_root / f"{commit['piece']}.piece", strict=True)
        with source.open('rb') as handle:
            handle.seek(commit['piece'] * 65536)
            expected_bytes = handle.read(65536)
        if path.read_bytes() != expected_bytes or len(expected_bytes) != commit['bytes']:
            raise ValueError('installed committed piece bytes differ from independent source slice')
        proofs.append({'piece': commit['piece'], 'size': len(expected_bytes),
                       'sha256': digest_file(path), 'send': send[0], 'receive': receive, 'commit': commit})
    return {'size': size, 'sha256': digest_file(output), 'byte_comparison': True, 'pieces': proofs}


def verify_installed_swarm(swarm, exe, executable_hash):
    from .measured import validate_event
    result = strict_json((swarm.root / 'results.json').read_bytes())
    names = ['tracker', 'seeder', 'downloader']
    if (result['cleanup_errors'] or [r['name'] for r in result['processes']] != names
            or [r['name'] for r in swarm.launches] != names):
        raise ValueError('installed transfer process inventory/cleanup differs')
    events = {}
    for child, launch, end in zip(swarm.children, swarm.launches, result['processes']):
        expected_prefix = [str(exe), '-I', '-X', 'utf8', '-m']
        module = 'bittorrent_lite.discovery.tracker_server' if child['name'] == 'tracker' else 'bittorrent_lite'
        if (launch['command'][:5] != expected_prefix or launch['command'][5] != module
                or launch['isolated'] is not True or launch['python_sha256'] != executable_hash
                or launch['identity'] != end['identity'] or child['interpreter'] != end['interpreter']
                or end['interpreter_exit_code'] != end['exit_code']
                or end['exit_code'] != end['expected_exit_code']):
            raise ValueError('installed command/observed identity/exit evidence differs')
        if child['name'] == 'tracker':
            allowed = [15] if os.name == 'nt' else [0, -15]
            if (end['exit_code'] not in allowed or end['termination_contract'] != {
                    'api': 'psutil.Process.terminate', 'platform': os.name, 'expected_exit_codes': allowed}):
                raise ValueError('installed tracker teardown oracle differs')
        elif end['exit_code'] != 0 or end['deliberate_kill']:
            raise ValueError('installed peer did not exit gracefully')
        # Swarm checks complete-line framing, strict contiguous sequence and the
        # independent OS interpreter PID. The shared oracle checks event schemas.
        rows = swarm.structured_events(child)
        for row in rows:
            validate_event({**row, 'proc': child['name']}, child['name'])
            if (row['event'] == 'status' and (row['state'] == 'ERROR' or row['storage_error'] or row['recovery_error'])
                    or row['event'] == 'piece_verification' and row['outcome'] != 'stored'
                    or row['event'] == 'complete' and row['final_hash_ok'] is not True):
                raise ValueError('installed runtime reported an unexpected fault')
        events[child['name']] = rows
    output = swarm.root / 'downloads/downloader' / swarm.source.name
    # FileStore namespaces pieces by SHA-256 of the exact saved metadata bytes,
    # not by the source hash or by the containing peer directory.
    file_id = digest_file(checked_path(swarm.meta, strict=True))
    provenance = transfer_provenance(swarm.source, output, events['downloader'], events['seeder'],
                                     piece_root=swarm.root / 'downloads/downloader/pieces' / file_id)
    return {'status': 'PASS', 'size': swarm.size, 'source_isolation_verified': False,
            'acceptance_eligible': False, 'isolated_python': str(exe), 'python_sha256': executable_hash,
            'source_sha256': swarm.digest, 'output': str(output), 'network_provenance': provenance}


def installed_transfer_worker(packaging_root, kind, out, origins, origins_sha256, executable_hash):
    """Source-only supervisor; every product child runs the installed isolated Python."""
    from bittorrent_lite.tests.end_to_end.support import Swarm, wait_for
    packaging_root, origins = checked_path(packaging_root, strict=True), checked_path(origins, strict=True)
    prior = strict_json((packaging_root / 'report.json').read_bytes())
    repo = checked_path(prior['source_root'], strict=True)
    repo, out = _fresh_out(repo, out)
    frozen = snapshot(repo)
    report = {'schema': 1, 'stage': 'installed-transfer-worker', 'kind': kind,
              'status': 'NOT RUN', 'acceptance_eligible': False, 'cases': [],
              'source_sha256': frozen['sha256'], 'source_isolation_verified': False}
    write_json_new(out / 'source-before.json', frozen)
    try:
        if not os.environ.get('ACCEPTANCE_PROCESS_REGISTRY'):
            raise PrerequisiteBlocked('installed transfer worker requires enclosing RecordingSession/guardian')
        if not Path(__file__).resolve().is_relative_to(repo / 'bittorrent_lite'):
            raise ValueError('installed-transfer supervisor is not the frozen source checkout')
        prefix, exe, spec = installed_contract(packaging_root, kind, frozen)
        if digest_file(origins) != origins_sha256 or digest_file(exe) != executable_hash:
            raise ValueError('installed origins/interpreter binding changed before transfer')
        observed = strict_json(origins.read_bytes())
        verify_installed_bytes(observed, spec, prefix)
        for size in INSTALLED_TRANSFER_SIZES:
            # This directory has no importable source package. -I also excludes
            # cwd/user-site/PYTHONPATH, so installed core execution is required.
            with Swarm(out / f'{kind} installed swarm {size} \u03a9', size=size,
                       fixture_seed=2026 + size, python_executable=exe,
                       python_sha256=executable_hash, isolated=True) as swarm:
                swarm.start_tracker()
                swarm.start_peer('seeder', seed=True)
                swarm.start_peer('downloader')
                def all_alive_and_complete():
                    for child in swarm.children:
                        swarm.check(child)
                        swarm.structured_events(child)
                    return swarm.has_event(swarm.peers['downloader'], 'COMPLETE')
                wait_for(all_alive_and_complete, timeout=60)
                swarm.complete('downloader', timeout=.1)
            proof = verify_installed_swarm(swarm, exe, executable_hash)
            write_json_new(swarm.root / 'installed-transfer-proof.json', proof)
            report['cases'].append({'size': size, 'status': 'PASS',
                'proof': str(swarm.root / 'installed-transfer-proof.json'),
                'proof_sha256': digest_file(swarm.root / 'installed-transfer-proof.json')})
            verify_installed_bytes(observed, spec, prefix)
        report['status'] = 'PASS'
    except PrerequisiteBlocked as exc:
        report.update(status='BLOCKED', reason=str(exc))
    except Exception:
        report.update(status='FAIL', exception=traceback.format_exc())
    finally:
        try:
            after = snapshot(repo)
            write_json_new(out / 'source-after.json', after)
            compare_snapshots(frozen, after)
            report['source_preserved'] = True
        except Exception:
            report.update(status='FAIL', source_preserved=False, source_exception=traceback.format_exc())
        report['files'] = [{'path': p.relative_to(out).as_posix(), 'sha256': digest_file(p), 'size': p.stat().st_size}
                           for p in sorted(out.rglob('*')) if p.is_file()]
        write_json_new(out / 'report.json', report)
    return report


def verify_installed_worker_report(root, kind, frozen):
    root = checked_path(root, strict=True)
    value = strict_json((root / 'report.json').read_bytes())
    if (value.get('stage') != 'installed-transfer-worker' or value.get('status') != 'PASS'
            or value.get('kind') != kind or value.get('source_sha256') != frozen['sha256']
            or value.get('source_preserved') is not True or value.get('source_isolation_verified') is not False
            or value.get('acceptance_eligible') is not False
            or [r['size'] for r in value['cases']] != list(INSTALLED_TRANSFER_SIZES)
            or any(r['status'] != 'PASS' for r in value['cases'])):
        raise ValueError('installed transfer worker results differ from exact diagnostic contract')
    names = set()
    for item in value['files']:
        rel = item['path']
        if not isinstance(rel, str) or Path(rel).is_absolute() or '..' in Path(rel).parts or rel in names:
            raise ValueError('invalid installed transfer artifact inventory')
        names.add(rel)
        path = checked_path(root / rel, strict=True)
        if not path.is_relative_to(root) or digest_file(path) != item['sha256'] or path.stat().st_size != item['size']:
            raise ValueError('installed transfer evidence artifact changed')
    actual = {checked_path(p, strict=True).relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    if actual != names | {'report.json'}:
        raise ValueError('installed transfer artifact inventory is incomplete')
    for case in value['cases']:
        proof = checked_path(case['proof'], strict=True)
        if not proof.is_relative_to(root) or digest_file(proof) != case['proof_sha256']:
            raise ValueError('installed transfer proof changed or escaped worker root')
    return value


def run_installed_transfer(packaging_root, out):
    packaging_root = checked_path(packaging_root, strict=True)
    prior = strict_json((packaging_root / 'report.json').read_bytes())
    repo, out = _fresh_out(checked_path(prior['source_root'], strict=True), out)
    frozen = snapshot(repo)
    write_json_new(out / 'source-before.json', frozen)
    report = {'schema': 1, 'stage': 'installed-real-transfer', 'status': 'NOT RUN',
              'acceptance_ready': False, 'source_isolation_verified': False,
              'source_sha256': frozen['sha256'], 'commands': [], 'installations': {},
              'packaging_report_sha256': digest_file(packaging_root / 'report.json'),
              'limitations': ['This is local diagnostic TCP evidence, with same-user source access.',
                              'Separate source-only supervisor imports test support; product children use installed -I interpreters.',
                              'Independent final acceptance verification and other OS/LAN/max-size cases remain separate.']}
    driver = None
    try:
        if not os.environ.get('ACCEPTANCE_PROCESS_REGISTRY'):
            raise PrerequisiteBlocked('installed-transfer stage requires an external recording guardian')
        driver = Driver(out, frozen)
        for kind in ('wheel', 'sdist'):
            prefix, exe, spec = installed_contract(packaging_root, kind, frozen)
            observed = strict_json(driver.run(kind + '-origins-before', [exe, '-I', '-c', PROBE_SOURCE,
                packaging_root / 'installed-spec.json', prefix],
                'Recheck installed core origins/resources and absence of installed test supervisor before TCP launch.'))
            verify_installed_bytes(observed, spec, prefix)
            driver.verified()
            origins = out / (kind + '-origins-before.json')
            write_json_new(origins, observed)
            worker = out / (kind + ' transfer worker \u03a9')
            driver.run(kind + '-actual-transfers', [sys.executable, '-I', '-m',
                'bittorrent_lite.acceptance_tools.portability', 'installed-worker', '--packaging-root', packaging_root,
                '--kind', kind, '--out', worker, '--origins', origins, '--origins-sha256', digest_file(origins),
                '--python-sha256', digest_file(exe)],
                'Actual installed tracker/seeder/downloader TCP transfers at 1,65536,524411 bytes, raw wire/ownership provenance, exact output bytes and owned cleanup.',
                timeout=300)
            checked = verify_installed_worker_report(worker, kind, frozen)
            driver.verified()
            after = strict_json(driver.run(kind + '-origins-after', [exe, '-I', '-c', PROBE_SOURCE,
                packaging_root / 'installed-spec.json', prefix], 'Installed core files/origins remain frozen after real execution.'))
            verify_installed_bytes(after, spec, prefix)
            driver.verified()
            report['installations'][kind] = {'status': checked['status'], 'worker_report': str(worker / 'report.json'),
                'worker_report_sha256': digest_file(worker / 'report.json'), 'sizes': list(INSTALLED_TRANSFER_SIZES)}
        report['status'] = 'PASS'
    except PrerequisiteBlocked as exc:
        report.update(status='BLOCKED', reason=str(exc))
    except Exception:
        report.update(status='FAIL', exception=traceback.format_exc())
    finally:
        if driver:
            report['commands'] = driver.commands
        try:
            after = snapshot(repo)
            write_json_new(out / 'source-after.json', after)
            compare_snapshots(frozen, after)
            report['source_preserved'] = True
        except Exception:
            report.update(status='FAIL', source_preserved=False, source_exception=traceback.format_exc())
        write_json_new(out / 'report.json', report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    stages = parser.add_subparsers(dest='stage', required=True)
    packaging = stages.add_parser('packaging')
    for option in ('repo', 'out', 'python', 'wheelhouse', 'wheel-lock'):
        packaging.add_argument('--' + option, type=Path, required=True)
    standalone = stages.add_parser('standalone')
    standalone.add_argument('--packaging-root', type=Path, required=True)
    standalone.add_argument('--out', type=Path, required=True)
    installed = stages.add_parser('installed-transfer')
    installed.add_argument('--packaging-root', type=Path, required=True)
    installed.add_argument('--out', type=Path, required=True)
    worker = stages.add_parser('installed-worker')
    for name in ('packaging-root', 'out', 'origins'):
        worker.add_argument('--' + name, type=Path, required=True)
    worker.add_argument('--kind', choices=('wheel', 'sdist'), required=True)
    worker.add_argument('--origins-sha256', required=True)
    worker.add_argument('--python-sha256', required=True)
    args = parser.parse_args(argv)
    if args.stage == 'packaging':
        report = run_packaging(args.repo, args.out, args.python, args.wheelhouse, args.wheel_lock)
    elif args.stage == 'standalone':
        report = run_standalone(args.packaging_root, args.out)
    elif args.stage == 'installed-transfer':
        report = run_installed_transfer(args.packaging_root, args.out)
    else:
        report = installed_transfer_worker(args.packaging_root, args.kind, args.out,
                                           args.origins, args.origins_sha256, args.python_sha256)
    print(json.dumps({'status': report['status'], 'acceptance_ready': False,
                      'report': str(args.out / 'report.json')}))
    return {'PASS': 0, 'FAIL': 1, 'BLOCKED': 2, 'NOT RUN': 2}[report['status']]


if __name__ == '__main__':
    raise SystemExit(main())
