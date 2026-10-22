"""Predeclared verifier negative controls; all files are isolated fixtures."""
import hashlib
import json
import copy

import pytest

from bittorrent_lite.acceptance_tools.evidence import (
    compare_files, create_fixture, exact_ids, file_oracle, require_ready,
    seal_tree, strict_events, strict_json, verify_metadata, verify_seal,
)
from bittorrent_lite.acceptance_tools.inventory import compare_snapshots, resource_rows, snapshot


def test_distinct_piece_fixture_and_independent_tamper_controls(tmp_path):
    source = tmp_path / 'source.bin'
    record = create_fixture(source, size=12 * 65536 + 9, token='DIAGNOSTIC ONLY',
                            source_freeze='0' * 64, provider='test fixture', lane='diagnostic')
    pieces = record['oracle']['pieces']
    assert len({p['sha256'] for p in pieces}) == 13
    data = source.read_bytes()
    for index in range(12):
        block = data[index * 65536:(index + 1) * 65536]
        assert block[0] == index % 256
        assert block[1:11] == index.to_bytes(8, 'big') + b'\0\xff'
        assert block[-1] == (index + 127) % 256
    target = tmp_path / 'output.bin'
    target.write_bytes(source.read_bytes())
    compare_files(source, target, record['oracle'])
    data = bytearray(target.read_bytes())
    data[65540] ^= 1
    target.write_bytes(data)
    with pytest.raises(ValueError, match='mismatch'):
        compare_files(source, target)
    target.write_bytes(source.read_bytes()[:-1])
    with pytest.raises(ValueError, match='mismatch'):
        compare_files(source, target)
    with pytest.raises(FileExistsError):
        create_fixture(source, size=1, token='no overwrite', source_freeze='0' * 64,
                       provider='test', lane='diagnostic')


@pytest.mark.parametrize('raw', ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}',
                                 '{"x":1e999}', '{"x":[-1e999]}',
                                 b'\xef\xbb\xbf{"x":1}', '\ufeff{"x":1}'])
def test_strict_json_rejects_ambiguous_evidence(raw):
    with pytest.raises(ValueError):
        strict_json(raw)


def test_exact_identity_reconciliation_rejects_missing_duplicate_and_extra():
    for actual in (['a'], ['a', 'a'], ['a', 'b', 'c']):
        with pytest.raises(ValueError):
            exact_ids(['a', 'b'], actual, label='test')
    exact_ids(['a', 'b'], ['b', 'a'], label='test')


@pytest.mark.parametrize('fault', ['gap', 'duplicate', 'pid', 'schema', 'bool-sequence'])
def test_strict_sequence_rejects_lost_reordered_or_unbound_events(tmp_path, fault):
    path = tmp_path / 'events.jsonl'
    rows = [dict(proc='p', event='observed', mono=i, log_schema='btl-log-v1',
                 log_sequence=i, log_pid=123) for i in range(3)]
    def write():
        path.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
    write()
    assert len(strict_events(path, expected_proc='p', require_sequence=True, expected_pid=123)[0]) == 3
    if fault == 'gap':
        rows.pop(1)
    elif fault == 'duplicate':
        rows[1]['log_sequence'] = 0
    elif fault == 'pid':
        rows[1]['log_pid'] = 456
    elif fault == 'schema':
        rows[1].pop('log_schema')
    else:
        rows[1]['log_sequence'] = True
    write()
    with pytest.raises(ValueError, match='missing/reordered'):
        strict_events(path, expected_proc='p', require_sequence=True, expected_pid=123)
    with pytest.raises(ValueError, match='independently observed'):
        strict_events(path, expected_proc='p', require_sequence=True)


