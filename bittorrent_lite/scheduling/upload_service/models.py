"""Records, manifest loading, and configuration for the upload service."""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Union

__all__ = [
    "MAX_PIECE_LENGTH",
    "MAX_PIECES",
    "MAX_MANIFEST_FILE_BYTES",
    "ManifestError",
    "PieceMeta",
    "Manifest",
    "load_manifest",
    "UploadConfig",
    "UploadRequest",
    "Admission",
    "DataOutput",
    "RejectOutput",
    "Output",
    "Snapshot",
    "JobState",
]

MAX_PIECE_LENGTH = 4_194_304
MAX_PIECES = 4096
MAX_MANIFEST_FILE_BYTES = 1_048_576
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


class ManifestError(ValueError):
    """Raised for an invalid piece description, manifest, or manifest file."""


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass(frozen=True)
class PieceMeta:
    """Describes one piece. ``sha256`` is a content digest, not authentication."""

    index: int
    length: int
    sha256: str

    def __post_init__(self) -> None:
        if not _is_int(self.index) or self.index < 0:
            raise ManifestError("piece index must be a non-negative integer")
        if not _is_int(self.length) or not 1 <= self.length <= MAX_PIECE_LENGTH:
            raise ManifestError(
                f"piece {self.index}: length must be an integer from 1 to {MAX_PIECE_LENGTH}"
            )
        if (
            not isinstance(self.sha256, str)
            or len(self.sha256) != 64
            or not _HEX_DIGITS.issuperset(self.sha256)
        ):
            raise ManifestError(
                f"piece {self.index}: sha256 must be exactly 64 hexadecimal characters"
            )
        object.__setattr__(self, "sha256", self.sha256.lower())


@dataclass(frozen=True)
class Manifest:
    """Ordered, consecutive-from-zero collection of 1-4096 pieces."""

    pieces: tuple[PieceMeta, ...]

    def __post_init__(self) -> None:
        try:
            pieces = tuple(self.pieces)
        except TypeError as exc:
            raise ManifestError("manifest pieces must be iterable") from exc
        if not 1 <= len(pieces) <= MAX_PIECES:
            raise ManifestError(f"manifest must contain 1 to {MAX_PIECES} pieces")
        for item in pieces:
            if not isinstance(item, PieceMeta):
                raise ManifestError("manifest entries must be PieceMeta instances")
        indices = [p.index for p in pieces]
        if len(set(indices)) != len(indices):
            raise ManifestError("manifest contains duplicate piece indices")
        if set(indices) != set(range(len(pieces))):
            raise ManifestError("manifest piece indices must be consecutive from zero (missing index)")
        if indices != list(range(len(pieces))):
            raise ManifestError("manifest pieces must be listed in index order")
        object.__setattr__(self, "pieces", pieces)

    def __len__(self) -> int:
        return len(self.pieces)

    @property
    def max_length(self) -> int:
        return max(p.length for p in self.pieces)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def load_manifest(path: str | Path) -> Manifest:
    """Load a version-1 JSON manifest. Raises :class:`ManifestError` on any problem."""
    p = Path(path)
    try:
        if p.stat().st_size > MAX_MANIFEST_FILE_BYTES:
            raise ManifestError("manifest file is larger than 1 MiB")
        with open(p, "rb") as fh:
            raw = fh.read(MAX_MANIFEST_FILE_BYTES + 1)
    except OSError as exc:
        raise ManifestError(f"cannot read manifest file: {exc.strerror or exc}") from exc
    if len(raw) > MAX_MANIFEST_FILE_BYTES:
        raise ManifestError("manifest file is larger than 1 MiB")
    try:
        doc = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except ManifestError:
        raise
    except (ValueError, RecursionError) as exc:  # JSONDecodeError, UnicodeDecodeError
        raise ManifestError(f"malformed manifest JSON: {exc}") from exc

    if not isinstance(doc, dict):
        raise ManifestError("manifest must be a JSON object")
    unknown = set(doc) - {"version", "pieces"}
    if unknown:
        raise ManifestError(f"unknown manifest field(s): {sorted(unknown)}")
    if "version" not in doc or "pieces" not in doc:
        raise ManifestError("manifest requires 'version' and 'pieces'")
    if not _is_int(doc["version"]) or doc["version"] != 1:
        raise ManifestError("unsupported manifest version (expected integer 1)")
    entries = doc["pieces"]
    if not isinstance(entries, list):
        raise ManifestError("'pieces' must be a list")
    if not 1 <= len(entries) <= MAX_PIECES:
        raise ManifestError(f"manifest must contain 1 to {MAX_PIECES} pieces")

    metas = []
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ManifestError(f"pieces[{position}] must be an object")
        extra = set(entry) - {"index", "length", "sha256"}
        if extra:
            raise ManifestError(f"pieces[{position}] has unknown field(s): {sorted(extra)}")
        missing = {"index", "length", "sha256"} - set(entry)
        if missing:
            raise ManifestError(f"pieces[{position}] is missing field(s): {sorted(missing)}")
        if not _is_int(entry["index"]) or not _is_int(entry["length"]):
            raise ManifestError(f"pieces[{position}]: index and length must be integers")
        metas.append(PieceMeta(entry["index"], entry["length"], entry["sha256"]))
    return Manifest(tuple(metas))


def _positive_int(name: str, value: object) -> None:
    if not _is_int(value) or value <= 0:  # type: ignore[operator]
        raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True)
class UploadConfig:
    max_jobs: int = 40
    max_jobs_per_peer: int = 4
    max_output_records: int = 40
    max_output_bytes: int = 8_388_608
    max_read_bytes: int = 8_388_608
    max_piece_length: int = MAX_PIECE_LENGTH
    workers: int = 0

    def __post_init__(self) -> None:
        for name in (
            "max_jobs",
            "max_jobs_per_peer",
            "max_output_records",
            "max_output_bytes",
            "max_read_bytes",
            "max_piece_length",
        ):
            _positive_int(name, getattr(self, name))
        if self.max_jobs_per_peer > self.max_jobs:
            raise ValueError("max_jobs_per_peer cannot exceed max_jobs")
        if self.max_piece_length > MAX_PIECE_LENGTH:
            raise ValueError(f"max_piece_length cannot exceed {MAX_PIECE_LENGTH}")
        if not _is_int(self.workers) or self.workers not in (0, 2):
            raise ValueError("workers must be 0 or 2")


@dataclass(frozen=True)
class UploadRequest:
    peer_id: str
    piece: int


@dataclass(frozen=True)
class Admission:
    accepted: bool
    job_id: int | None
    reason: str | None


@dataclass(frozen=True)
class DataOutput:
    job_id: int
    peer_id: str
    piece: int
    data: bytes


@dataclass(frozen=True)
class RejectOutput:
    job_id: int
    peer_id: str
    reason: str


Output = Union[DataOutput, RejectOutput]


@dataclass(frozen=True)
class Snapshot:
    active_jobs: int
    queued_jobs: int
    reading_jobs: int
    output_slots: int
    reserved_output_bytes: int
    reserved_read_bytes: int
    sent_bytes: int
    sent_pieces: int
    failed_sends: int
    cancelled_jobs: int
    rejected_requests: int
    source_failures: int
    closed: bool


class JobState(enum.Enum):
    QUEUED = "queued"
    READING = "reading"
    READY = "ready"
    DELIVERED = "delivered"
