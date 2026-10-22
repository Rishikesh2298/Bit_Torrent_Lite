"""Pure installed-transfer helper controls; no child process or socket starts.

All fabricated byte/event fixtures below are unit inputs, never run evidence.
"""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bittorrent_lite.acceptance_tools import portability as p
from bittorrent_lite.acceptance_tools.inventory import snapshot, write_json_new
from bittorrent_lite.tests.end_to_end import support


def test_explicit_isolated_swarm_argv_uses_verified_python_and_forced_utf8(tmp_path, monkeypatch):
    monkeypatch.setattr(support, 'free_port', lambda: 19001)
    exe = tmp_path / 'verified python.exe'
    exe.write_bytes(b'unit-only fake executable; never run')
    digest = hashlib.sha256(exe.read_bytes()).hexdigest()
    swarm = support.Swarm(tmp_path / 'unrelated cwd \u03a9', 1,
                          python_executable=exe, python_sha256=digest, isolated=True)
    calls = []
    process = SimpleNamespace(pid=91000)
    def popen(argv, **kwargs):
        calls.append((argv, kwargs))
        return process
    monkeypatch.setattr(support.subprocess, 'Popen', popen)
    monkeypatch.setattr(support, '_register_child', lambda *a, **kw: {'pid': 91000})
    swarm.launch('peer', ['bittorrent_lite', '--peer-id', 'peer'])
    assert calls[0][0] == [str(exe), '-I', '-X', 'utf8', '-m', 'bittorrent_lite', '--peer-id', 'peer']
    assert calls[0][1]['cwd'] == swarm.root and 'PYTHONPATH' not in calls[0][1]['env']
    assert swarm.launches[0]['isolated'] is True and swarm.launches[0]['python_sha256'] == digest


@pytest.mark.parametrize('change', ['relative', 'wrong-hash', 'missing-hash', 'isolated-without-executable'])
def test_interpreter_override_requires_absolute_hash_verified_bytes(tmp_path, monkeypatch, change):
    monkeypatch.setattr(support, 'free_port', lambda: 19001)
    exe = tmp_path / 'python.exe'
    exe.write_bytes(b'unit fixture')
    kwargs = {'python_executable': exe, 'python_sha256': hashlib.sha256(exe.read_bytes()).hexdigest(), 'isolated': True}
    if change == 'relative': kwargs['python_executable'] = Path('python.exe')
    elif change == 'wrong-hash': kwargs['python_sha256'] = '0' * 64
    elif change == 'missing-hash': kwargs['python_sha256'] = None
    else: kwargs = {'isolated': True}
    with pytest.raises(ValueError):
        support.Swarm(tmp_path / 'swarm', 1, **kwargs)


def test_interpreter_mutation_between_construction_and_launch_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(support, 'free_port', lambda: 19001)
    exe = tmp_path / 'python.exe'
    exe.write_bytes(b'unit fixture')
    swarm = support.Swarm(tmp_path / 'swarm', 1, python_executable=exe,
        python_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(), isolated=True)
    exe.write_bytes(b'changed')
    monkeypatch.setattr(support.subprocess, 'Popen', lambda *a, **kw: pytest.fail('must reject before launch'))
    with pytest.raises(ValueError, match='changed before launch'):
        swarm.launch('peer', ['bittorrent_lite'])


def contract_fixture(tmp_path):
    repo = tmp_path / 'repo'
    for name in p.RESOURCES:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'{}')
    package = repo / 'bittorrent_lite/__init__.py'
    package.write_bytes(b'"""unit fixture"""')
    frozen = snapshot(repo)
    packaging = tmp_path / 'packaging'
    prefix = packaging / 'wheel environment \u03a9'
    exe = p.env_python(prefix)
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b'unit-only executable bytes')
    write_json_new(packaging / 'installed-spec.json', p.package_inventory(frozen))
    report = {'status': 'PASS', 'stage': 'offline-packaging', 'source_sha256': frozen['sha256'],
              'source_root': str(repo), 'installations': {'wheel': {'prefix': str(prefix), 'python': str(exe)}}}
    write_json_new(packaging / 'report.json', report)
    return packaging, prefix, exe, frozen, report


