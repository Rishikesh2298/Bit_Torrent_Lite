from dataclasses import dataclass, field
from bittorrent_lite.common.types import PieceState
from bittorrent_lite.common.config import REQUEST_TIMEOUT
from bittorrent_lite.common.config import QUEUE_SEND_TIMEOUT
from bittorrent_lite.common.config import MAX_OUTSTANDING_REQUESTS
from bittorrent_lite.common.config import MAX_CONNECTIONS
from bittorrent_lite.scheduling.request_pipeline import PipelineConfig
from bittorrent_lite.scheduling.recovery import RecoveryConfig
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
    recovery: RecoveryConfig = field(default_factory=lambda: RecoveryConfig(
        endgame_enabled=False, max_copies=1))
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
