from dataclasses import dataclass, field
from bittorrent_lite.types import PieceState
from bittorrent_lite.config import REQUEST_TIMEOUT, QUEUE_SEND_TIMEOUT
from bittorrent_lite.config import MAX_OUTSTANDING_REQUESTS, MAX_CONNECTIONS
from request_pipeline import PipelineConfig
from recovery_policy import RecoveryConfig
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
    request_window: int = MAX_OUTSTANDING_REQUESTS
    response_timeout: float = REQUEST_TIMEOUT
    send_confirm_timeout: float = QUEUE_SEND_TIMEOUT
    max_connections: int = MAX_CONNECTIONS
    recovery: RecoveryConfig = field(default_factory=RecoveryConfig)
    recovery_seed: int = 0

    def __post_init__(self):
        if not isinstance(self.recovery, RecoveryConfig):
            raise ValueError("recovery must be a RecoveryConfig")
        if type(self.recovery_seed) is not int:
            raise ValueError("recovery_seed must be an integer")
        self.pipeline_config()

    def pipeline_config(self):
        return PipelineConfig(window=self.request_window,
                              response_timeout=self.response_timeout,
                              send_confirm_timeout=self.send_confirm_timeout,
                              max_connections=self.max_connections,
                              max_copies=self.recovery.max_copies)
