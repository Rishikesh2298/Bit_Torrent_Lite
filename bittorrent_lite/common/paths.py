"""Locate a source checkout without relying on a username or working directory."""
from pathlib import Path


def project_root() -> Path:
    """Find this checkout's packaging marker, with a readable installed-copy error."""
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").is_file() and (candidate / "bittorrent_lite").is_dir():
            return candidate
    raise RuntimeError(
        "Experiment tooling requires a source checkout. Clone the project and "
        "install it with python -m pip install -e ."
    )
