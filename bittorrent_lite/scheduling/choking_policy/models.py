"""Public, frozen data models for ``bittorrent_lite.scheduling.choking_policy``."""

from __future__ import annotations

import math
from dataclasses import dataclass


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _finite_float(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    try:
        result = float(value)
    except OverflowError:
        raise ValueError(f"{name} must be finite") from None
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


@dataclass(frozen=True)
class Config:
    """Validated policy configuration."""

    max_peers: int = 128
    max_slots: int = 2
    selection_interval: float = 5.0
    optimistic_interval: float = 15.0
    contribution_window: int = 5
    confirmation_timeout: float = 10.0
    diagnostic_capacity: int = 128
    random_seed: int = 0

    def __post_init__(self) -> None:
        setter = object.__setattr__
        if not _is_int(self.max_peers) or self.max_peers < 1:
            raise ValueError("max_peers must be a positive integer")
        if not _is_int(self.max_slots) or not 2 <= self.max_slots <= self.max_peers:
            raise ValueError("max_slots must be an integer from 2 through max_peers")
        selection = _finite_float("selection_interval", self.selection_interval)
        if selection <= 0:
            raise ValueError("selection_interval must be positive")
        optimistic = _finite_float("optimistic_interval", self.optimistic_interval)
        if optimistic < selection:
            raise ValueError("optimistic_interval must be at least selection_interval")
        window = self.contribution_window
        if not _is_int(window) or window < 1:
            raise ValueError("contribution_window must be a positive whole number of seconds")
        timeout = _finite_float("confirmation_timeout", self.confirmation_timeout)
        if timeout <= 0:
            raise ValueError("confirmation_timeout must be positive")
        if not _is_int(self.diagnostic_capacity) or self.diagnostic_capacity < 1:
            raise ValueError("diagnostic_capacity must be a positive integer")
        if not _is_int(self.random_seed):
            raise ValueError("random_seed must be an integer")
        setter(self, "selection_interval", selection)
        setter(self, "optimistic_interval", optimistic)
        setter(self, "contribution_window", window)
        setter(self, "confirmation_timeout", timeout)


@dataclass(frozen=True)
class PeerInfo:
    peer_id: str
    interested: bool = False


@dataclass(frozen=True)
class PermissionIntent:
    token: str
    peer_id: str
    allow: bool
    issued_at: float


@dataclass(frozen=True)
class Diagnostic:
    code: str
    peer_id: str | None
    at: float


@dataclass(frozen=True)
class PeerSnapshot:
    peer_id: str
    interested: bool
    desired: bool
    confirmed: bool
    reserved: bool
    recent_bytes: int
    allowed_seconds: float
    pending: PermissionIntent | None


@dataclass(frozen=True)
class Snapshot:
    now: float
    upload_enabled: bool
    seeder: bool
    closing: bool
    closed: bool
    peers: tuple[PeerSnapshot, ...]
    regular: tuple[str, ...]
    optimistic: str | None
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True)
class Decision:
    intents: tuple[PermissionIntent, ...]
    state: Snapshot
