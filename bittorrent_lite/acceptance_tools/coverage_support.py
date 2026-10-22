"""Explicit startup coverage for a designated disposable acceptance environment.

The hook is opt-in via BTL_COVERAGE_ROOT and COVERAGE_PROCESS_START. Every
interpreter gets its own data file and startup/final record. An abrupt kill
can leave a start without a finish; this is reported, never counted as flushed.
"""
from __future__ import annotations

import argparse
import atexit
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import uuid

from .inventory import checked_path, digest_file, write_json_new
from .evidence import strict_json

HOOK_NAME = 'bittorrent_acceptance_coverage.pth'
HOOK = ('import os; os.environ.get("BTL_COVERAGE_ROOT") and '
        '__import__("bittorrent_lite.acceptance_tools.coverage_support", '
        'fromlist=["startup"]).startup()\n')
_active = None


def install_hook(environment: Path, workspace: Path):
    """Only add a new hook to an explicitly named venv inside the workspace."""
    environment = checked_path(environment, strict=True)
    workspace = checked_path(workspace, strict=True)
    if not environment.is_relative_to(workspace) or not (environment / 'pyvenv.cfg').is_file():
        raise ValueError('coverage hook requires a disposable workspace venv')
    sites = [environment / 'Lib/site-packages'] if os.name == 'nt' else list(environment.glob('lib/python*/site-packages'))
    if len(sites) != 1 or not sites[0].is_dir():
        raise ValueError('exactly one environment site-packages directory is required')
    path = checked_path(sites[0] / HOOK_NAME)
    with path.open('x', encoding='utf-8', newline='\n') as handle:
        handle.write(HOOK)
    return {'path': str(path), 'sha256': digest_file(path)}


def write_config(path: Path, source: Path):
    source = checked_path(source, strict=True)
    path = checked_path(path)
    # No production module or pragma is excluded. Test code is the only omit.
    text = ('[run]\nbranch = True\nparallel = True\n'
            f'source =\n    {source.as_posix()}\n'
            'omit =\n    */bittorrent_lite/tests/*\n'
            '[report]\nexclude_lines =\n')
    with path.open('x', encoding='utf-8', newline='\n') as handle:
        handle.write(text)
    return {'path': str(path), 'sha256': digest_file(path)}


def startup():
    global _active
    if _active is not None:
        return
    try:
        import coverage
        import psutil
        root = checked_path(Path(os.environ['BTL_COVERAGE_ROOT']), strict=True)
        config = checked_path(Path(os.environ['COVERAGE_PROCESS_START']), strict=True)
        if not root.is_dir() or not config.is_file():
            raise ValueError('coverage output root/config missing')
        tag = f'{os.getpid()}-{uuid.uuid4().hex}'
        data_file = root / f'.coverage.{tag}'
        collector = coverage.Coverage(config_file=str(config), data_file=str(data_file), data_suffix=False)
        collector.start()
        _active = collector
        process = psutil.Process()
        start = {'schema': 'btl-coverage-v2', 'pid': os.getpid(), 'parent_pid': os.getppid(),
                 'creation_time': process.create_time(),
                 'executable': process.exe(), 'python_executable': sys.executable, 'argv': list(sys.argv),
                 'cwd': str(Path.cwd()), 'monotonic': time.monotonic(),
                 'data_file': data_file.name, 'config_sha256': digest_file(config),
                 'coverage_version': coverage.__version__, 'status': 'STARTED'}
        write_json_new(root / f'{tag}.start.json', start)
        def finish():
            try:
                collector.stop()
                collector.save()
                files = sorted(collector.get_data().measured_files())
                write_json_new(root / f'{tag}.finish.json', {
                    **start, 'status': 'FLUSHED', 'monotonic_end': time.monotonic(),
                    'measured_files': files, 'data_sha256': digest_file(data_file)})
            except BaseException as exc:
                # atexit errors otherwise do not fail the process; verifier must
                # reject this record even when the application exits zero.
                write_json_new(root / f'{tag}.error.json', {'status': 'ERROR', 'error': repr(exc)})
                raise
        atexit.register(finish)
    except BaseException:
        # Python prints .pth exceptions and otherwise continues. Fail closed.
        import traceback
        traceback.print_exc()
        sys.stderr.flush()
        os._exit(86)


