"""Pure PREPARE process-double regressions; never live-process evidence."""
import json
import signal
from types import SimpleNamespace

import pytest

from bittorrent_lite.acceptance_tools import recording, stress
from bittorrent_lite.tests.end_to_end import support


class ProcessDouble:
    def __init__(self, pid, *, wrapper=None):
        self.pid, self.wrapper, self.returncode = pid, wrapper, None
        self.terminated, self.killed = False, False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        # An actual process double has a wrapper and models psutil's API;
        # standalone wrapper doubles model subprocess.Popen.
        self.returncode = (15 if self.wrapper else 1) if support.os.name == 'nt' else 0
        if self.wrapper:
            self.wrapper.returncode = self.returncode

    def kill(self):
        self.killed = True
        self.returncode = (15 if self.wrapper else 1) if support.os.name == 'nt' else -signal.SIGKILL
        if self.wrapper:
            self.wrapper.returncode = self.returncode

    def wait(self, timeout):
        return self.returncode


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(support, 'free_port', lambda: 19001)
    swarm = support.Swarm(tmp_path, 1)
    wrapper = ProcessDouble(1001)
    actual = ProcessDouble(1002, wrapper=wrapper)
    child = {'proc': wrapper, 'name': 'tracker', 'proc_id': '00-tracker',
             'identity': {'pid': 1001, 'creation_time': 1, 'executable': 'unit-wrapper'},
             'interpreter': {'pid': 1002, 'creation_time': 2, 'executable': 'unit-python'},
             'teardown': 'declared_tracker_platform_termination', 'stop': None,
             'deliberate_kill': False, 'tails': {}, 'strict_log': False}
    for field in ('out', 'err', 'events'):
        child[field] = tmp_path / (field + '.raw')
        child[field].write_bytes(b'')
    child['events'].write_bytes(b'{"event":"tracker_ready","mono":1,"proc":"00-tracker"}\n'
                               b'{"event":"exit","reason":"stopped","mono":2,"proc":"00-tracker"}\n')
    swarm.children.append(child)
    def matching(identity):
        process = {1001: wrapper, 1002: actual}.get(identity['pid'])
        return process if process is not None and process.poll() is None else None
    monkeypatch.setattr(recording, 'matching_process', matching)
    return swarm, child, wrapper, actual


def test_tracker_terminates_actual_interpreter_and_observes_wrapper_exit(fixture):
    swarm, child, wrapper, actual = fixture
    swarm.close()
    assert actual.terminated and not wrapper.terminated
    assert child['interpreter_exit_code'] == actual.returncode == wrapper.returncode
    assert swarm.actions[0]['target_identity'] == child['interpreter']
    result = json.loads((swarm.root / 'results.json').read_text())
    assert result['cleanup_errors'] == []
    assert result['processes'][0]['interpreter'] == child['interpreter']
    assert result['processes'][0]['interpreter_exit_code'] == result['processes'][0]['expected_exit_code']


def test_changed_actual_interpreter_prevents_any_signal(fixture, monkeypatch):
    swarm, child, wrapper, actual = fixture
    monkeypatch.setattr(recording, 'matching_process', lambda identity: wrapper if identity['pid'] == 1001 else None)
    with pytest.raises(AssertionError, match='interpreter identity changed'):
        swarm.close()
    assert not actual.terminated and not wrapper.terminated and not actual.killed


def test_ordinary_cooperative_stop_checks_actual_identity_before_touching_file(fixture, monkeypatch):
    swarm, child, wrapper, actual = fixture
    child.update(name='peer', teardown=None, stop=swarm.root / 'peer.stop')
    swarm.peers['peer'] = child
    monkeypatch.setattr(recording, 'matching_process', lambda identity: wrapper if identity['pid'] == 1001 else None)
    with pytest.raises(AssertionError, match='interpreter identity changed'):
        swarm.stop_peer('peer')
    assert not child['stop'].exists()


def test_unknown_interpreter_exit_code_is_never_inferred_from_wrapper(fixture):
    swarm, child, wrapper, actual = fixture
    wrapper.returncode = 0
    with pytest.raises(AssertionError, match='exit status is unavailable'):
        swarm._wait_owned_exit(child, actual, 1)
    assert 'interpreter_exit_code' not in child


def test_differing_actual_and_wrapper_codes_are_not_reclassified_as_expected(fixture):
    swarm, child, wrapper, actual = fixture
    actual.returncode, wrapper.returncode = 1, 0
    with pytest.raises(AssertionError, match='differs from actual interpreter exit'):
        swarm._wait_owned_exit(child, actual, 1)
    assert 'interpreter_exit_code' not in child


def test_stress_reuses_existing_live_observation_without_registering_again(fixture, monkeypatch):
    swarm, child, wrapper, actual = fixture
    observation = {'identity': child['interpreter'], 'ancestry': [child['identity'], child['interpreter']]}
    child['interpreter_observation'] = observation
    monkeypatch.setattr(recording, 'register_process', lambda *a, **kw: pytest.fail('must not register twice'))
    assert stress.observe_interpreter(child, {}, 'unit-registry') is observation


def test_same_pid_wait_uses_popen_to_avoid_reaping_exit_status_twice(fixture):
    swarm, child, wrapper, actual = fixture
    child['interpreter'] = child['identity']
    wrapper.returncode = 0
    other_view = SimpleNamespace(pid=wrapper.pid, wait=lambda _: pytest.fail('must use Popen.wait for direct child'))
    assert swarm._wait_owned_exit(child, other_view, 1) == 0


