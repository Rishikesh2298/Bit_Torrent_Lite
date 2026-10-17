"""Data types for the request pipeline."""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional

OUTCOME_KINDS = ("completed", "invalid", "expired", "canceled")


def is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_time(v) -> bool:
    return is_number(v) and math.isfinite(v) and v >= 0


class PieceState(Enum):
    MISSING = "MISSING"
    REQUESTED = "REQUESTED"
    VERIFYING = "VERIFYING"
    HAVE = "HAVE"


@dataclass(frozen=True)
class RequestKey:
    connection_id: int
    request_id: int
    piece_index: int

    def __post_init__(self):
        for name in ("connection_id", "request_id", "piece_index"):
            if not is_int(getattr(self, name)):
                raise ValueError(f"{name} must be an integer")

    def to_dict(self) -> dict:
        return {"connection_id": self.connection_id,
                "request_id": self.request_id,
                "piece_index": self.piece_index}


@dataclass(frozen=True)
class RequestView:
    key: RequestKey
    provider_id: str
    queued_at: float
    sent_at: Optional[float]
    deadline: Optional[float]
    verifying: bool

    def to_dict(self) -> dict:
        d = self.key.to_dict()
        d.update(provider_id=self.provider_id, queued_at=self.queued_at,
                 sent_at=self.sent_at, deadline=self.deadline,
                 verifying=self.verifying)
        return d


@dataclass(frozen=True)
class Outcome:
    kind: str
    key: RequestKey
    reason: str
    at: float

    def __post_init__(self):
        if self.kind not in OUTCOME_KINDS:
            raise ValueError(f"unknown outcome kind {self.kind!r}")

    def to_dict(self) -> dict:
        d = self.key.to_dict()
        d.update(kind=self.kind, reason=self.reason, at=self.at)
        return d


@dataclass(frozen=True)
class PipelineConfig:
    window: int = 4
    response_timeout: float = 10.0
    send_confirm_timeout: float = 5.0
    max_connections: int = 10
    max_copies: int = 2

    def __post_init__(self):
        if not is_int(self.window) or not 1 <= self.window <= 4:
            raise ValueError("window must be an integer from 1 to 4")
        if not is_int(self.max_copies) or not 1 <= self.max_copies <= 2:
            raise ValueError("max_copies must be an integer from 1 to 2")
        if not is_int(self.max_connections) or self.max_connections < 1:
            raise ValueError("max_connections must be a positive integer")
        for name in ("response_timeout", "send_confirm_timeout"):
            v = getattr(self, name)
            if not is_number(v) or not math.isfinite(v) or v <= 0:
                raise ValueError(f"{name} must be a positive finite number")
