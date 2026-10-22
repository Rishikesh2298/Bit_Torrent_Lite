"""Independent byte and artifact oracles. Does not import product storage code."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

from .inventory import canonical_bytes, checked_path, digest_file, is_redirect, write_json_new


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def strict_json(raw: bytes | str):
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8', errors='strict')
    if not isinstance(raw, str) or raw.startswith('\ufeff'):
        raise ValueError('evidence JSON must be UTF-8 without BOM')
    def reject(value):
        raise ValueError(f'nonfinite JSON number: {value}')
    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            reject(value)
        return number
    return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=reject,
                      parse_float=finite_float)


def file_oracle(path: Path, piece_size=65536):
    if type(piece_size) is not int or piece_size <= 0:
        raise ValueError('positive integer piece size required')
    whole = hashlib.sha256()
    pieces = []
    size = 0
    with path.open('rb') as handle:
        while chunk := handle.read(piece_size):
            whole.update(chunk)
            pieces.append({'index': len(pieces), 'size': len(chunk),
                           'sha256': hashlib.sha256(chunk).hexdigest()})
            size += len(chunk)
    return {'size': size, 'sha256': whole.hexdigest(), 'piece_size': piece_size, 'pieces': pieces}


def compare_files(source: Path, output: Path, expected=None):
    actual_source = file_oracle(source)
    if expected is not None and actual_source != expected:
        raise ValueError('source oracle mismatch')
    actual_output = file_oracle(output)
    if actual_source != actual_output:
        raise ValueError('file size/piece/whole digest mismatch')
    with source.open('rb') as first, output.open('rb') as second:
        while left := first.read(1024 * 1024):
            if left != second.read(len(left)):
                raise ValueError('byte equality failed')
        if second.read(1):
            raise ValueError('trailing output bytes')
    return actual_output


def create_fixture(path: Path, *, size: int, token: str, source_freeze: str,
                   provider: str, lane: str, random_bytes=False):
    if type(size) is not int or not 1 <= size <= 64 * 1024 * 1024:
        raise ValueError('fixture size must be 1..64 MiB')
    if (not isinstance(token, str) or not token or not isinstance(provider, str) or not provider
            or not isinstance(source_freeze, str) or len(source_freeze) != 64
            or any(char not in '0123456789abcdef' for char in source_freeze)):
        raise ValueError('post-freeze challenge provenance required')
    if lane not in {'diagnostic', 'acceptance'}:
        raise ValueError('explicit fixture lane required')
    path = checked_path(path)
    if path.exists() or path.with_suffix(path.suffix + '.oracle.json').exists():
        raise FileExistsError('fixture and oracle destinations must be fresh')
    # Each piece has its own seed and index prefix; no repeated 64 KiB block.
    with path.open('xb') as handle:
        for index, offset in enumerate(range(0, size, 65536)):
            length = min(65536, size - offset)
            seed = token.encode('utf-8') + b'\0' + index.to_bytes(8, 'big')
            block = bytearray(os.urandom(length) if random_bytes else hashlib.shake_256(seed).digest(length))
            if length >= 20:
                block[0] = index % 256
                block[1:11] = index.to_bytes(8, 'big') + b'\0\xff'
                block[-9:-1] = ((1 << 64) - index - 1).to_bytes(8, 'big')
                block[-1] = (index + 127) % 256
            handle.write(block)
    oracle = file_oracle(path)
    record = {'lane': lane, 'provider': provider, 'source_freeze': source_freeze,
              'token_sha256': hashlib.sha256(token.encode('utf-8')).hexdigest(),
              'random_bytes': random_bytes, 'oracle': oracle}
    write_json_new(path.with_suffix(path.suffix + '.oracle.json'), record)
    return record


def verify_metadata(source: Path, metadata: Path):
    value = strict_json(metadata.read_bytes())
    expected = file_oracle(source)
    required = {'format_version', 'filename', 'file_size', 'piece_size', 'file_sha256', 'piece_hashes'}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError('metadata field schema mismatch')
    if (type(value['format_version']) is not int or value['format_version'] != 1
            or type(value['file_size']) is not int or type(value['piece_size']) is not int
            or not isinstance(value['filename'], str) or value['filename'] != source.name
            or not isinstance(value['piece_hashes'], list)
            or not isinstance(value['file_sha256'], str)
            or any(not isinstance(digest, str) for digest in value['piece_hashes'])):
        raise ValueError('metadata field type/version/name mismatch')
    if (value['file_size'] != expected['size'] or value['piece_size'] != expected['piece_size']
            or value['file_sha256'] != expected['sha256']
            or value['piece_hashes'] != [p['sha256'] for p in expected['pieces']]):
        raise ValueError('metadata does not describe independently hashed source bytes')
    return {**expected, 'metadata_sha256': digest_file(metadata)}


def strict_events(path: Path, *, expected_proc: str, deliberate_kill=False,
                  corroborated_kill=None, require_sequence=False, expected_pid=None):
    """Preserve an interrupted tail separately; never infer missing metrics."""
    raw = path.read_bytes()
    if require_sequence and (type(expected_pid) is not int or expected_pid <= 0):
        raise ValueError('sequenced evidence requires independently observed interpreter PID')
    if not raw:
        raise ValueError(f'empty required event stream: {path}')
    lines = raw.splitlines(keepends=True)
    tail = b''
    if not lines[-1].endswith(b'\n'):
        if not deliberate_kill or not corroborated_kill:
            raise ValueError(f'unexpected truncated event stream: {path}')
        tail = lines.pop()
    records = []
    previous = -math.inf
    for number, line in enumerate(lines, 1):
        try:
            value = strict_json(line.decode('utf-8'))
            if not isinstance(value, dict) or not isinstance(value.get('event'), str) or not value['event']:
                raise ValueError('event name missing')
            if value.get('proc') != expected_proc:
                raise ValueError('process identity mismatch')
            if require_sequence and (value.get('log_schema') != 'btl-log-v1'
                    or type(value.get('log_sequence')) is not int
                    or value['log_sequence'] != number - 1
                    or type(value.get('log_pid')) is not int
                    or value['log_pid'] != expected_pid):
                raise ValueError('missing/reordered event or incorrect interpreter PID')
            mono = value.get('mono')
            if type(mono) not in (float, int) or not math.isfinite(mono) or mono < previous:
                raise ValueError('invalid/nonmonotonic timestamp')
            previous = mono
            records.append(value)
        except (ValueError, TypeError, UnicodeError) as exc:
            raise ValueError(f'{path}:{number}: {exc}') from exc
    if not records:
        raise ValueError('no complete event records')
    return records, tail


def exact_ids(expected, actual, *, label):
    if len(expected) != len(set(expected)) or len(actual) != len(set(actual)):
        raise ValueError(f'duplicate {label} identities')
    if set(expected) != set(actual):
        raise ValueError(f'{label} identities differ: missing={sorted(set(expected)-set(actual))}, '
                         f'extra={sorted(set(actual)-set(expected))}')


def seal_tree(root: Path, destination: Path, *, previous: str, source_freeze: str):
    root = checked_path(root, strict=True)
    destination = checked_path(destination)
    if destination.is_relative_to(root):
        raise ValueError('seal must live outside the immutable artifact subtree it hashes')
    entries = []
    for path in _artifact_files(root):
        entries.append({'path': path.relative_to(root).as_posix(),
                        'size': path.stat().st_size, 'sha256': digest_file(path)})
    if not entries:
        raise ValueError('cannot seal empty evidence')
    payload = {'schema': 1, 'previous': previous, 'source_freeze': source_freeze, 'files': entries}
    seal = {**payload, 'sha256': hashlib.sha256(canonical_bytes(payload)).hexdigest()}
    write_json_new(destination, seal)
    return seal


def verify_seal(root: Path, seal: dict):
    root = checked_path(root, strict=True)
    payload = {k: v for k, v in seal.items() if k != 'sha256'}
    if hashlib.sha256(canonical_bytes(payload)).hexdigest() != seal.get('sha256'):
        raise ValueError('seal digest invalid')
    expected = [entry['path'] for entry in seal['files']]
    actual = [p.relative_to(root).as_posix() for p in _artifact_files(root)]
    exact_ids(expected, actual, label='artifact')
    for entry in seal['files']:
        path = checked_path(root / entry['path'], strict=True)
        if not path.is_relative_to(root):
            raise ValueError('unsafe artifact path')
        if path.stat().st_size != entry['size'] or digest_file(path) != entry['sha256']:
            raise ValueError(f'artifact changed: {entry["path"]}')


def _artifact_files(root: Path):
    """Do not traverse any redirected directory while building an artifact set."""
    for path in sorted(root.iterdir()):
        if is_redirect(path):
            raise ValueError(f'artifact redirection forbidden: {path}')
        if path.is_dir():
            yield from _artifact_files(path)
        elif path.is_file():
            yield path
        else:
            raise ValueError(f'nonregular artifact: {path}')


def require_ready(gate: dict, *, expected_inventory=None, evidence_root=None):
    """No generic force/skip option: unresolved requirements cannot be frozen."""
    required = {'cases', 'modules', 'helpers', 'dependencies', 'resources', 'decisions', 'review'}
    if set(gate) != required:
        raise ValueError('preparation gate requires every explicit ledger')
    if expected_inventory is None or set(expected_inventory) != required or evidence_root is None:
        raise ValueError('reviewed exact expected inventory and evidence root required')
    evidence_root = checked_path(evidence_root, strict=True)
    for group, rows in gate.items():
        expected = expected_inventory[group]
        if not rows or not isinstance(expected, list) or not expected:
            raise ValueError(f'empty preparation ledger: {group}')
        if any(not isinstance(identity, str) or not identity.strip() for identity in expected):
            raise ValueError(f'invalid expected inventory: {group}')
        if any(not isinstance(row, dict) or not isinstance(row.get('id'), str)
               or not row['id'].strip() for row in rows):
            raise ValueError(f'invalid actual inventory: {group}')
        exact_ids(expected, [row.get('id') for row in rows], label=f'preparation {group}')
        for row in rows:
            if (row.get('status') != 'READY' or not isinstance(row.get('evidence'), list)
                    or not row['evidence'] or not isinstance(row.get('reviewer'), str)
                    or not row['reviewer'].strip()):
                raise ValueError(f'preparation blocked: {group}/{row.get("id", "unknown")}')
            if group in {'cases', 'modules', 'helpers'} and (
                    not isinstance(row.get('methods'), list) or not row['methods']
                    or any(not isinstance(m, str) or not m.strip() for m in row['methods'])
                    or not row.get('oracle') or row.get('assertions_reviewed') is not True):
                raise ValueError(f'preparation method/assertion review missing: {group}/{row["id"]}')
            for artifact in row['evidence']:
                if not isinstance(artifact, dict) or set(artifact) != {'path', 'sha256'}:
                    raise ValueError('hashed evidence references required')
                if (not isinstance(artifact['path'], str) or not artifact['path']
                        or Path(artifact['path']).is_absolute() or '..' in Path(artifact['path']).parts):
                    raise ValueError('unsafe preparation evidence path')
                path = checked_path(evidence_root / artifact['path'], strict=True)
                if not path.is_relative_to(evidence_root) or not path.is_file():
                    raise ValueError('unsafe preparation evidence path')
                if digest_file(path) != artifact['sha256']:
                    raise ValueError('preparation evidence hash mismatch')
