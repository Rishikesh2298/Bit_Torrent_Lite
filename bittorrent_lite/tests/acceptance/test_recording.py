"""Preparation diagnostics for genuine recorder bytes, identity and ownership."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from bittorrent_lite.acceptance_tools import recording


def session(tmp_path):
    return recording.RecordingSession(tmp_path / "records", "diagnostic", "prepare", {"source": "test-snapshot"})


def test_recorder_preserves_binary_stdin_and_large_separate_streams(tmp_path):
    recorder = session(tmp_path)
    payload = b"\x00\xff\r\n" * 30000
    command = [sys.executable, "-c", "import sys; x=sys.stdin.buffer.read(); sys.stdout.buffer.write(x); sys.stderr.buffer.write(x[::-1])"]
    result = recorder.run("bytes", command, cwd=tmp_path, stdin_bytes=payload,
                          timeout_s=10, oracle="stdout equals stdin; stderr equals reverse bytes")
    root = recorder.root / "bytes"
    assert (root / "stdout.bin").read_bytes() == payload
    assert (root / "stderr.bin").read_bytes() == payload[::-1]
    assert (root / "stdin.bin").read_bytes() == payload
    assert result["exit_code"] == 0 and not result["timed_out"]
    assert result["process"]["pid"] > 0 and result["process"]["creation_time"] > 0
    assert result["elapsed_s"] > 0
    assert result["argv"] == command
    assert result["shell"] is False
    assert recording.matching_process(result["process"]) is None
    assert result["cleanup_errors"] == []
    assert json.loads((root / "record.json").read_text())["exit_code"] == 0


def test_reused_case_or_session_is_rejected_without_overwriting(tmp_path):
    recorder = session(tmp_path)
    recorder.run("once", [sys.executable, "-c", "print('first')"], cwd=tmp_path,
                 timeout_s=10, oracle="print first")
    before = (recorder.root / "once" / "stdout.bin").read_bytes()
    with pytest.raises(FileExistsError):
        recorder.run("once", [sys.executable, "-c", "print('second')"], cwd=tmp_path,
                     timeout_s=10, oracle="must reject existing output")
    with pytest.raises(FileExistsError):
        session(tmp_path)
    assert (recorder.root / "once" / "stdout.bin").read_bytes() == before


def test_predeclared_negative_exit_is_preserved_not_reclassified(tmp_path):
    recorder = session(tmp_path)
    result = recorder.run("negative", [sys.executable, "-c", "import sys; print('expected rejection'); sys.exit(2)"],
                          cwd=tmp_path, timeout_s=10, expected_exit_codes=(2,),
                          oracle="exit 2 and expected rejection text")
    assert result["exit_code"] == 2
    assert (recorder.root / "negative" / "stdout.bin").read_bytes().strip() == b"expected rejection"


def test_unexpected_exit_retains_raw_evidence_and_raises(tmp_path):
    recorder = session(tmp_path)
    with pytest.raises(recording.RecordingFailure) as caught:
        recorder.run("bad", [sys.executable, "-c", "import sys; sys.stderr.write('specific fault'); sys.exit(7)"],
                     cwd=tmp_path, timeout_s=10, oracle="exit zero")
    assert caught.value.record["exit_code"] == 7
    assert caught.value.record["status"] == "FAIL"
    assert (recorder.root / "bad" / "stderr.bin").read_bytes() == b"specific fault"
    assert (recorder.root / "bad" / "record.json").exists()


def test_timeout_is_failure_and_owned_process_exits(tmp_path):
    recorder = session(tmp_path)
    with pytest.raises(recording.RecordingFailure) as caught:
        recorder.run("timeout", [sys.executable, "-c", "import time; time.sleep(60)"],
                     cwd=tmp_path, timeout_s=.1, oracle="finish inside 0.1 seconds")
    assert caught.value.record["timed_out"] is True
    assert caught.value.record["exit_code"] is not None
    assert recording.matching_process(caught.value.record["process"]) is None
    guardian = json.loads((recorder.root / "timeout" / "guardian-result.json").read_text())
    assert guardian["errors"] == []


def test_changed_birth_identity_cannot_authorize_cleanup(tmp_path):
    current = recording.process_identity(os.getpid())
    stale = {**current, "creation_time": current["creation_time"] - 1}
    assert recording.matching_process(stale) is None
    assert recording.stop_owned([stale], tmp_path / "cleanup.jsonl", grace_s=.01, terminate_s=.01) == []
    events = [json.loads(line) for line in (tmp_path / "cleanup.jsonl").read_text().splitlines()]
    assert events[0]["action"] == "already_exited_or_identity_changed"
    assert recording.matching_process(current) is not None


def test_guardian_cleans_registered_child_after_real_supervisor_exit(tmp_path):
    case = tmp_path / "orphan"
    case.mkdir()
    registry = case / "processes"
    registry.mkdir()
    retired = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(.3)"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    retired_identity = recording.process_identity(retired.pid)
    retired.wait(timeout=5)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    identity = recording.register_process(registry, child.pid, owner_run="negative-control", role="orphan-fixture")
    recording._write_new(case / "supervisor.json", retired_identity)
    try:
        result = subprocess.run([sys.executable, str(Path(recording.__file__)), "--guardian", str(case)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15, check=False)
        child.wait(timeout=3)
        assert result.returncode == 0, result.stderr
        report = json.loads((case / "guardian-result.json").read_text())
        assert report["supervisor_died"] is True
        assert report["errors"] == []
        assert recording.matching_process(identity) is None
    finally:
        if child.poll() is None:
            recording.stop_owned([identity], case / "test-finally-cleanup.jsonl", grace_s=.01, terminate_s=.2)
            child.wait(timeout=3)


def test_nonabsolute_executable_and_outside_stop_path_rejected(tmp_path):
    recorder = session(tmp_path)
    with pytest.raises(ValueError, match="absolute"):
        recorder.run("alias", ["python", "--version"], cwd=tmp_path, timeout_s=5, oracle="version")
    with pytest.raises(ValueError, match="under"):
        recorder.run("outside", [sys.executable, "--version"], cwd=tmp_path, timeout_s=5,
                     oracle="version", stop_file=tmp_path / "outside.stop")
    assert not (tmp_path / "outside.stop").exists()


def test_natural_exit_between_identity_check_and_descendant_scan_is_recorded(tmp_path, monkeypatch):
    identity = {"pid": 123, "creation_time": 1, "executable": "fixture",
                "owner_run": "unit-fixture", "role": "command"}
    class Exiting:
        def children(self, recursive):
            assert recursive
            raise recording.psutil.NoSuchProcess(123)
    pending = [Exiting()]
    monkeypatch.setattr(recording, '_registered', lambda registry: [identity])
    monkeypatch.setattr(recording, 'matching_process',
                        lambda item: pending.pop() if item is identity and pending else None)
    assert recording._watch(tmp_path, {'pid': 456}) == 0
    result = json.loads((tmp_path / 'guardian-result.json').read_text())
    events = [json.loads(line) for line in (tmp_path / 'guardian.jsonl').read_text().splitlines()]
    assert result['errors'] == []
    assert result['identities'] == [identity]
    assert any(event['action'] == 'exited_during_descendant_scan' for event in events)


def test_descendant_access_error_is_not_hidden_as_natural_exit(tmp_path, monkeypatch):
    identity = {"pid": 123, "creation_time": 1, "executable": "fixture",
                "owner_run": "unit-fixture", "role": "command"}
    class Denied:
        def children(self, recursive):
            raise recording.psutil.AccessDenied(123)
    pending = [Denied()]
    monkeypatch.setattr(recording, '_registered', lambda registry: [identity])
    monkeypatch.setattr(recording, 'matching_process',
                        lambda item: pending.pop() if item is identity and pending else None)
    assert recording._watch(tmp_path, {'pid': 456}) == 2
    result = json.loads((tmp_path / 'guardian-result.json').read_text())
    assert any('AccessDenied' in error for error in result['errors'])


def test_descendant_pid_reuse_never_becomes_cleanup_authority(monkeypatch):
    class ObservedChild:
        pid = 123
        def create_time(self):
            return 10.0
        def is_running(self):
            return True
    unrelated = {'pid': 123, 'creation_time': 11.0, 'executable': 'unrelated'}
    monkeypatch.setattr(recording, 'process_identity', lambda pid: unrelated)
    assert recording.observed_child_identity(ObservedChild()) is None
    matching = {'pid': 123, 'creation_time': 10.0, 'executable': 'owned'}
    monkeypatch.setattr(recording, 'process_identity', lambda pid: matching)
    assert recording.observed_child_identity(ObservedChild()) == matching


def test_exited_observed_child_does_not_lookup_recycled_pid(monkeypatch):
    class ExitedChild:
        pid = 123
        def create_time(self):
            return 10.0
        def is_running(self):
            return False
    def forbidden(pid):
        pytest.fail('an already exited observed child must not be reidentified')
    monkeypatch.setattr(recording, 'process_identity', forbidden)
    assert recording.observed_child_identity(ExitedChild()) is None


@pytest.mark.parametrize('field, changed', [('pid', 124), ('creation_time', 11.0),
    ('executable', 'unrelated'), ('arguments', ['different']), ('parent_pid', 999)])
def test_registration_rejects_identity_change_before_publishing(tmp_path, monkeypatch, field, changed):
    expected = dict(pid=123, creation_time=10.0, executable='owned',
                    arguments=['owned', 'test-fixture'], parent_pid=1)
    monkeypatch.setattr(recording, 'process_identity', lambda pid: {**expected, field: changed})
    registry = tmp_path / 'registry'
    with pytest.raises(ValueError, match='identity changed before registration'):
        recording.register_process(registry, 123, owner_run='unit', role='fixture',
                                   expected_identity=expected)
    assert list(registry.iterdir()) == []


def test_registration_publishes_only_matching_independent_observation(tmp_path, monkeypatch):
    expected = dict(pid=123, creation_time=10.0, executable='owned',
                    arguments=['owned', 'test-fixture'], parent_pid=1)
    monkeypatch.setattr(recording, 'process_identity', lambda pid: dict(expected))
    registry = tmp_path / 'registry'
    identity = recording.register_process(registry, 123, owner_run='unit', role='fixture',
                                         expected_identity=expected)
    files = list(registry.iterdir())
    assert len(files) == 1 and json.loads(files[0].read_text()) == identity
    assert all(identity[key] == value for key, value in expected.items())
