"""Real finite process-tree negative control; no application-launcher credit.

The only declared abnormal exit is this fixture's supervisor os._exit(17).
The guardian starts while that supervisor lives. Worker and grandchild use
registered cooperative stop files and must leave their original raw logs.
Windows read-only handles preserve actual exit statuses before reparenting;
POSIX cannot portably obtain a non-child wait status, which is recorded as an
explicit evidence limitation, never invented as zero. No process is launched
by merely importing or collecting this module.
"""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import time
import uuid

import pytest

from bittorrent_lite.acceptance_tools import recording


# These files are written only into a fresh owned evidence directory. All three
# fixture programs are finite and all process creation is immediately followed
# by explicit registration. The guardian itself watches only the worker tree.
COMMON = r'''
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

case = Path(sys.argv[1]).resolve()
recording_path = Path(sys.argv[2]).resolve()
spec = importlib.util.spec_from_file_location('fixture_recording', recording_path)
recording = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recording)
flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
environment_contract = json.loads((case / 'expected-crash.json').read_text(encoding='utf-8'))
psutil_module = Path(recording.psutil.__file__).resolve()
if (psutil_module != Path(environment_contract['psutil_module'])
        or hashlib.sha256(psutil_module.read_bytes()).hexdigest() != environment_contract['psutil_module_sha256']):
    raise RuntimeError('fixture imported a different psutil package than its parent')
if Path(recording.process_identity(os.getpid())['executable']).resolve() != Path(environment_contract['actual_executable']):
    raise RuntimeError('fixture did not use its declared direct interpreter')

def register(pid, role, stop_file, watched=True):
    observed = recording.process_identity(pid)
    identity = recording.register_process(case / 'fixture-owned', pid,
        owner_run='guardian-crash-negative-control', role=role, stop_file=stop_file,
        expected_identity=observed)
    if watched:
        recording.register_process(case / 'processes', pid,
            owner_run='guardian-crash-negative-control', role=role, stop_file=stop_file,
            expected_identity=identity)
    outer = os.environ.get('ACCEPTANCE_PROCESS_REGISTRY')
    if outer and Path(outer).resolve() not in ((case / 'fixture-owned').resolve(),
                                              (case / 'processes').resolve()):
        recording.register_process(outer, pid, owner_run='guardian-crash-negative-control',
                                   role=role, stop_file=stop_file, expected_identity=identity)
    return identity

def read_complete(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        return None

def raw(stdout, stderr=b''):
    sys.stdout.buffer.write(stdout)
    sys.stdout.buffer.flush()
    sys.stderr.buffer.write(stderr)
    sys.stderr.buffer.flush()
'''

GRANDCHILD = COMMON + r'''
raw(b'grandchild-start\x00\xff\n', b'grandchild-stderr\x80\n')
recording._write_new(case / 'grandchild-ready.json',
                     {'identity': recording.process_identity(os.getpid()), 'at': recording._times()})
deadline = time.monotonic() + 45
while not (case / 'grandchild.stop').exists():
    if time.monotonic() >= deadline:
        raise RuntimeError('finite grandchild lifetime exceeded without guardian stop')
    time.sleep(.02)
raw(b'grandchild-stopped\n')
'''