def test_truncation_exception_needs_predeclared_corroborated_kill(tmp_path):
    path = tmp_path / 'events.jsonl'
    line = b'{"proc":"p","event":"request","mono":1}\n'
    path.write_bytes(line + b'{"proc":')
    with pytest.raises(ValueError):
        strict_events(path, expected_proc='p')
    with pytest.raises(ValueError):
        strict_events(path, expected_proc='p', deliberate_kill=True)
    events, tail = strict_events(path, expected_proc='p', deliberate_kill=True,
                                 corroborated_kill={'pid': 1, 'reason': 'test fixture only'})
    assert len(events) == 1 and tail == b'{"proc":'
    path.write_bytes(b'invalid\n' + line + b'{')
    with pytest.raises(ValueError, match=':1:'):
        strict_events(path, expected_proc='p', deliberate_kill=True, corroborated_kill={'fixture': True})


def test_seal_rejects_changed_missing_and_inserted_artifacts(tmp_path):
    root = tmp_path / 'raw'
    root.mkdir()
    path = root / 'log'
    path.write_bytes(b'actual diagnostic fixture')
    seal = seal_tree(root, tmp_path / 'seal.json', previous='GENESIS', source_freeze='0' * 64)
    verify_seal(root, seal)
    path.write_bytes(b'changed')
    with pytest.raises(ValueError, match='changed'):
        verify_seal(root, seal)
    path.unlink()
    with pytest.raises(ValueError, match='identities differ'):
        verify_seal(root, seal)
    path.write_bytes(b'actual diagnostic fixture')
    (root / 'synthetic-manifest.json').write_text('{}')
    with pytest.raises(ValueError, match='identities differ'):
        verify_seal(root, seal)


def test_snapshot_includes_untracked_source_and_detects_changes(tmp_path):
    (tmp_path / 'untracked.py').write_text('value = 1\n')
    before = snapshot(tmp_path)
    assert [f['path'] for f in before['files']] == ['untracked.py']
    (tmp_path / 'untracked.py').write_text('value = 2\n')
    with pytest.raises(ValueError, match='frozen source changed'):
        compare_snapshots(before, snapshot(tmp_path))


def _ready_fixture(tmp_path):
    artifact = tmp_path / 'review-fixture.txt'
    artifact.write_bytes(b'Only a unit-test fixture, never an independent review attestation.')
    row = {'id': 'case', 'status': 'READY',
           'evidence': [{'path': artifact.name, 'sha256': hashlib.sha256(artifact.read_bytes()).hexdigest()}],
           'reviewer': 'unit-test fixture', 'methods': ['fixture-method'],
           'oracle': 'fixture oracle', 'assertions_reviewed': True}
    groups = ('cases', 'modules', 'helpers', 'dependencies', 'resources', 'decisions', 'review')
    return {name: [copy.deepcopy(row)] for name in groups}, {name: ['case'] for name in groups}


def test_preparation_cannot_accept_empty_or_unreviewed_ledgers(tmp_path):
    with pytest.raises(ValueError):
        require_ready({})
    gate, expected = _ready_fixture(tmp_path)
    with pytest.raises(ValueError, match='expected inventory'):
        require_ready(gate)
    require_ready(gate, expected_inventory=expected, evidence_root=tmp_path)
    gate['cases'][0]['status'] = 'BLOCKED'
    with pytest.raises(ValueError, match='preparation blocked'):
        require_ready(gate, expected_inventory=expected, evidence_root=tmp_path)


def test_readiness_rejects_omitted_duplicate_or_unreviewed_mandatory_rows(tmp_path):
    gate, expected = _ready_fixture(tmp_path)
    expected['cases'].append('mandatory-unmapped')
    with pytest.raises(ValueError, match='identities differ'):
        require_ready(gate, expected_inventory=expected, evidence_root=tmp_path)
    expected['cases'].pop()
    gate['cases'].append(copy.deepcopy(gate['cases'][0]))
    with pytest.raises(ValueError, match='duplicate'):
        require_ready(gate, expected_inventory=expected, evidence_root=tmp_path)
    gate['cases'].pop()
    gate['cases'][0]['assertions_reviewed'] = False
    with pytest.raises(ValueError, match='assertion review'):
        require_ready(gate, expected_inventory=expected, evidence_root=tmp_path)