def _identity(record):
    if (not isinstance(record, dict) or type(record.get('pid')) is not int or record['pid'] <= 0
            or type(record.get('creation_time')) not in (int, float)
            or not math.isfinite(record['creation_time']) or record['creation_time'] <= 0
            or not isinstance(record.get('executable'), str)
            or not Path(record['executable']).is_absolute()):
        raise ValueError('invalid expected/recorded process identity')
    return (record['pid'], record['creation_time'],
            os.path.normcase(str(Path(record['executable']).resolve())))


def _read_reference(reference):
    if not isinstance(reference, dict) or set(reference) != {'path', 'sha256'}:
        raise ValueError('termination evidence requires a path and independently frozen hash')
    if not isinstance(reference['path'], str) or not Path(reference['path']).is_absolute():
        raise ValueError('termination evidence reference must be an absolute internal record path')
    path = checked_path(Path(reference['path']), strict=True)
    if (not isinstance(reference['sha256'], str)
            or not re.fullmatch('[0-9a-f]{64}', reference['sha256'])
            or digest_file(path) != reference['sha256']):
        raise ValueError('termination evidence hash mismatch')
    return strict_json(path.read_bytes())


def _termination_specs(items, expected):
    result = {}
    for item in items:
        if not isinstance(item, dict) or set(item) != {'identity', 'declaration', 'observation'}:
            raise ValueError('invalid expected termination entry')
        key = _identity(item['identity'])
        if key not in expected or key in result:
            raise ValueError('unexpected or duplicate deliberate termination identity')
        declaration = _read_reference(item['declaration'])
        observation = _read_reference(item['observation'])
        if (not isinstance(declaration, dict) or not isinstance(observation, dict)
                or declaration.get('schema') != 'btl-coverage-termination-plan-v1'
                or not isinstance(declaration.get('case_id'), str) or not declaration['case_id']
                or not isinstance(declaration.get('process_role'), str) or not declaration['process_role']
                or expected[key].get('case_id') != declaration['case_id']
                or expected[key].get('coverage_role') != declaration['process_role']
                or type(declaration.get('declared_at_monotonic')) not in (int, float)
                or not math.isfinite(declaration['declared_at_monotonic'])
                or declaration.get('termination_kind') != 'forced'
                or observation.get('schema') != 'btl-coverage-termination-observation-v1'
                or observation.get('case_id') != declaration['case_id']
                or observation.get('process_role') != declaration['process_role']
                or observation.get('termination_kind') != 'forced'
                or _identity(observation.get('identity', {})) != key
                or observation.get('exit_confirmed') is not True
                or type(observation.get('exit_code')) is not int
                or type(observation.get('observed_at_monotonic')) not in (int, float)
                or not math.isfinite(observation['observed_at_monotonic'])):
            raise ValueError('unverified deliberate termination declaration/observation')
        result[key] = (item, declaration, observation)
    return result


