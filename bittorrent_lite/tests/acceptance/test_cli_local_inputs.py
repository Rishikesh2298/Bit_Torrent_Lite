"""Local configuration rejection must precede sockets and output creation."""
import json
import os
from pathlib import Path

import pytest

from bittorrent_lite.application.cli import main
from bittorrent_lite.storage.metadata import create_metadata, load_metadata, save_metadata


def fixture(tmp_path, *, piece_size=65536, filename='input bytes \u03a9.bin'):
    source = tmp_path / filename
    source.write_bytes(b'\x00\xffunique fixture')
    metadata = tmp_path / 'metadata with spaces.json'
    save_metadata(create_metadata(str(source), piece_size), str(metadata))
    output = tmp_path / 'output with spaces \u03a9'
    args = ['--peer-id', 'peer-01', '--port', '19001', '--metadata', str(metadata),
            '--output-dir', str(output), '--check-config']
    return source, metadata, output, args


def forbidden_backend(*args):
    raise AssertionError('local validation must never construct a backend')


def test_check_config_accepts_unicode_spaces_from_unrelated_cwd_without_writes(tmp_path, monkeypatch, capsys):
    source, metadata, output, args = fixture(tmp_path)
    unrelated = tmp_path / 'unrelated cwd'
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert main(args + ['--seeder', '--file', str(source)], backend_factory=forbidden_backend) == 0
    record = json.loads(capsys.readouterr().out)
    assert record['num_pieces'] == 1 and record['peer_id'] == 'peer-01'
    assert not output.exists()
    assert {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == before


@pytest.mark.parametrize('tracker', ['ftp://host', 'http://', 'http://name:pass@host',
                                    'http://host:0', 'http://host:65536', 'http://host:invalid'])
def test_check_config_rejects_invalid_tracker_before_output_creation(tmp_path, tracker, capsys):
    _, _, output, args = fixture(tmp_path)
    assert main(args + ['--tracker', tracker], backend_factory=forbidden_backend) == 2
    assert capsys.readouterr().err
    assert not output.exists()


def test_check_config_rejects_network_oversize_without_changing_generic_metadata(tmp_path, capsys):
    _, metadata, output, args = fixture(tmp_path, piece_size=65537)
    assert load_metadata(str(metadata))[0].piece_size == 65537
    assert main(args, backend_factory=forbidden_backend) == 2
    assert '65536' in capsys.readouterr().err
    assert not output.exists()


@pytest.mark.parametrize('name', ['CON', 'con.txt', 'NUL.dat', 'COM1.bin', 'LPT9',
                                 'ending.', 'ending ', 'a/b', 'a\\b', '../escape',
                                 'a:b', 'a?b', 'a*b', 'a|b', 'a<b', 'a>b', 'a"b', 'a\x01b'])
def test_check_config_rejects_nonportable_output_names(tmp_path, name, capsys):
    _, metadata, output, args = fixture(tmp_path)
    value = json.loads(metadata.read_text())
    value['filename'] = name
    metadata.write_text(json.dumps(value), encoding='utf-8')
    assert main(args, backend_factory=forbidden_backend) == 2
    assert 'plain filename' in capsys.readouterr().err
    assert not output.exists()


def test_check_config_rejects_source_hardlink_collision_and_preserves_both(tmp_path, capsys):
    source, metadata, output, args = fixture(tmp_path)
    final = output / 'peer-01' / source.name
    final.parent.mkdir(parents=True)
    os.link(source, final)
    before = source.read_bytes()
    assert main(args + ['--seeder', '--file', str(source)], backend_factory=forbidden_backend) == 2
    assert 'overwrite' in capsys.readouterr().err
    assert source.read_bytes() == final.read_bytes() == before
    assert not (final.parent / 'pieces').exists()


def test_check_config_rejects_changed_source_bytes_before_network_or_output(tmp_path, capsys):
    source, _, output, args = fixture(tmp_path)
    source.write_bytes(b'\x01' + source.read_bytes()[1:])
    assert main(args + ['--seeder', '--file', str(source)], backend_factory=forbidden_backend) == 2
    assert capsys.readouterr().err
    assert not output.exists()


def test_bounded_deep_metadata_is_controlled_rejection_without_traceback(tmp_path, capsys):
    path = tmp_path / 'deep.json'
    # The Python 3.12 C parser accepts 2,000 levels on this interpreter;
    # 4,000 levels reaches its recursion guard while staying below the byte cap.
    raw = b'[' * 4000 + b'0' + b']' * 4000
    path.write_bytes(raw)
    with pytest.raises(ValueError, match='nesting'):
        load_metadata(str(path))
    assert main(['--peer-id', 'peer-01', '--port', '19001', '--metadata', str(path),
                 '--check-config'], backend_factory=forbidden_backend) == 2
    assert 'Traceback' not in capsys.readouterr().err
    assert path.read_bytes() == raw
