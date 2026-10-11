from dataclasses import dataclass
import math
from bittorrent_lite.types import PieceState
from bittorrent_lite.config import REQUEST_TIMEOUT, QUEUE_SEND_TIMEOUT
from typing import Optional


@dataclass
class NeighborState:
    connection_id: int
    peer_id: str
    active: bool = True
    bitfield: Optional[list[bool]] = None
    am_interested: bool = False
    peer_interested: bool = False
    am_choking: bool = True
    peer_choking: bool = True


@dataclass
class PendingRequest:
    request_id: int
    connection_id: int
    piece_index: int
    queued_at: float
    sent_at: Optional[float] = None
    deadline: Optional[float] = None
    verifying: bool = False


@dataclass(frozen=True)
class SchedulerConfig:
    request_window: int = 1
    response_timeout: float = REQUEST_TIMEOUT
    send_confirm_timeout: float = QUEUE_SEND_TIMEOUT

    def __post_init__(self):
        if type(self.request_window) is not int or self.request_window < 1:
            raise ValueError("request_window must be a positive integer")
        for value in (self.response_timeout, self.send_confirm_timeout):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError("timeouts must be positive finite numbers")
