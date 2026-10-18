"""Immutable, validated configuration and shared validation helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import Any, Dict, Optional

STRATEGIES = ("rarest-first", "sequential", "random")


def is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def is_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def check_int(name: str, value: Any, lo: Optional[int] = None,
              hi: Optional[int] = None) -> int:
    if not is_int(value):
        raise ValueError(f"{name} must be an integer (booleans are not accepted)")
    if lo is not None and value < lo:
        raise ValueError(f"{name} must be >= {lo}")
    if hi is not None and value > hi:
        raise ValueError(f"{name} must be <= {hi}")
    return value


def check_bool(name: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def check_positive_seconds(name: str, value: Any) -> None:
    if not is_finite_number(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number of seconds")


@dataclass(frozen=True)
class RecoveryConfig:
    strategy: str = "rarest-first"
    retry_delays: tuple = (2.0, 4.0, 10.0)
    local_send_cooldown: float = 1.0
    endgame_enabled: bool = True
    endgame_remaining: int = 4
    endgame_min_age: float = 5.0
    max_copies: int = 2
    max_penalty_providers: int = 256
    max_penalty_entries: int = 4096
    recent_event_limit: int = 256

    def __post_init__(self) -> None:
        if not isinstance(self.strategy, str) or self.strategy not in STRATEGIES:
            raise ValueError(f"strategy must be one of {', '.join(STRATEGIES)}")
        delays = self.retry_delays
        if not isinstance(delays, tuple) or not delays:
            raise ValueError("retry_delays must be a nonempty tuple")
        for d in delays:
            check_positive_seconds("retry_delays entries", d)
        if any(b < a for a, b in zip(delays, delays[1:])):
            raise ValueError("retry_delays must be nondecreasing")
        check_positive_seconds("local_send_cooldown", self.local_send_cooldown)
        check_bool("endgame_enabled", self.endgame_enabled)
        check_int("endgame_remaining", self.endgame_remaining, lo=1)
        check_positive_seconds("endgame_min_age", self.endgame_min_age)
        check_int("max_copies", self.max_copies, lo=1, hi=2)
        check_int("max_penalty_providers", self.max_penalty_providers, lo=1)
        check_int("max_penalty_entries", self.max_penalty_entries, lo=1)
        check_int("recent_event_limit", self.recent_event_limit, lo=0)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            out[f.name] = list(value) if isinstance(value, tuple) else value
        return out
