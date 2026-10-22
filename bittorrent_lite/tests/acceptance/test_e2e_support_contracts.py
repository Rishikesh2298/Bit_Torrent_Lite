"""Unit tests for E2E evidence helpers; no child process or TCP socket starts."""
import hashlib
import json
from pathlib import Path
import signal

import pytest

from bittorrent_lite.tests.end_to_end import support


class Process:
    def __init__(self, pid=91001, code=None):
        self.pid = pid
        self.returncode = code
        self.killed = False
        self.terminated = False

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = 1 if support.os.name == 'nt' else -signal.SIGKILL

    def terminate(self):
        self.terminated = True
        self.returncode = 1 if support.os.name == 'nt' else 0

    def wait(self, timeout):
        return self.returncode


@pytest.fixture
def swarm(tmp_path, monkeypatch):
    monkeypatch.setattr(support, 'free_port', lambda: 19000)
    # Deliberately no context-manager cleanup: these tests never start children.
    return support.Swarm(tmp_path, 65536 * 2 + 29, fixture_seed=71)


def child_files(swarm, *, code=None):
    child = {'proc': Process(code=code), 'out': swarm.root / 'raw.stdout',
             'err': swarm.root / 'raw.stderr', 'events': swarm.root / 'strict.events.jsonl',
             'name': 'a-peer', 'proc_id': '00-a-peer', 'identity': None,
             'stop': None, 'teardown': None, 'deliberate_kill': False, 'tails': {}}
    child['out'].write_bytes(b'')
    child['err'].write_bytes(b'')
    child['events'].write_bytes(b'')
    return child


def structured_line(event='listening', *, mono=1, proc='00-a-peer'):
    return (json.dumps({'event': event, 'mono': mono, 'proc': proc}) + '\n').encode()


def test_fixture_full_pieces_are_distinct_and_default_is_not_a_challenge(swarm):
    data = swarm.source.read_bytes()
    pieces = [data[i:i + 65536] for i in range(0, len(data), 65536)]
    assert pieces[0] != pieces[1]
    assert pieces[0][:8] != pieces[1][:8]
    assert pieces[0][-8:] != pieces[1][-8:]
    manifest = json.loads((swarm.root / 'fixture.json').read_text())
    assert manifest['piece_sha256'] == [hashlib.sha256(piece).hexdigest() for piece in pieces]
    assert manifest['mode'] == 'diagnostic' and manifest['fixture_seed'] == 71
    assert manifest['acceptance_challenge'] is None
    assert manifest['acceptance_eligible'] is False
    assert manifest['source_isolation_verified'] is False


def test_existing_source_is_never_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(support, 'free_port', lambda: 19000)
    source = tmp_path / 'original bytes.bin'
    source.write_bytes(b'unrelated sentinel')
    with pytest.raises(FileExistsError):
        support.Swarm(tmp_path, 1)
    assert source.read_bytes() == b'unrelated sentinel'


def test_launch_registers_immediately_with_distinct_raw_and_structured_paths(swarm, monkeypatch):
    calls, launches = [], []
    process = Process()
    def popen(command, **kwargs):
        calls.append('popen')
        launches.append((command, kwargs))
        assert kwargs['stdout'].mode == 'xb' and kwargs['stderr'].mode == 'xb'
        return process
    identity = {'pid': process.pid, 'creation_time': 123, 'executable': 'python',
                'arguments': ['python'], 'parent_pid': 4}
    def register(registry, proc, **kwargs):
        calls.append('register')
        assert proc is process
        assert registry == 'controlled-registry'
        assert kwargs['stop_file'] == swarm.root / 'peer.stop'
        assert kwargs['role'] == 'a-peer'
        assert len(swarm.children) == 1
        assert not (swarm.root / 'launches.json').exists()
        return identity
    monkeypatch.setattr(support.subprocess, 'Popen', popen)
    monkeypatch.setattr(support, '_register_child', register)
    swarm.env['ACCEPTANCE_PROCESS_REGISTRY'] = 'controlled-registry'
    child = swarm.launch('a-peer', ['bittorrent_lite', '--peer-id', 'a-peer'],
                         stop_file=swarm.root / 'peer.stop')
    assert calls == ['popen', 'register']
    assert child['identity'] == identity
    environment = launches[0][1]['env']
    assert Path(environment['BTL_EVENT_LOG']) == child['events']
    assert environment['BTL_PROC_ID'] == child['proc_id']
    assert environment['PYTHONIOENCODING'] == 'utf-8'
    assert environment['PYTHONUTF8'] == '1'
    assert swarm.launches[-1]['stream_encoding'] == 'utf-8'
    assert child['events'] not in (child['out'], child['err'])
    assert child['out'].suffix == '.stdout' and child['err'].suffix == '.stderr'