def test_installation_contract_binds_exact_packaging_source_and_prefix(tmp_path):
    packaging, prefix, exe, frozen, report = contract_fixture(tmp_path)
    actual_prefix, actual_exe, spec = p.installed_contract(packaging, 'wheel', frozen)
    assert actual_prefix == prefix and actual_exe == exe and spec == p.package_inventory(frozen)
    with pytest.raises(ValueError, match='unknown installation'):
        p.installed_contract(packaging, 'arbitrary-command', frozen)
    frozen = dict(frozen, sha256='0' * 64)
    with pytest.raises(ValueError, match='source differs'):
        p.installed_contract(packaging, 'wheel', frozen)


def test_failed_packaging_cannot_authorize_installed_transfer(tmp_path):
    packaging, prefix, exe, frozen, report = contract_fixture(tmp_path)
    report['status'] = 'FAIL'
    (packaging / 'report.json').write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(p.PrerequisiteBlocked, match='did not pass'):
        p.installed_contract(packaging, 'wheel', frozen)


def test_actual_installed_bytes_are_rehashed_not_only_manifest_claims(tmp_path):
    prefix = tmp_path / 'prefix'
    prefix.mkdir()
    source = prefix / 'module.py'
    source.write_bytes(b'original')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    spec = {'modules': [{'module': 'unit', 'sha256': digest}], 'resources': [], 'entrypoints': {}}
    observed = {'prefix': str(prefix), 'modules': [{'module': 'unit', 'origin': str(source), 'sha256': digest}],
                'resources': [], 'entrypoints': {}}
    p.verify_installed_bytes(observed, spec, prefix)
    source.write_bytes(b'changed')
    with pytest.raises(ValueError, match='actual installed file differs'):
        p.verify_installed_bytes(observed, spec, prefix)


def wire_fixture(tmp_path):
    source, output = tmp_path / 'source', tmp_path / 'output'
    source.write_bytes(b'unit bytes')
    output.write_bytes(source.read_bytes())
    pieces = tmp_path / 'pieces'
    pieces.mkdir()
    (pieces / '0.piece').write_bytes(source.read_bytes())
    send = {'event': 'frame_sent', 'message_type': 'PIECE', 'frame_complete': True,
            'remote': 'downloader', 'request_id': 3, 'piece': 0, 'payload_bytes': 10,
            'local_endpoint': ['127.0.0.1', 1234], 'remote_endpoint': ['127.0.0.1', 5678]}
    received = {'event': 'frame_received', 'message_type': 'PIECE', 'frame_complete': True,
                'remote': 'seeder', 'request_id': 3, 'piece': 0, 'payload_bytes': 10,
                'connection_id': 2, 'mono': 2, 'local_endpoint': ['127.0.0.1', 5678],
                'remote_endpoint': ['127.0.0.1', 1234]}
    commit = {'event': 'piece_verified', 'piece': 0, 'connection_id': 2, 'request_id': 3,
              'remote': 'seeder', 'bytes': 10, 'mono': 3}
    return source, output, pieces, [received, commit, {'event': 'complete', 'final_hash_ok': True}], [send]


def test_wire_provenance_requires_exact_bytes_and_matching_tcp_piece_path(tmp_path):
    source, output, pieces, downloader, seeder = wire_fixture(tmp_path)
    result = p.transfer_provenance(source, output, downloader, seeder, piece_root=pieces)
    assert result['byte_comparison'] is True and result['size'] == 10
    assert result['pieces'][0]['commit'] == downloader[1]


@pytest.mark.parametrize('change', ['missing-send', 'endpoint', 'commit-duplicate', 'wrong-request',
                                   'bad-output', 'bad-piece', 'false-complete', 'duplicate-complete'])