WORKER = COMMON + r'''
raw(b'worker-start\x00\xff\n', b'worker-stderr\x80\n')
child = None
identity = None
with (case / 'grandchild.stdout.bin').open('xb') as stdout, \
     (case / 'grandchild.stderr.bin').open('xb') as stderr:
    try:
        child = subprocess.Popen([sys.executable, str(case / 'grandchild.py'),
                                  str(case), str(recording_path)],
            cwd=case, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
            creationflags=flags)
        identity = register(child.pid, 'fixture-grandchild', case / 'grandchild.stop')
        deadline = time.monotonic() + 10
        while read_complete(case / 'grandchild-ready.json') is None:
            if child.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError('grandchild failed to become ready')
            time.sleep(.02)
        recording._write_new(case / 'worker-ready.json', {
            'identity': recording.process_identity(os.getpid()),
            'grandchild': identity, 'at': recording._times()})
        deadline = time.monotonic() + 40
        while not (case / 'worker.stop').exists():
            # Guardian registry order is not a process-tree order. The child
            # may cooperatively exit just before our stop file is published.
            if child.poll() is not None and not (case / 'grandchild.stop').exists():
                raise RuntimeError('grandchild ended before guardian cleanup')
            if time.monotonic() >= deadline:
                raise RuntimeError('worker or grandchild ended before guardian cleanup')
            time.sleep(.02)
        code = child.wait(timeout=5)
        recording._write_new(case / 'worker-result.json', {
            'grandchild': identity, 'grandchild_exit_code': code, 'at': recording._times()})
        if code != 0:
            raise RuntimeError('ordinary grandchild exit was not zero')
        raw(b'worker-stopped\n')
    finally:
        if child is not None and child.poll() is None:
            if identity is not None:
                recording.stop_owned([identity], case / 'worker-emergency-cleanup.jsonl',
                                     grace_s=.2, terminate_s=.5)
            else:
                child.terminate()  # Exact Popen-owned handle if registration failed.
            child.wait(timeout=3)
'''

SUPERVISOR = COMMON + r'''
declaration = read_complete(case / 'expected-crash.json')
if declaration is None or declaration['expected_exit_code'] != 17:
    raise RuntimeError('deliberate negative exit was not predeclared')
raw(b'supervisor-start\n', b'supervisor-stderr-before-crash\xff\n')
supervisor = recording.process_identity(os.getpid())
recording._write_new(case / 'supervisor.json', supervisor)
guardian = worker = None
guardian_identity = worker_identity = None
with (case / 'guardian.stdout.bin').open('xb') as guardian_stdout, \
     (case / 'guardian.stderr.bin').open('xb') as guardian_stderr, \
     (case / 'worker.stdout.bin').open('xb') as worker_stdout, \
     (case / 'worker.stderr.bin').open('xb') as worker_stderr:
    try:
        guardian = subprocess.Popen([sys.executable, str(recording_path), '--guardian', str(case)],
            cwd=case, stdin=subprocess.DEVNULL, stdout=guardian_stdout, stderr=guardian_stderr,
            creationflags=flags)
        guardian_identity = register(guardian.pid, 'fixture-guardian', case / 'guardian.stop', watched=False)
        worker = subprocess.Popen([sys.executable, str(case / 'worker.py'), str(case), str(recording_path)],
            cwd=case, stdin=subprocess.DEVNULL, stdout=worker_stdout, stderr=worker_stderr,
            creationflags=flags)
        worker_identity = register(worker.pid, 'fixture-worker', case / 'worker.stop')
        deadline = time.monotonic() + 12
        while True:
            worker_ready = read_complete(case / 'worker-ready.json')
            try:
                log = (case / 'guardian.jsonl').read_bytes()
            except FileNotFoundError:
                log = b''
            first = log.split(b'\n')[0] if b'\n' in log else b''
            guardian_ready = json.loads(first) if first else None
            if worker_ready is not None and guardian_ready is not None:
                if guardian_ready['action'] != 'guardian_ready':
                    raise RuntimeError('guardian did not publish readiness')
                break
            if guardian.poll() is not None or worker.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError('fixture did not become ready while supervisor was alive')
            time.sleep(.02)
        for identity in (supervisor, worker_identity, worker_ready['grandchild'], guardian_identity):
            if recording.matching_process(identity) is None:
                raise RuntimeError('process identity was no longer alive before the crash')
        recording._write_new(case / 'supervisor-ready.json', {
            'supervisor': supervisor, 'worker': worker_identity,
            'grandchild': worker_ready['grandchild'], 'guardian': guardian_identity,
            'guardian_ready_at': guardian_ready['at'], 'at': recording._times()})
        deadline = time.monotonic() + 12
        while not (case / 'allow-declared-crash').exists():
            if (case / 'supervisor.stop').exists():
                sys.exit(0)  # Owned emergency cleanup path, never the crash oracle.
            if time.monotonic() >= deadline:
                raise RuntimeError('parent did not authorize the predeclared crash in time')
            time.sleep(.02)
        recording._write_new(case / 'supervisor-crash.json', {
            'action': 'intentional_supervisor_crash', 'identity': supervisor,
            'expected_exit_code': 17, 'at': recording._times()})
        raw(b'supervisor-crashing\n')
        os._exit(17)  # This deliberate fixture death bypasses finally completely.
    finally:
        # Only reached for an unexpected fixture error or requested emergency stop.
        if guardian is not None and guardian.poll() is None:
            (case / 'guardian.stop').touch(exist_ok=True)
            guardian.wait(timeout=12)
        if worker is not None and worker.poll() is None:
            if worker_identity is not None:
                recording.stop_owned([worker_identity], case / 'supervisor-emergency-cleanup.jsonl',
                                     grace_s=.2, terminate_s=.5)
            else:
                worker.terminate()
            worker.wait(timeout=3)
'''