def inspect_participation(root: Path, *, expected_processes, config: Path,
                          config_sha256: str, expected_sources: dict,
                          coverage_version: str, expected_terminations=()):
    """Reconcile exact OS interpreter identities with frozen config/source bytes.

The caller obtains expected_processes from the independent guardian/process
registry, not the coverage starts being checked. Native Windows venv redirectors
are not executing Python interpreters; their real interpreter descendants must
be reconciled explicitly. Expected terminations require predeclared, separately
hashed evidence and return INTERRUPTED_NOT_COUNTED, never FLUSHED coverage.
This checks participation, not completeness of behavioral/module coverage.
"""
    from coverage import CoverageData
    root = checked_path(root, strict=True)
    config = checked_path(config, strict=True)
    if (not isinstance(config_sha256, str) or not re.fullmatch('[0-9a-f]{64}', config_sha256)
            or digest_file(config) != config_sha256):
        raise ValueError('frozen coverage config differs')
    if not isinstance(coverage_version, str) or not coverage_version:
        raise ValueError('pinned coverage version is required')
    expected = {}
    for process in expected_processes:
        key = _identity(process)
        if key in expected:
            raise ValueError('duplicate expected interpreter identity')
        expected[key] = process
    if not expected:
        raise ValueError('expected interpreter inventory is empty')
    sources = {}
    for filename, digest in expected_sources.items():
        path = checked_path(Path(filename), strict=True)
        name = os.path.normcase(str(path))
        if (not Path(filename).is_absolute() or name in sources
                or not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest)
                or digest_file(path) != digest):
            raise ValueError('frozen coverage source inventory differs')
        sources[name] = digest
    if not sources:
        raise ValueError('expected source inventory is empty')
    terminations = _termination_specs(expected_terminations, expected)
    entries = {}
    for path in root.iterdir():
        checked = checked_path(path, strict=True)
        if not checked.is_file():
            raise ValueError('coverage directory may contain only regular evidence files')
        entries[path.name] = checked
    starts = sorted(root.glob('*.start.json'))
    if not starts:
        raise ValueError('no covered interpreter starts')
    result = []
    used_files, identities = set(), set()
    for start_path in starts:
        tag = start_path.name.removesuffix('.start.json')
        start = strict_json(entries[start_path.name].read_bytes())
        key = _identity(start)
        if (start.get('schema') != 'btl-coverage-v2' or start.get('status') != 'STARTED'
                or key not in expected or key in identities
                or not re.fullmatch(str(start['pid']) + '-[0-9a-f]{32}', tag)
                or start.get('config_sha256') != config_sha256
                or start.get('coverage_version') != coverage_version
                or type(start.get('monotonic')) not in (int, float)
                or not math.isfinite(start['monotonic'])):
            raise ValueError('unexpected/duplicate coverage identity, config or version')
        identities.add(key)
        name = start.get('data_file')
        if name != '.coverage.' + tag:
            raise ValueError('invalid or reused coverage data filename')
        used_files.add(start_path.name)
        finish_path = root / f'{tag}.finish.json'
        if f'{tag}.error.json' in entries:
            raise ValueError(f'coverage did not flush: {tag}; explicit collector error')
        if key in terminations:
            item, declaration, observation = terminations[key]
            if (finish_path.name in entries or declaration['declared_at_monotonic'] > start['monotonic']
                    or observation['observed_at_monotonic'] < start['monotonic']):
                raise ValueError('deliberate abrupt termination timing/flush evidence differs')
            interrupted_files = {}
            for suffix in ('', '-journal', '-wal', '-shm'):
                if name + suffix in entries:
                    used_files.add(name + suffix)
                    interrupted_files[name + suffix] = digest_file(entries[name + suffix])
            result.append({**start, 'status': 'INTERRUPTED_NOT_COUNTED',
                           'termination_evidence': item, 'interrupted_files': interrupted_files,
                           'executed_lines': {}, 'executed_arcs': {}})
            continue
        if finish_path.name not in entries:
            raise ValueError(f'coverage did not flush: {tag}')
        finish = strict_json(entries[finish_path.name].read_bytes())
        for field, value in start.items():
            if field != 'status' and finish.get(field) != value:
                raise ValueError(f'coverage identity changed: {tag}/{field}')
        if name not in entries:
            raise ValueError(f'coverage database is missing: {tag}')
        data_path = entries[name]
        if (finish['status'] != 'FLUSHED' or digest_file(data_path) != finish['data_sha256']
                or type(finish.get('monotonic_end')) not in (int, float)
                or not math.isfinite(finish['monotonic_end'])
                or finish['monotonic_end'] < start['monotonic']):
            raise ValueError(f'coverage data mismatch: {tag}')
        data = CoverageData(basename=str(data_path))
        data.read()
        files = sorted(data.measured_files())
        if files != finish['measured_files'] or not data.has_arcs():
            raise ValueError(f'coverage file/branch mismatch: {tag}')
        for filename in files:
            if not Path(filename).is_absolute() or os.path.normcase(str(checked_path(Path(filename), strict=True))) not in sources:
                raise ValueError(f'coverage measured an unfrozen source: {filename}')
        if digest_file(data_path) != finish['data_sha256']:
            raise ValueError('coverage database changed during inspection')
        used_files.update((finish_path.name, name))
        result.append({**finish, 'executed_lines': {p: sorted(data.lines(p) or []) for p in files},
                       'executed_arcs': {p: sorted(data.arcs(p) or []) for p in files}})
    if identities != set(expected):
        raise ValueError('registered interpreter missing coverage start')
    if set(entries) != used_files:
        raise ValueError(f'unmatched or stale coverage evidence: {sorted(set(entries) - used_files)}')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--environment', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(install_hook(args.environment, args.workspace)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