def test_installed_wire_oracle_rejects_synthetic_success_shortcuts(tmp_path, change):
    source, output, pieces, downloader, seeder = wire_fixture(tmp_path)
    if change == 'missing-send': seeder.clear()
    elif change == 'endpoint': seeder[0]['remote_endpoint'][1] += 1
    elif change == 'commit-duplicate': downloader.append(copy.deepcopy(downloader[1]))
    elif change == 'wrong-request': downloader[1]['request_id'] += 1
    elif change == 'bad-output': output.write_bytes(b'wrong data')
    elif change == 'bad-piece': (pieces / '0.piece').write_bytes(b'wrong data')
    elif change == 'false-complete': downloader[-1]['final_hash_ok'] = False
    elif change == 'duplicate-complete': downloader.append(copy.deepcopy(downloader[-1]))
    with pytest.raises(ValueError):
        p.transfer_provenance(source, output, downloader, seeder, piece_root=pieces)


def installed_swarm_with_real_store(tmp_path, *, size, reformat_metadata=False):
    """Real metadata/store/assembly, fabricated process and wire unit inputs.

    Exercise verify_installed_swarm's actual caller path without launching a
    process. A generic supplied piece_root missed the diagnostic-074 defect.
    """
    from bittorrent_lite.storage.file_store import FileStore
    from bittorrent_lite.storage.metadata import create_metadata, load_metadata, save_metadata

    source, meta = tmp_path / 'original bytes.bin', tmp_path / 'shared metadata.json'
    data = bytes(index % 251 for index in range(size))
    source.write_bytes(data)
    save_metadata(create_metadata(str(source)), str(meta))
    original_id = hashlib.sha256(meta.read_bytes()).hexdigest()
    if reformat_metadata:
        meta.write_text(json.dumps(json.loads(meta.read_bytes()), indent=2) + '\n', encoding='utf-8')
    file_id = hashlib.sha256(meta.read_bytes()).hexdigest()
    metadata, loaded_id = load_metadata(str(meta))
    assert loaded_id == file_id
    assert (file_id != original_id) == reformat_metadata
    store = FileStore(metadata, loaded_id, str(tmp_path / 'downloads/downloader/pieces'))
    assert store.pieces_dir == tmp_path / 'downloads/downloader/pieces' / file_id
    rows = {'tracker': [{'event': 'tracker_ready', 'mono': 0, 'port': 8000}],
            'seeder': [], 'downloader': []}
    for index in range(metadata.num_pieces):
        payload = data[index * 65536:(index + 1) * 65536]
        assert store.verify_and_store(index, payload)
        frame = {'message_type': 'PIECE', 'frame_complete': True, 'frame_bytes': len(payload) + 100,
                 'request_id': index + 1, 'piece': index, 'payload_bytes': len(payload)}
        rows['seeder'].append(dict(frame, event='frame_sent', mono=index * 3 + 1,
            connection_id=1, remote='downloader', expected_remote='downloader',
            local_endpoint=['127.0.0.1', 1234], remote_endpoint=['127.0.0.1', 5678]))
        rows['downloader'].append(dict(frame, event='frame_received', mono=index * 3 + 2,
            connection_id=2, remote='seeder', expected_remote='seeder',
            local_endpoint=['127.0.0.1', 5678], remote_endpoint=['127.0.0.1', 1234]))
        rows['downloader'].append({'event': 'piece_verified', 'mono': index * 3 + 3,
            'at': index * 3 + 3, 'peer_id': 'downloader', 'connection_id': 2,
            'remote': 'seeder', 'request_id': index + 1, 'piece': index, 'bytes': len(payload)})
    rows['downloader'].append({'event': 'complete', 'mono': metadata.num_pieces * 3 + 1,
                               'final_hash_ok': True})
    output = tmp_path / 'downloads/downloader' / source.name
    assert store.assemble_file(str(output))
    exe, executable_hash = tmp_path / 'unit-only python.exe', 'e' * 64
    children, launches, endings = [], [], []
    for index, name in enumerate(('tracker', 'seeder', 'downloader')):
        identity = {'pid': 90000 + index, 'unit_fixture': True}
        child = {'name': name, 'interpreter': identity}
        children.append(child)
        module = 'bittorrent_lite.discovery.tracker_server' if name == 'tracker' else 'bittorrent_lite'
        launches.append({'name': name, 'command': [str(exe), '-I', '-X', 'utf8', '-m', module],
                         'isolated': True, 'python_sha256': executable_hash, 'identity': identity})
        code = 15 if name == 'tracker' and p.os.name == 'nt' else 0
        end = {'name': name, 'identity': identity, 'interpreter': identity,
               'interpreter_exit_code': code, 'exit_code': code, 'expected_exit_code': code,
               'deliberate_kill': name == 'tracker' and code != 0}
        if name == 'tracker':
            end['termination_contract'] = {'api': 'psutil.Process.terminate', 'platform': p.os.name,
                                           'expected_exit_codes': [15] if p.os.name == 'nt' else [0, -15]}
        endings.append(end)
        for sequence, row in enumerate(rows[name]):
            row.update(proc=name, log_schema='btl-log-v1', log_sequence=sequence,
                       log_pid=identity['pid'])
    write_json_new(tmp_path / 'results.json', {'cleanup_errors': [], 'processes': endings})
    swarm = SimpleNamespace(root=tmp_path, source=source, meta=meta, size=size,
        digest=hashlib.sha256(data).hexdigest(), children=children, launches=launches,
        structured_events=lambda child: rows[child['name']])
    return swarm, exe, executable_hash, store