def test_readiness_rechecks_evidence_hash_and_rejects_outside_paths(tmp_path):
    gate, expected = _ready_fixture(tmp_path)
    gate['cases'][0]['evidence'][0]['sha256'] = 'f' * 64
    with pytest.raises(ValueError, match='hash mismatch'):
        require_ready(gate, expected_inventory=expected, evidence_root=tmp_path)
    gate['cases'][0]['evidence'][0]['path'] = str(tmp_path.parent)
    with pytest.raises(ValueError, match='unsafe'):
        require_ready(gate, expected_inventory=expected, evidence_root=tmp_path)


def test_seal_destination_cannot_normalize_back_inside_artifacts(tmp_path):
    root = tmp_path / 'raw'
    root.mkdir()
    (root / 'log').write_bytes(b'fixture')
    outside = tmp_path / 'outside'
    outside.mkdir()
    with pytest.raises(ValueError, match='outside'):
        seal_tree(root, outside / '..' / 'raw' / 'seal.json', previous='GENESIS', source_freeze='0' * 64)
    assert not (root / 'seal.json').exists()


def test_root_or_ancestor_redirection_is_rejected_before_normalization(tmp_path, monkeypatch):
    from bittorrent_lite.acceptance_tools import inventory
    root = tmp_path / 'root'
    root.mkdir()
    (root / 'code.py').write_text('x=1')
    original = inventory.is_redirect
    monkeypatch.setattr(inventory, 'is_redirect', lambda p: p == tmp_path or original(p))
    with pytest.raises(ValueError, match='redirection'):
        snapshot(root)


def test_sealer_rejects_directory_redirection_before_traversal(tmp_path, monkeypatch):
    from bittorrent_lite.acceptance_tools import evidence
    root = tmp_path / 'root'
    root.mkdir()
    redirect = root / 'redirect'
    redirect.mkdir()
    (redirect / 'secret').write_bytes(b'fixture only')
    original = evidence.is_redirect
    monkeypatch.setattr(evidence, 'is_redirect', lambda p: p == redirect or original(p))
    with pytest.raises(ValueError, match='redirection'):
        seal_tree(root, tmp_path / 'seal.json', previous='GENESIS', source_freeze='0' * 64)


def test_nonpython_resources_are_explicitly_inventoried_without_coverage_credit(tmp_path):
    (tmp_path / 'config.json').write_text('{}')
    (tmp_path / 'README.md').write_text('Instructions')
    (tmp_path / 'main.py').write_text('value=1')
    rows = list(resource_rows(tmp_path))
    assert {row['path'] for row in rows} == {'config.json', 'README.md'}
    assert all(row['status'] == 'BLOCKED' and not row['methods'] for row in rows)


def test_fixture_rejects_nonhex_freeze_before_writing(tmp_path):
    path = tmp_path / 'source.bin'
    with pytest.raises(ValueError, match='provenance'):
        create_fixture(path, size=1, token='diagnostic', provider='test',
                       source_freeze='z' * 64, lane='diagnostic')
    assert not path.exists()


def test_independent_metadata_oracle_rejects_boolean_version_and_wrong_name(tmp_path):
    source = tmp_path / 'source.bin'
    source.write_bytes(b'\x00\xffbinary fixture')
    expected = file_oracle(source)
    metadata = tmp_path / 'metadata.json'
    value = {'format_version': 1, 'filename': source.name, 'file_size': expected['size'],
             'piece_size': 65536, 'file_sha256': expected['sha256'],
             'piece_hashes': [p['sha256'] for p in expected['pieces']]}
    metadata.write_text(json.dumps(value), encoding='utf-8')
    assert verify_metadata(source, metadata)['size'] == source.stat().st_size
    for field, bad in [('format_version', True), ('file_size', True), ('filename', 'wrong.bin')]:
        metadata.write_text(json.dumps({**value, field: bad}), encoding='utf-8')
        with pytest.raises(ValueError, match='type/version/name'):
            verify_metadata(source, metadata)