def test_registration_failure_retains_owned_child_for_cleanup(swarm, monkeypatch):
    process = Process()
    monkeypatch.setattr(support.subprocess, 'Popen', lambda *args, **kwargs: process)
    def fail(*args, **kwargs):
        raise OSError('registration unavailable')
    monkeypatch.setattr(support, '_register_child', fail)
    swarm.env['ACCEPTANCE_PROCESS_REGISTRY'] = 'controlled-registry'
    with pytest.raises(OSError, match='registration unavailable'):
        swarm.launch('a-peer', ['bittorrent_lite'])
    assert swarm.children[0]['proc'] is process
    assert swarm.actions[-1]['action'] == 'registration_failed'


def test_public_events_ignore_only_known_console_format(swarm):
    child = child_files(swarm)
    child['out'].write_bytes(b'[14:32:01] [TRACKER     ] INFO    normal console\n'
                             b'{"event":"START","at":1}\n')
    assert swarm.events(child) == [{'event': 'START', 'at': 1}]
    child['out'].write_bytes(b'arbitrary malformed output\n')
    with pytest.raises(AssertionError, match='malformed complete record'):
        swarm.events(child)


def test_public_unicode_console_is_strict_utf8(swarm):
    child = child_files(swarm)
    child['out'].write_bytes(('[14:32:01] [TRACKER     ] INFO    file=abcd… -> 0 peer(s)\n'
                              '{"event":"START","at":1}\n').encode('utf-8'))
    assert swarm.events(child) == [{'event': 'START', 'at': 1}]
    child['out'].write_bytes(b'[14:32:01] [TRACKER     ] INFO    file=abcd\x85 -> 0 peer(s)\n')
    with pytest.raises(UnicodeDecodeError):
        swarm.events(child)


def test_tracker_readiness_checks_http_contract_and_records_bytes(swarm, monkeypatch):
    calls = []
    class Response:
        status = 200
        def read(self, limit):
            assert limit == 65537
            return b'{"interval":5,"peers":[]}'
    class Connection:
        def __init__(self, host, port, timeout):
            assert (host, port, timeout) == ('127.0.0.1', swarm.tracker_port, .5)
        def request(self, method, path, body, headers):
            calls.append((method, path, json.loads(body), headers))
        def getresponse(self):
            return Response()
        def close(self):
            calls.append('closed')
    monkeypatch.setattr(support.http.client, 'HTTPConnection', Connection)
    swarm._probe_tracker()
    assert calls[0][:2] == ('POST', '/announce')
    assert calls[0][2] == {'file_id': '0' * 64, 'peer_id': 'readiness-probe',
                           'listen_port': 1, 'event': 'stopped'}
    assert calls[-1] == 'closed'
    record = json.loads((swarm.root / 'tracker-readiness.jsonl').read_text())
    assert record['status'] == 200 and record['port'] == swarm.tracker_port
    assert json.loads(bytes.fromhex(record['request_hex'])) == calls[0][2]
    assert bytes.fromhex(record['response_hex']) == b'{"interval":5,"peers":[]}'


@pytest.mark.parametrize('bad', [b'{bad}\n', b'\xff\n', b'[]\n',
                                b'{"event":"a","event":"b"}\n',
                                b'{"event":"a","mono":NaN}\n',
                                b'{"event":"a","mono":1e999}\n',
                                b'\n'],
                         ids=['json', 'utf8', 'array', 'duplicate-key', 'nan', 'overflow-float', 'blank'])
def test_complete_bad_lines_always_fail_even_while_child_runs(swarm, bad):
    child = child_files(swarm)
    child['out'].write_bytes(bad)
    with pytest.raises((AssertionError, UnicodeDecodeError)):
        swarm.events(child)


def test_only_running_incomplete_tail_can_be_temporarily_ignored(swarm):
    child = child_files(swarm)
    child['out'].write_bytes(b'{"event":"START"}\n{"event":')
    assert swarm.events(child) == [{'event': 'START'}]
    child['proc'].returncode = 0
    with pytest.raises(AssertionError, match='incomplete final record'):
        swarm.events(child)