@pytest.mark.parametrize('size,reformat', [(1, False), (65537, False), (65537, True)],
                         ids=['one-byte', 'short-final-piece', 'exact-reformatted-metadata-bytes'])
def test_installed_swarm_caller_uses_real_filestore_metadata_namespace(tmp_path, size, reformat):
    swarm, exe, executable_hash, store = installed_swarm_with_real_store(
        tmp_path, size=size, reformat_metadata=reformat)
    assert not (store.pieces_dir.parent / '0.piece').exists()
    proof = p.verify_installed_swarm(swarm, exe, executable_hash)
    assert proof['status'] == 'PASS' and proof['size'] == size
    assert proof['network_provenance']['byte_comparison'] is True
    pieces = proof['network_provenance']['pieces']
    assert [row['piece'] for row in pieces] == list(range(store.metadata.num_pieces))
    assert sum(row['size'] for row in pieces) == size


def test_installed_swarm_cannot_use_flat_or_source_hash_piece_decoys(tmp_path):
    swarm, exe, executable_hash, store = installed_swarm_with_real_store(tmp_path, size=1)
    # Retain the real piece under another name, then provide valid bytes only in
    # two wrong namespaces. The caller must require the exact metadata-byte ID.
    actual = store.pieces_dir / '0.piece'
    actual.rename(store.pieces_dir / '0.piece.retained')
    (store.pieces_dir.parent / '0.piece').write_bytes(swarm.source.read_bytes())
    decoy = store.pieces_dir.parent / swarm.digest
    assert decoy != store.pieces_dir
    decoy.mkdir()
    (decoy / '0.piece').write_bytes(swarm.source.read_bytes())
    with pytest.raises(FileNotFoundError):
        p.verify_installed_swarm(swarm, exe, executable_hash)


def test_worker_report_cannot_claim_acceptance_credit(tmp_path):
    write_json_new(tmp_path / 'report.json', {'stage': 'installed-transfer-worker', 'status': 'PASS',
        'kind': 'wheel', 'source_sha256': 'a' * 64, 'source_preserved': True,
        'source_isolation_verified': False, 'acceptance_eligible': True})
    with pytest.raises(ValueError, match='exact diagnostic contract'):
        p.verify_installed_worker_report(tmp_path, 'wheel', {'sha256': 'a' * 64})


def test_installed_stage_rejects_missing_outer_recorder_without_any_child_launch(tmp_path, monkeypatch):
    packaging, prefix, exe, frozen, report = contract_fixture(tmp_path)
    monkeypatch.delenv('ACCEPTANCE_PROCESS_REGISTRY', raising=False)
    monkeypatch.setattr(p, 'Driver', lambda *_: pytest.fail('must block before launching'))
    result = p.run_installed_transfer(packaging, tmp_path / 'out')
    assert result['status'] == 'BLOCKED' and result['acceptance_ready'] is False