def test_strict_event_pid_must_match_independently_observed_interpreter(fixture):
    swarm, child, wrapper, actual = fixture
    child['strict_log'] = True
    child['events'].write_bytes(json.dumps({'event': 'tracker_ready', 'mono': 1,
        'proc': child['proc_id'], 'log_schema': 'btl-log-v1', 'log_sequence': 0,
        'log_pid': wrapper.pid}).encode() + b'\n')
    with pytest.raises(AssertionError, match='wrong observed interpreter PID'):
        swarm.structured_events(child)


def test_plain_swarm_creates_fresh_local_registry_and_registers_child(tmp_path, monkeypatch):
    monkeypatch.delenv('ACCEPTANCE_PROCESS_REGISTRY', raising=False)
    monkeypatch.setattr(support, 'free_port', lambda: 19001)
    swarm = support.Swarm(tmp_path, 1)
    registry = tmp_path / 'owned-processes'
    assert registry.is_dir() and swarm.env['ACCEPTANCE_PROCESS_REGISTRY'] == str(registry)
    observed = json.loads((tmp_path / 'process-supervision.json').read_text())
    assert observed['registry_mode'] == 'local-no-guardian'
    assert observed['guardian_verification'] == 'NOT VERIFIED BY SWARM'
    assert observed['acceptance_requires_external_recorder'] is True
    proc = ProcessDouble(3001)
    identity = {'pid': 3001, 'creation_time': 1, 'executable': 'unit-wrapper'}
    calls = []
    def register(path, process, **kwargs):
        calls.append((path, process, kwargs))
        return identity
    monkeypatch.setattr(support.subprocess, 'Popen', lambda *a, **kw: proc)
    monkeypatch.setattr(support, '_register_child', register)
    child = swarm.launch('peer', ['bittorrent_lite'], stop_file=tmp_path / 'peer.stop')
    assert child['identity'] == identity
    assert calls[0][0] == str(registry) and calls[0][1] is proc


def test_outer_registry_is_preserved_without_claiming_guardian_verification(tmp_path, monkeypatch):
    external = tmp_path / 'outer-registry'
    external.mkdir()
    monkeypatch.setenv('ACCEPTANCE_PROCESS_REGISTRY', str(external))
    monkeypatch.setattr(support, 'free_port', lambda: 19001)
    swarm = support.Swarm(tmp_path / 'swarm', 1)
    assert swarm.env['ACCEPTANCE_PROCESS_REGISTRY'] == str(external)
    assert not (swarm.root / 'owned-processes').exists()
    assert swarm.process_supervision['registry_mode'] == 'inherited'
    assert swarm.process_supervision['guardian_verification'] == 'NOT VERIFIED BY SWARM'


def test_existing_local_registry_is_not_reused_or_overwritten(tmp_path, monkeypatch):
    monkeypatch.delenv('ACCEPTANCE_PROCESS_REGISTRY', raising=False)
    monkeypatch.setattr(support, 'free_port', lambda: 19001)
    registry = tmp_path / 'owned-processes'
    registry.mkdir()
    sentinel = registry / 'unrelated.txt'
    sentinel.write_bytes(b'preserve')
    with pytest.raises(FileExistsError):
        support.Swarm(tmp_path, 1)
    assert sentinel.read_bytes() == b'preserve'


@pytest.mark.parametrize('operation', ['terminate', 'kill'])
def test_windows_psutil_and_popen_have_distinct_exact_exit_contracts(operation):
    observed = support.termination_contract({'identity': {'pid': 1}}, operation, platform='nt')
    fallback = support.termination_contract({'identity': None}, operation, platform='nt')
    assert observed == {'api': 'psutil.Process.' + operation, 'platform': 'nt', 'expected_exit_codes': [15]}
    assert fallback == {'api': 'subprocess.Popen.' + operation, 'platform': 'nt', 'expected_exit_codes': [1]}


def test_psutil_tracker_exit_one_is_rejected_not_broadened_to_match(fixture, monkeypatch):
    swarm, child, wrapper, actual = fixture
    contract = support.termination_contract
    monkeypatch.setattr(support, 'termination_contract', lambda child, operation:
                        contract(child, operation, platform='nt'))
    def wrong_api_termination():
        actual.terminated = True
        actual.returncode = wrapper.returncode = 1
    actual.terminate = wrong_api_termination
    with pytest.raises(AssertionError, match=r'tracker teardown exit 1 not in \[15\]'):
        swarm.close()
    assert swarm.actions[0]['mechanism'] == 'psutil.Process.terminate'
    assert swarm.actions[0]['expected_exit_codes'] == [15]


def test_nonzero_psutil_exit_does_not_count_as_graceful_peer_stop(fixture):
    swarm, child, wrapper, actual = fixture
    child.update(name='peer', teardown=None, stop=swarm.root / 'peer.stop')
    swarm.peers['peer'] = child
    def nonzero_wait(timeout):
        actual.returncode = wrapper.returncode = 15
        return 15
    actual.wait = nonzero_wait
    with pytest.raises(AssertionError):
        swarm.stop_peer('peer')
    assert child['interpreter_exit_code'] == 15
