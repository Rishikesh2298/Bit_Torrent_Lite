"""Exercise installed entry points without starting networking or a swarm."""
import hashlib
import json
import os
import subprocess
import sys

import pytest

from bittorrent_lite.common.paths import project_root


def isolated_environment():
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    return env


def test_project_root_does_not_depend_on_working_directory(tmp_path, monkeypatch):
    expected = project_root()
    unrelated = tmp_path / "unrelated folder with spaces"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)
    assert project_root() == expected
    assert (expected / "pyproject.toml").is_file()


@pytest.mark.parametrize("module", [
    "bittorrent_lite",
    "bittorrent_lite.application.cli",
    "bittorrent_lite.discovery.tracker_server",
])
def test_installed_help_commands_from_another_directory(tmp_path, module):
    result = subprocess.run(
        [sys.executable, "-m", module, "--help"], cwd=tmp_path,
        env=isolated_environment(), capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()


def test_metadata_cli_accepts_paths_with_spaces_outside_checkout(tmp_path):
    folder = tmp_path / "source and metadata"
    folder.mkdir()
    source = folder / "binary source.bin"
    output = folder / "saved metadata.json"
    content = bytes(range(256)) * 257
    source.write_bytes(content)
    result = subprocess.run(
        [sys.executable, "-m", "bittorrent_lite.storage.generate_metadata",
         "--file", str(source), "--output", str(output)],
        cwd=tmp_path, env=isolated_environment(), capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    metadata = json.loads(output.read_text("utf-8"))
    assert metadata["file_size"] == len(content)
    assert metadata["file_sha256"] == hashlib.sha256(content).hexdigest()
    assert len(metadata["piece_hashes"]) == 2
    assert source.read_bytes() == content