class NonChildExitObservation:
    """Acquire a Windows wait/query handle while the identity is still alive."""
    def __init__(self, identity):
        self.identity = identity
        self.process = recording.matching_process(identity)
        assert self.process is not None
        self.handle = None
        if os.name == 'nt':
            from ctypes import wintypes
            self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            self.kernel.OpenProcess.restype = wintypes.HANDLE
            self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            self.kernel.WaitForSingleObject.restype = wintypes.DWORD
            self.kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            self.kernel.GetExitCodeProcess.restype = wintypes.BOOL
            self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            self.kernel.CloseHandle.restype = wintypes.BOOL
            self.handle = self.kernel.OpenProcess(0x00100000 | 0x1000, False, identity['pid'])
            if not self.handle:
                raise ctypes.WinError(ctypes.get_last_error())
            if recording.matching_process(identity) is None:
                self.close()
                raise AssertionError('identity changed while acquiring its wait handle')

    def wait(self, seconds):
        if self.handle is None:
            # POSIX returns None for a non-child; preserve that limitation.
            return self.process.wait(timeout=seconds)
        from ctypes import wintypes
        status = self.kernel.WaitForSingleObject(self.handle, int(seconds * 1000))
        if status == 258:
            raise TimeoutError('owned fixture process failed to exit in time')
        if status != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        code = wintypes.DWORD()
        if not self.kernel.GetExitCodeProcess(self.handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return code.value

    def close(self):
        if self.handle is not None:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def read_complete(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def wait_ready(path, supervisor, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = read_complete(path)
        if record is not None:
            return record
        assert supervisor.poll() is None, 'supervisor died before the declared crash gate'
        time.sleep(.02)
    raise AssertionError('supervisor readiness deadline exceeded')


def identity_key(identity):
    return identity['pid'], identity['creation_time'], os.path.normcase(identity['executable'])


@pytest.mark.timeout(60)
def test_guardian_survives_live_supervisor_crash_and_cleans_registered_descendants(tmp_path):
    # Under RecordingSession, retain raw evidence in that fresh command record
    # instead of pytest's rotating temporary-directory retention. Standalone
    # diagnostics use tmp_path and do not claim persistent acceptance evidence.
    outer_registry = os.environ.get('ACCEPTANCE_PROCESS_REGISTRY')
    evidence_parent = Path(outer_registry).resolve().parent if outer_registry else tmp_path
    case = evidence_parent / ('guardian-crash-' + uuid.uuid4().hex)
    case.mkdir()
    for name in ('processes', 'fixture-owned'):
        (case / name).mkdir()
    for name, source in (('supervisor.py', SUPERVISOR), ('worker.py', WORKER),
                         ('grandchild.py', GRANDCHILD)):
        (case / name).write_text(textwrap.dedent(source), encoding='utf-8')
    # Windows venv python.exe is a redirector that can create another interpreter
    # PID. This fixture deliberately launches the independently observed running
    # interpreter executable directly, while importing the same psutil package.
    actual_executable = Path(recording.process_identity(os.getpid())['executable']).resolve(strict=True)
    psutil_module = Path(recording.psutil.__file__).resolve(strict=True)
    environment = dict(os.environ, PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    python_path = [str(psutil_module.parent.parent)]
    if environment.get('PYTHONPATH'):
        python_path.append(environment['PYTHONPATH'])
    environment['PYTHONPATH'] = os.pathsep.join(python_path)
    argv = [str(actual_executable), str(case / 'supervisor.py'), str(case), str(Path(recording.__file__).resolve())]
    declaration = {'scenario': 'deliberate fixture supervisor crash after guardian readiness',
                   'expected_exit_code': 17, 'expected_role': 'fixture-supervisor',
                   'caller_sys_executable': sys.executable,
                   'actual_executable': str(actual_executable),
                   'actual_executable_sha256': hashlib.sha256(actual_executable.read_bytes()).hexdigest(),
                   'psutil_module': str(psutil_module),
                   'psutil_module_sha256': hashlib.sha256(psutil_module.read_bytes()).hexdigest(),
                   'child_pythonpath': environment['PYTHONPATH'],
                   'argv': argv, 'at': recording._times()}
    recording._write_new(case / 'expected-crash.json', declaration)
    supervisor = None
    supervisor_identity = None
    observations = {}
    with (case / 'supervisor.stdout.bin').open('xb') as stdout, \
         (case / 'supervisor.stderr.bin').open('xb') as stderr:
        try:
            supervisor = subprocess.Popen(argv, cwd=case, env=environment,
                stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            observed = recording.process_identity(supervisor.pid)
            supervisor_identity = recording.register_process(case / 'fixture-owned', supervisor.pid,
                owner_run='guardian-crash-negative-control', role='fixture-supervisor',
                stop_file=case / 'supervisor.stop', expected_identity=observed)
            outer = environment.get('ACCEPTANCE_PROCESS_REGISTRY')
            if outer and Path(outer).resolve() != (case / 'fixture-owned').resolve():
                recording.register_process(outer, supervisor.pid,
                    owner_run='guardian-crash-negative-control', role='fixture-supervisor',
                    stop_file=case / 'supervisor.stop', expected_identity=supervisor_identity)
            ready = wait_ready(case / 'supervisor-ready.json', supervisor)
            assert identity_key(ready['supervisor']) == identity_key(supervisor_identity)
            for identity in ready.values():
                if isinstance(identity, dict) and 'pid' in identity:
                    assert recording.matching_process(identity) is not None
                    assert Path(identity['executable']).resolve() == actual_executable
            assert ready['worker']['parent_pid'] == supervisor.pid
            assert ready['guardian']['parent_pid'] == supervisor.pid
            assert ready['grandchild']['parent_pid'] == ready['worker']['pid']
            assert ready['guardian_ready_at']['monotonic'] <= ready['at']['monotonic']
            assert not (case / 'guardian-result.json').exists()
            assert not (case / 'guardian.stop').exists()
            for role in ('guardian', 'worker', 'grandchild'):
                observations[role] = NonChildExitObservation(ready[role])

            (case / 'allow-declared-crash').touch(exist_ok=False)
            assert supervisor.wait(timeout=5) == 17
            codes = {'supervisor': supervisor.returncode}
            codes['guardian'] = observations['guardian'].wait(15)
            for role in ('worker', 'grandchild'):
                codes[role] = observations[role].wait(3)
            for role in ('guardian', 'worker', 'grandchild'):
                if os.name == 'nt':
                    assert codes[role] == 0, (role, codes[role])
                else:
                    assert codes[role] in (0, None), (role, codes[role])
                assert recording.matching_process(ready[role]) is None
            assert recording.matching_process(supervisor_identity) is None

            report = json.loads((case / 'guardian-result.json').read_text(encoding='utf-8'))
            assert report['supervisor_died'] is True
            assert report['errors'] == []
            expected = {identity_key(ready[role]) for role in ('worker', 'grandchild')}
            observed_by_pid = {item['pid']: item for item in report['identities']}
            observed_keys = {identity_key(item) for item in report['identities']}
            assert expected <= observed_keys
            assert expected <= {identity_key(item) for item in report['alive_before_cleanup']} <= observed_keys
            for item in report['identities']:
                if identity_key(item) in expected:
                    assert item['registration'] == 'explicit'
                else:
                    # Windows may create console-host auxiliaries internally.
                    # Retain their observed ancestry and require cleanup too.
                    assert item['registration'] == 'observed'
                    assert item['role'] == 'observed-descendant'
                    parent, visited = item['parent_pid'], {item['pid']}
                    while parent not in (ready['worker']['pid'], ready['grandchild']['pid']):
                        assert parent in observed_by_pid and parent not in visited
                        visited.add(parent)
                        parent = observed_by_pid[parent]['parent_pid']
                assert recording.matching_process(item) is None
            log = (case / 'guardian.jsonl').read_bytes()
            assert log.endswith(b'\n')
            events = [json.loads(line) for line in log.splitlines()]
            assert events[0]['action'] == 'guardian_ready'
            assert identity_key(events[0]['identity']) == identity_key(ready['guardian'])
            assert [item['action'] for item in events].count('supervisor_exit') == 1
            assert not [item for item in events if item['action'] in
                        ('requested_cleanup', 'guardian_error', 'terminate', 'kill')]
            assert {identity_key(item['identity']) for item in events
                    if item['action'] == 'stop_file'} == expected
            complete = [item for item in events if item['action'] == 'cleanup_complete']
            assert len(complete) == 1 and complete[0]['errors'] == [] and complete[0]['survivors'] == []
            crash = json.loads((case / 'supervisor-crash.json').read_text(encoding='utf-8'))
            assert identity_key(crash['identity']) == identity_key(supervisor_identity)
            assert crash['expected_exit_code'] == declaration['expected_exit_code'] == 17
            assert declaration['at']['monotonic'] < ready['at']['monotonic'] < crash['at']['monotonic']
            detected = next(item for item in events if item['action'] == 'supervisor_exit')
            assert crash['at']['monotonic'] <= detected['at']['monotonic']
            worker_result = json.loads((case / 'worker-result.json').read_text(encoding='utf-8'))
            assert worker_result['grandchild_exit_code'] == 0
            expected_logs = {
                'supervisor.stdout.bin': b'supervisor-start\nsupervisor-crashing\n',
                'supervisor.stderr.bin': b'supervisor-stderr-before-crash\xff\n',
                'worker.stdout.bin': b'worker-start\x00\xff\nworker-stopped\n',
                'worker.stderr.bin': b'worker-stderr\x80\n',
                'grandchild.stdout.bin': b'grandchild-start\x00\xff\ngrandchild-stopped\n',
                'grandchild.stderr.bin': b'grandchild-stderr\x80\n',
                'guardian.stdout.bin': b'', 'guardian.stderr.bin': b'',
            }
            for name, expected_bytes in expected_logs.items():
                assert (case / name).read_bytes() == expected_bytes, name
            recording._write_new(case / 'test-observed.json', {
                'actual_exit_codes': codes, 'at': recording._times(),
                'nonchild_exit_status_limitation': None if os.name == 'nt' else
                    'POSIX non-child wait status unavailable where null; this is not zero-exit evidence.',
                'raw_sha256': {name: hashlib.sha256((case / name).read_bytes()).hexdigest()
                               for name in expected_logs},
                'scope': 'Real guardian crash fixture only; original experiment launcher is not exercised.'})
        finally:
            # This fallback cannot turn failed guardian behavior into a pass:
            # every guardian oracle above runs before test-finally intervention.
            if supervisor is not None and supervisor.poll() is None:
                (case / 'supervisor.stop').touch(exist_ok=True)
                try:
                    supervisor.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    pass
            owned = recording._registered(case / 'fixture-owned')
            report = read_complete(case / 'guardian-result.json')
            if report is not None:
                owned.extend(report['identities'])
            live = [item for item in owned if recording.matching_process(item) is not None]
            if live:
                recording.stop_owned(live, case / 'test-emergency-cleanup.jsonl', grace_s=.2, terminate_s=.5)
            if supervisor is not None and supervisor.poll() is None:
                supervisor.terminate()  # Exact owned Popen handle, never a name/global kill.
            if supervisor is not None:
                supervisor.wait(timeout=3)
            for observer in observations.values():
                observer.close()
            assert all(recording.matching_process(item) is None for item in owned), 'owned fixture process survived'