def test_declared_kill_tail_is_preserved_and_described(swarm):
    child = child_files(swarm, code=1)
    child['deliberate_kill'] = True
    raw = b'{"event":"START"}\n{"event":'
    child['out'].write_bytes(raw)
    assert swarm.events(child) == [{'event': 'START'}]
    assert child['out'].read_bytes() == raw
    assert child['tails'][child['out'].name]['bytes'] == len(b'{"event":')
    assert child['tails'][child['out'].name]['reason'] == 'declared_kill_incomplete_tail'


@pytest.mark.parametrize('fault', ['wrong-proc', 'time-regression', 'console'],
                         ids=['wrong-proc', 'time-regression', 'console'])
def test_structured_stream_rejects_identity_time_and_console_contamination(swarm, fault):
    child = child_files(swarm)
    raw = {'wrong-proc': structured_line(proc='other'),
           'time-regression': structured_line(mono=2) + structured_line(mono=1),
           'console': b'[14:32:01] [TRACKER     ] INFO    normal console\n'}[fault]
    child['events'].write_bytes(raw)
    with pytest.raises(AssertionError):
        swarm.structured_events(child)


def test_complete_checks_size_digest_and_bytewise_original_without_copying(swarm, monkeypatch):
    child = child_files(swarm)
    swarm.peers['a-peer'] = child
    child['out'].write_bytes(b'{"event":"COMPLETE"}\n')
    output = swarm.root / 'downloads' / 'a-peer' / swarm.source.name
    output.parent.mkdir(parents=True)
    # Test setup emulates a product result; the supervisor must only read it.
    output.write_bytes(swarm.source.read_bytes())
    reads = []
    real_compare = support._same_bytes
    def compared(first, second):
        reads.append((first, second))
        return real_compare(first, second)
    monkeypatch.setattr(support, '_same_bytes', compared)
    assert swarm.complete('a-peer') == output
    assert reads == [(swarm.source, output)]
    assert swarm.actions[-1]['source_byte_comparison'] is True
    assert swarm.actions[-1]['source_isolation_verified'] is False
    corrupted = bytearray(output.read_bytes())
    corrupted[5] ^= 1
    output.write_bytes(corrupted)
    with pytest.raises(AssertionError):
        swarm.complete('a-peer')


def test_missing_source_comparison_is_not_reported_as_isolation(swarm):
    child = child_files(swarm)
    swarm.peers['a-peer'] = child
    child['out'].write_bytes(b'{"event":"COMPLETE"}\n')
    output = swarm.root / 'downloads' / 'a-peer' / swarm.source.name
    output.parent.mkdir(parents=True)
    output.write_bytes(swarm.source.read_bytes())
    swarm.source.rename(swarm.root / 'still-accessible-source.bin')
    swarm.complete('a-peer')
    assert swarm.actions[-1]['source_byte_comparison'] is False
    assert swarm.actions[-1]['source_isolation_verified'] is False


def test_deliberate_crash_records_intent_pid_time_and_exact_exit(swarm):
    child = child_files(swarm)
    child['out'].write_bytes(b'{"event":"START"}\n')
    child['events'].write_bytes(structured_line())
    swarm.kill(child)
    assert child['proc'].killed and child['deliberate_kill']
    assert child['expected_exit_code'] == child['proc'].returncode
    assert [r['action'] for r in swarm.actions] == ['deliberate_crash_requested', 'deliberate_crash_completed']
    assert all(r['pid'] == child['proc'].pid and r['utc'] and r['monotonic'] > 0 for r in swarm.actions)


def test_ordinary_preexisting_nonzero_exit_cannot_be_silently_ignored(swarm):
    child = child_files(swarm, code=7)
    child['out'].write_bytes(b'{"event":"START"}\n')
    child['events'].write_bytes(structured_line())
    swarm.children.append(child)
    with pytest.raises(AssertionError, match='unexpected exit 7'):
        swarm.close()
    result = json.loads((swarm.root / 'results.json').read_text())
    assert result['processes'][0]['exit_code'] == 7
    assert result['cleanup_errors']


def test_declared_tracker_teardown_is_separate_from_peer_success(swarm):
    child = child_files(swarm)
    child['name'] = 'tracker'
    child['teardown'] = 'declared_tracker_platform_termination'
    child['events'].write_bytes(structured_line('tracker_ready') +
                               b'{"event":"exit","reason":"stopped","mono":2,"proc":"00-a-peer"}\n')
    swarm.children.append(child)
    swarm.close()
    assert child['proc'].terminated
    assert [r['action'] for r in swarm.actions] == ['tracker_teardown_requested', 'tracker_teardown_completed']
    result = json.loads((swarm.root / 'results.json').read_text())
    assert result['processes'][0]['exit_code'] == result['processes'][0]['expected_exit_code']
