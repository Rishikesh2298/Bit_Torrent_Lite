"""Process supervision only: never supplies download bytes or schedules pieces."""
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import random
import re
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone

from bittorrent_lite.storage.metadata import create_metadata, save_metadata


CONSOLE_LINE = re.compile(r"^\[\d{2}:\d{2}:\d{2}\] \[[^\]\r\n]+\] (?:DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+.*$")


def _stamp():
    return {"utc": datetime.now(timezone.utc).isoformat(), "monotonic": time.monotonic()}


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _same_bytes(first, second):
    with Path(first).open('rb') as left, Path(second).open('rb') as right:
        while True:
            a, b = left.read(1024 * 1024), right.read(1024 * 1024)
            if a != b:
                return False
            if not a:
                return True


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key {key!r}')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError(f'nonfinite JSON constant {value}')


def _finite_float(value):
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f'nonfinite JSON number {value}')
    return parsed


def _register_child(registry, proc, *, owner_run, role, stop_file):
    # The optional acceptance dependency is not imported for ordinary use.
    from bittorrent_lite.acceptance_tools.recording import register_process
    return register_process(registry, proc.pid, owner_run=owner_run, role=role,
                            stop_file=stop_file)


def observe_interpreter(child, launch, registry):
    """Bind a recorded launcher to its actual live Python interpreter.

    Windows venv launchers can be a native parent of the interpreter. Captured
    process birth identities and verified ancestry authorize later cleanup.
    """
    import psutil
    from bittorrent_lite.acceptance_tools.inventory import checked_path
    from bittorrent_lite.acceptance_tools.recording import (
        matching_process, observed_child_identity, register_process)
    prior = child.get('interpreter_observation')
    if prior is not None:
        if (matching_process(child['identity']) is None
                or matching_process(prior['identity']) is None):
            raise ValueError('captured interpreter/launcher disappeared before reuse')
        return prior
    parent = matching_process(child['identity'])
    if parent is None:
        raise ValueError('owned launcher disappeared before interpreter observation')
    candidates = []
    for process in [parent, *parent.children(recursive=True)]:
        try:
            identity = observed_child_identity(process)
            if identity is None:
                continue
            env = process.environ()
            if (identity['arguments'][1:] == launch['command'][1:]
                    and env.get('BTL_PROC_ID') == child['proc_id']
                    and env.get('BTL_LOG_STRICT') == '1'
                    and checked_path(env['BTL_EVENT_LOG']) == child['events']):
                candidates.append((process, identity, env))
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
    parent_ids = {identity['parent_pid'] for _, identity, _ in candidates}
    leaves = [item for item in candidates if item[1]['pid'] not in parent_ids]
    if len(leaves) != 1:
        raise ValueError('cannot uniquely identify actual strict-log interpreter')
    process, identity, env = leaves[0]
    chain = [process]
    while chain[-1].pid != parent.pid:
        ancestor = chain[-1].parent()
        if ancestor is None or len(chain) > 8:
            raise ValueError('interpreter ancestry does not reach owned launcher')
        chain.append(ancestor)
    registered = [child['identity']]
    for member in reversed(chain[:-1]):
        observed = observed_child_identity(member)
        if observed is None:
            raise ValueError('interpreter ancestry changed during registration')
        registered.append(register_process(registry, member.pid, owner_run=env['BTL_RUN_ID'],
            role=child['name'] + '-interpreter', stop_file=child['stop'], expected_identity=observed))
    if any(registered[-1][key] != identity[key] for key in ('pid', 'creation_time', 'executable')):
        raise ValueError('observed interpreter differs from registered identity')
    observation = {'proc_id': child['proc_id'], 'name': child['name'], 'identity': registered[-1],
                   'ancestry': registered, 'observed_mono': time.monotonic(),
                   'method': 'live-owned-tree-argv-environment', 'events': child['events'].name}
    child['interpreter'] = registered[-1]
    child['interpreter_observation'] = observation
    return observation


