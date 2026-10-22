"""Piece provider adapters. A provider is ``read_piece(index) -> bytes``."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Mapping

from bittorrent_lite.scheduling.upload_service.models import Manifest

__all__ = ["MemorySource", "DirectorySource"]


class MemorySource:
    """Serves pieces from a private copy of a mapping.

    The retained bytes are caller-owned source storage, separate from the
    service's transient memory budget. The service still verifies digests.
    """

    def __init__(self, manifest: Manifest, pieces: Mapping[int, bytes]) -> None:
        if not isinstance(manifest, Manifest):
            raise TypeError("manifest must be a Manifest")
        copied = dict(pieces)
        if any(type(index) is not int for index in copied):
            raise ValueError("piece keys must be integer indices")
        expected = {p.index for p in manifest.pieces}
        if set(copied) != expected:
            raise ValueError("pieces must have exactly the manifest's indices")
        for meta in manifest.pieces:
            value = copied[meta.index]
            if type(value) is not bytes:
                raise ValueError(f"piece {meta.index} must be an immutable bytes object")
            if len(value) != meta.length:
                raise ValueError(f"piece {meta.index} has the wrong length")
        self._manifest = manifest
        self._pieces = copied

    def __call__(self, index: int) -> bytes:
        return self._pieces[index]


class DirectorySource:
    """Reads ``piece-000000.bin``, ``piece-000001.bin``, ... under ``root``.

    Only generated filenames are used. Symbolic links and paths resolving
    outside ``root`` are rejected. A fresh stream is opened per call and at
    most ``length + 1`` bytes are read. Files must stay immutable while the
    service runs. Failures raise (the service reports ``source_error``).
    """

    def __init__(self, manifest: Manifest, root: str | Path) -> None:
        if not isinstance(manifest, Manifest):
            raise TypeError("manifest must be a Manifest")
        resolved = Path(os.path.realpath(root))
        if not resolved.is_dir():
            raise ValueError("root must be an existing directory")
        self._manifest = manifest
        self._root = resolved

    def __call__(self, index: int) -> bytes:
        if isinstance(index, bool) or not isinstance(index, int):
            raise TypeError("index must be an integer")
        if not 0 <= index < len(self._manifest.pieces):
            raise IndexError("unknown piece index")
        length = self._manifest.pieces[index].length
        path = self._root / f"piece-{index:06d}.bin"
        if stat.S_ISLNK(os.lstat(path).st_mode):
            raise ValueError("symbolic links are not permitted")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError("piece path is not a regular file")
            if Path(os.path.realpath(path)).parent != self._root:
                raise ValueError("piece path resolves outside root")
            with os.fdopen(fd, "rb") as stream:
                fd = -1  # ownership moved to the stream
                data = stream.read(length + 1)
        finally:
            if fd != -1:
                os.close(fd)
        if len(data) != length:
            raise ValueError("piece file length does not match the manifest")
        return data