def termination_contract(child, operation, *, platform=None):
    """Predeclare the exact API/exit oracle before issuing a forced operation."""
    if operation not in {'terminate', 'kill'}:
        raise ValueError('unknown forced termination operation')
    platform = os.name if platform is None else platform
    api = 'psutil.Process' if child.get('identity') is not None else 'subprocess.Popen'
    if platform == 'nt':
        # Pinned psutil 7.2.2 uses TerminateProcess(..., SIGTERM), including kill.
        # Python's subprocess.Popen uses TerminateProcess(..., 1).
        expected = [15 if api == 'psutil.Process' else 1]
    elif operation == 'kill':
        expected = [-signal.SIGKILL]
    else:
        expected = [0, -signal.SIGTERM]  # Tracker may handle SIGTERM gracefully.
    return {'api': api + '.' + operation, 'platform': platform,
            'expected_exit_codes': expected}


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def wait_for(predicate, timeout=40):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.05)
    raise AssertionError(f'condition did not become true within {timeout}s')


class Swarm:
    def __init__(self, root, size=65536 * 8 + 123, *, fixture_seed=0,
                 python_executable=None, python_sha256=None, isolated=False):
        if type(size) is not int or not 1 <= size <= 64 * 1024 * 1024:
            raise ValueError('fixture size must be between 1 byte and 64 MiB')
        if type(fixture_seed) is not int:
            raise ValueError('fixture_seed must be an integer')
        if type(isolated) is not bool:
            raise ValueError('isolated must be a boolean')
        if python_executable is None:
            if python_sha256 is not None or isolated:
                raise ValueError('isolated execution requires an explicitly verified interpreter')
            self.python_executable, self.python_sha256 = sys.executable, None
        else:
            from bittorrent_lite.acceptance_tools.inventory import checked_path
            candidate = Path(python_executable)
            if (not candidate.is_absolute() or not isinstance(python_sha256, str)
                    or not re.fullmatch(r'[0-9a-f]{64}', python_sha256)):
                raise ValueError('absolute interpreter and exact SHA-256 required')
            candidate = checked_path(candidate, strict=True)
            if not candidate.is_file() or _hash(candidate) != python_sha256:
                raise ValueError('explicit interpreter bytes differ')
            self.python_executable, self.python_sha256 = str(candidate), python_sha256
        self.isolated = isolated
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.source = self.root / 'original bytes.bin'
        rng = random.Random(fixture_seed)
        piece_digests = []
        with self.source.open('xb') as handle:
            for index, offset in enumerate(range(0, size, 65536)):
                block = bytearray(rng.randbytes(min(65536, size - offset)))
                if len(block) >= 16:
                    block[:8] = index.to_bytes(8, 'big')
                    block[-8:] = hashlib.sha256(b'piece-end' + index.to_bytes(8, 'big')).digest()[:8]
                handle.write(block)
                piece_digests.append(hashlib.sha256(block).hexdigest())
        self.size = size
        self.digest = _hash(self.source)
        self.meta = self.root / 'shared metadata.json'
        save_metadata(create_metadata(str(self.source)), str(self.meta))
        self.children = []
        self.peers = {}
        self.tracker_port = free_port()
        self.tracker = None
        self.env = os.environ.copy()
        self.env.pop('PYTHONPATH', None)
        registry = self.env.get('ACCEPTANCE_PROCESS_REGISTRY')
        if registry:
            registry_mode = 'inherited'
        else:
            # Plain pytest still needs actual-interpreter ownership on Windows.
            # This local registry is not a crash-survival process guardian.
            local_registry = self.root / 'owned-processes'
            local_registry.mkdir(exist_ok=False)
            registry = str(local_registry)
            self.env['ACCEPTANCE_PROCESS_REGISTRY'] = registry
            registry_mode = 'local-no-guardian'
        self.process_supervision = {'registry': registry, 'registry_mode': registry_mode,
                                    'guardian_verification': 'NOT VERIFIED BY SWARM',
                                    'acceptance_requires_external_recorder': True}
        with (self.root / 'process-supervision.json').open('x', encoding='utf-8') as handle:
            json.dump(self.process_supervision, handle, indent=2)
        self.launches = []
        self.actions = []
        self.fixture_provenance = {'mode': 'diagnostic', 'fixture_seed': fixture_seed,
                                   'acceptance_challenge': None, 'acceptance_eligible': False,
                                   'size': size, 'sha256': self.digest,
                                   'piece_sha256': piece_digests,
                                   'source_isolation_verified': False}
        (self.root / 'fixture.json').write_text(json.dumps(self.fixture_provenance, indent=2), encoding='utf-8')

    def _action(self, child, action, **fields):
        record = {'action': action, 'name': child['name'], 'pid': child['proc'].pid,
                  'identity': child.get('identity'), **_stamp(), **fields}
        self.actions.append(record)
        with (self.root / 'process-actions.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(record, allow_nan=False) + '\n')

    def _owned_alive(self, child):
        assert child['proc'].poll() is None, f"{child['name']} already exited"
        if child.get('identity') is not None:
            from bittorrent_lite.acceptance_tools.recording import matching_process
            assert matching_process(child['identity']) is not None, 'process identity changed; refusing signal'
            assert child.get('interpreter') is not None, 'actual interpreter was not captured; refusing signal'
            actual = matching_process(child['interpreter'])
            assert actual is not None, 'interpreter identity changed; refusing signal'
            return actual
        return child['proc']

    def _capture_interpreter(self, child):
        if child.get('identity') is None:
            return  # Ordinary unrecorded helper use does not claim OS identity evidence.
        launch = next(row for row in self.launches if row['proc_id'] == child['proc_id'])
        observation = observe_interpreter(child, launch, self.env['ACCEPTANCE_PROCESS_REGISTRY'])
        launch['interpreter_observation'] = observation
        (self.root / 'launches.json').write_text(json.dumps(self.launches, indent=2), encoding='utf-8')
        self._action(child, 'interpreter_observed', observation=observation)
        events = self.structured_events(child)
        assert all(row.get('log_pid') == observation['identity']['pid'] for row in events), 'logged interpreter PID differs'

    def _wait_owned_exit(self, child, actual, timeout):
        """Record actual and wrapper exits without inferring missing exit codes."""
        deadline = time.monotonic() + timeout
        if actual.pid == child['proc'].pid:
            code = child['proc'].wait(timeout)
        else:
            import psutil
            try:
                code = actual.wait(timeout)
            except psutil.TimeoutExpired as exc:
                raise subprocess.TimeoutExpired(child['name'], timeout) from exc
            assert type(code) is int, 'actual interpreter exit status is unavailable'
            wrapper = child['proc'].wait(max(.001, deadline - time.monotonic()))
            assert type(wrapper) is int, 'launcher exit status is unavailable'
            assert wrapper == code, f'launcher exit {wrapper} differs from actual interpreter exit {code}'
        assert type(code) is int, 'process exit status is unavailable'
        child['interpreter_exit_code'] = code
        if child.get('interpreter') is not None:
            from bittorrent_lite.acceptance_tools.recording import matching_process
            assert matching_process(child['interpreter']) is None, 'actual interpreter remains alive after exit'
        return code

    def launch(self, name, args, *, stop_file=None, teardown=None):
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', name):
            raise ValueError('child name must be a safe label')
        label = f'{len(self.children):02d}-{name}'
        out, err = self.root / (label + '.stdout'), self.root / (label + '.stderr')
        events = self.root / (label + '.events.jsonl')
        if self.python_sha256 is not None and _hash(Path(self.python_executable)) != self.python_sha256:
            raise ValueError('explicit interpreter changed before launch')
        # -I ignores PYTHON* environment variables, so pass UTF-8 as an actual
        # interpreter option when isolated installed execution is requested.
        command = [self.python_executable, *(['-I', '-X', 'utf8'] if self.isolated else []), '-m', *args]
        environment = dict(self.env, BTL_EVENT_LOG=str(events), BTL_PROC_ID=label,
                           BTL_RUN_ID=self.env.get('BTL_RUN_ID', self.root.name),
                           BTL_LOG_STRICT='1',
                           PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
        with out.open('xb') as stdout, err.open('xb') as stderr:
            proc = subprocess.Popen(command, cwd=self.root, env=environment, stdout=stdout, stderr=stderr)
            child = {'proc': proc, 'out': out, 'err': err, 'events': events, 'name': name,
                     'proc_id': label, 'stop': stop_file, 'teardown': teardown,
                     'deliberate_kill': False, 'identity': None, 'tails': {}, 'strict_log': True}
            self.children.append(child)  # Retain cleanup authority even if registration fails.
            registry = environment.get('ACCEPTANCE_PROCESS_REGISTRY')
            try:
                if registry:
                    child['identity'] = _register_child(
                        registry, proc, owner_run=environment['BTL_RUN_ID'], role=name,
                        stop_file=stop_file)
            except Exception:
                self._action(child, 'registration_failed')
                raise
        self.launches.append({'name': name, 'pid': proc.pid, 'command': command,
                              'isolated': self.isolated, 'python_sha256': self.python_sha256,
                              'identity': child['identity'], 'stop_file': str(stop_file) if stop_file else None,
                              'stdout': str(out), 'stderr': str(err), 'events': str(events),
                              'proc_id': label, 'teardown': teardown, **_stamp()})
        self.launches[-1]['stream_encoding'] = 'utf-8'
        (self.root / 'launches.json').write_text(json.dumps(self.launches, indent=2), encoding='utf-8')
        return child

    def start_tracker(self):
        self.tracker = self.launch('tracker', ['bittorrent_lite.discovery.tracker_server',
                                             '--host', '127.0.0.1', '--port', str(self.tracker_port)],
                                   teardown='declared_tracker_platform_termination')
        def ready():
            self.check(self.tracker)
            if not any(e['event'] == 'tracker_ready' for e in self.structured_events(self.tracker)):
                return False
            try:
                self._probe_tracker()
                return True
            except OSError:
                return False
        wait_for(ready, 10)
        self._capture_interpreter(self.tracker)

    def _probe_tracker(self):
        """Prove HTTP behavior as well as a logged listening event, with no member added."""
        request = json.dumps({'file_id': '0' * 64, 'peer_id': 'readiness-probe',
                              'listen_port': 1, 'event': 'stopped'}, separators=(',', ':')).encode()
        connection = http.client.HTTPConnection('127.0.0.1', self.tracker_port, timeout=.5)
        try:
            connection.request('POST', '/announce', body=request,
                               headers={'Content-Type': 'application/json'})
            response = connection.getresponse()
            raw = response.read(65537)
            record = {'request_hex': request.hex(), 'response_hex': raw.hex(),
                      'status': response.status, 'host': '127.0.0.1',
                      'port': self.tracker_port, **_stamp()}
            with (self.root / 'tracker-readiness.jsonl').open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(record) + '\n')
            assert response.status == 200 and len(raw) <= 65536, record
            parsed = json.loads(raw.decode('utf-8'), object_pairs_hook=_strict_object,
                                parse_constant=_invalid_constant, parse_float=_finite_float)
            assert parsed == {'interval': 5, 'peers': []}, parsed
        finally:
            connection.close()

    def start_peer(self, name, *, seed=False, strategy='rarest-first', window=4,
                   free_rider=False, workers=0, port=None):
        port = port or free_port()
        stop = self.root / f'{len(self.children):02d}-{name}.stop'
        args = ['bittorrent_lite', '--peer-id', name, '--host', '127.0.0.1', '--port', str(port),
                '--tracker', f'http://127.0.0.1:{self.tracker_port}', '--metadata', str(self.meta),
                '--output-dir', str(self.root / 'downloads'), '--stop-file', str(stop),
                '--strategy', strategy, '--window', str(window), '--seed', '42',
                '--upload-workers', str(workers)]
        if seed:
            args += ['--seeder', '--file', str(self.source)]
        if free_rider:
            args += ['--free-rider']
        child = self.launch(name, args, stop_file=stop)
        child.update(stop=stop, port=port)
        self.peers[name] = child
        wait_for(lambda: self.has_event(child, 'START'), 10)
        self._capture_interpreter(child)
        return child

    def check(self, child):
        assert child['proc'].poll() is None, f"{child['name']} exited {child['proc'].returncode}: {child['err'].read_text()}"

    def _events(self, child, path, *, structured):
        result = []
        if not path.exists():
            assert child['proc'].poll() is None, f'missing event evidence: {path}'
            return result
        raw = path.read_bytes()
        lines = raw.split(b'\n')
        tail = lines.pop()
        if tail:
            alive = child['proc'].poll() is None
            assert alive or child['deliberate_kill'], f'incomplete final record in {path}'
            if not alive:
                child['tails'][path.name] = {'bytes': len(tail), 'offset': len(raw) - len(tail),
                                             'reason': 'declared_kill_incomplete_tail'}
        for number, encoded in enumerate(lines, 1):
            line = encoded.decode('utf-8').removesuffix('\r')
            if not structured and CONSOLE_LINE.fullmatch(line):
                continue
            try:
                record = json.loads(line, object_pairs_hook=_strict_object,
                                    parse_constant=_invalid_constant, parse_float=_finite_float)
            except (ValueError, RecursionError) as exc:
                raise AssertionError(f'malformed complete record {path}:{number}: {exc}') from exc
            assert isinstance(record, dict) and isinstance(record.get('event'), str), f'invalid event record {path}:{number}'
            if structured:
                assert type(record.get('mono')) in (int, float) and record['mono'] >= 0, f'missing monotonic time {path}:{number}'
                assert record.get('proc') == child['proc_id'], f'wrong process identity {path}:{number}'
                assert not result or record['mono'] >= result[-1]['mono'], f'time regression {path}:{number}'
                if child.get('strict_log'):
                    assert record.get('log_schema') == 'btl-log-v1', f'missing strict log schema {path}:{number}'
                    assert type(record.get('log_sequence')) is int and record['log_sequence'] == number - 1, f'event gap {path}:{number}'
                    assert type(record.get('log_pid')) is int and record['log_pid'] > 0, f'missing interpreter PID {path}:{number}'
                    assert not result or record['log_pid'] == result[0]['log_pid'], f'interpreter changed {path}:{number}'
                    if child.get('interpreter') is not None:
                        assert record['log_pid'] == child['interpreter']['pid'], f'wrong observed interpreter PID {path}:{number}'
            result.append(record)
        return result

    def events(self, child):
        """Strict public CLI records, preserving existing uppercase API events."""
        return self._events(child, child['out'], structured=False)

    def structured_events(self, child):
        """Canonical dedicated metrics stream; console text is never accepted."""
        return self._events(child, child['events'], structured=True)

    def has_event(self, child, name):
        self.check(child)
        return any(e.get('event') == name for e in self.events(child))

    def complete(self, name, timeout=60):
        child = self.peers[name]
        wait_for(lambda: self.has_event(child, 'COMPLETE'), timeout)
        output = self.root / 'downloads' / name / self.source.name
        assert output.stat().st_size == self.size
        assert _hash(output) == self.digest
        source_available = self.source.is_file()
        if source_available:
            assert _same_bytes(self.source, output), 'output differs byte-for-byte from source'
        self._action(child, 'output_verified', output=str(output), size=output.stat().st_size,
                     sha256=_hash(output), source_byte_comparison=source_available,
                     source_isolation_verified=False)
        assert sum(e.get('event') == 'COMPLETE' for e in self.events(child)) == 1
        return output

    def stop_peer(self, name):
        child = self.peers[name]
        actual = self._owned_alive(child)
        self._action(child, 'cooperative_stop_requested', stop_file=str(child['stop']))
        child['stop'].touch()
        assert self._wait_owned_exit(child, actual, 10) == 0, child['err'].read_text()
        stopped = [e for e in self.events(child) if e.get('event') == 'STOPPED']
        assert len(stopped) == 1 and stopped[0]['errors'] == [], stopped
        assert 'Traceback' not in child['err'].read_text()
        structured = self.structured_events(child)
        assert sum(e['event'] == 'exit' for e in structured) == 1
        assert [e for e in structured if e['event'] == 'exit'][0]['reason'] == 'stopped'
        self._action(child, 'normal_exit', exit_code=0)
        return stopped[0]

    def kill(self, child):
        actual = self._owned_alive(child)
        contract = termination_contract(child, 'kill')
        child['termination_contract'] = contract
        self._action(child, 'deliberate_crash_requested', signal='TerminateProcess' if os.name == 'nt' else 'SIGKILL',
                     target_identity=child.get('interpreter') or child.get('identity'),
                     mechanism=contract['api'], expected_exit_codes=contract['expected_exit_codes'])
        actual.kill()
        code = self._wait_owned_exit(child, actual, 5)
        expected, = contract['expected_exit_codes']
        assert code == expected, f'declared kill returned unexpected exit {code}'
        child['deliberate_kill'] = True
        child['expected_exit_code'] = code
        self._action(child, 'deliberate_crash_completed', exit_code=code)
        self.events(child)
        self.structured_events(child)

    def close(self):
        errors = []
        for name, child in self.peers.items():
            if child['proc'].poll() is None:
                try:
                    self.stop_peer(name)
                except Exception as exc:
                    errors.append(str(exc))
        for child in self.children:
            if child['proc'].poll() is None:
                try:
                    actual = self._owned_alive(child)
                except Exception as exc:
                    errors.append(str(exc))
                    continue
                declared = child['teardown'] == 'declared_tracker_platform_termination'
                contract = termination_contract(child, 'terminate')
                child['termination_contract'] = contract
                self._action(child, 'tracker_teardown_requested' if declared else 'forced_cleanup_failure',
                             signal='TerminateProcess' if os.name == 'nt' else 'SIGTERM',
                             target_identity=child.get('interpreter') or child.get('identity'),
                             mechanism=contract['api'], expected_exit_codes=contract['expected_exit_codes'])
                try:
                    # Terminating a Windows native venv redirector alone leaves
                    # its Python child alive. Signal only the captured actual
                    # interpreter; its native parent then returns the same code.
                    actual.terminate()
                    try:
                        self._wait_owned_exit(child, actual, 5)
                    except subprocess.TimeoutExpired:
                        errors.append(f"{child['name']} required forced kill after termination timeout")
                        actual = self._owned_alive(child)
                        kill_contract = termination_contract(child, 'kill')
                        self._action(child, 'forced_kill_after_cleanup_timeout',
                                     target_identity=child.get('interpreter') or child.get('identity'),
                                     mechanism=kill_contract['api'], expected_exit_codes=kill_contract['expected_exit_codes'])
                        actual.kill()
                        self._wait_owned_exit(child, actual, 5)
                except Exception as exc:
                    errors.append(f"{child['name']} cleanup failed: {exc}")
                    continue
                if declared:
                    expected = contract['expected_exit_codes']
                    if child['proc'].returncode not in expected:
                        errors.append(f"tracker teardown exit {child['proc'].returncode} not in {expected}")
                    else:
                        child['expected_exit_code'] = child['proc'].returncode
                    # TerminateProcess may cut a final line; preserve/declare it.
                    child['deliberate_kill'] = child['proc'].returncode != 0
                    self._action(child, 'tracker_teardown_completed', exit_code=child['proc'].returncode)
                else:
                    errors.append(f"ordinary peer {child['name']} required forced cleanup")
            expected = child.get('expected_exit_code', 0)
            if child['proc'].returncode != expected:
                errors.append(f"{child['name']} unexpected exit {child['proc'].returncode}; expected {expected}")
            if child.get('interpreter') is not None:
                from bittorrent_lite.acceptance_tools.recording import matching_process
                if matching_process(child['interpreter']) is not None:
                    errors.append(f"{child['name']} actual interpreter remains alive")
            try:
                public = self.events(child)
                structured = self.structured_events(child)
                assert structured, f"empty structured evidence for {child['name']}"
                assert 'Traceback' not in child['err'].read_text(encoding='utf-8'), f"traceback in {child['name']} stderr"
                if child['stop'] is not None and not child['deliberate_kill']:
                    stopped = [e for e in public if e['event'] == 'STOPPED']
                    assert len(stopped) == 1 and stopped[0]['errors'] == [], stopped
                    exits = [e for e in structured if e['event'] == 'exit']
                    assert len(exits) == 1 and exits[0]['reason'] == 'stopped', exits
                if child['teardown'] == 'declared_tracker_platform_termination':
                    assert sum(e['event'] == 'tracker_ready' for e in structured) == 1
                    if child['proc'].returncode == 0:
                        exits = [e for e in structured if e['event'] == 'exit']
                        assert len(exits) == 1 and exits[0]['reason'] == 'stopped', exits
            except Exception as exc:
                errors.append(str(exc))
        (self.root / 'results.json').write_text(json.dumps({
            'size': self.size, 'sha256': self.digest,
            'fixture': self.fixture_provenance,
            'processes': [{'name': c['name'], 'pid': c['proc'].pid, 'identity': c['identity'],
                           'interpreter': c.get('interpreter'), 'interpreter_exit_code': c.get('interpreter_exit_code'),
                           'termination_contract': c.get('termination_contract'),
                           'exit_code': c['proc'].returncode, 'expected_exit_code': c.get('expected_exit_code', 0),
                           'deliberate_kill': c['deliberate_kill'], 'tails': c['tails']} for c in self.children],
            'cleanup_errors': errors}, indent=2))
        assert not errors, errors

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
