from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class ConnectionReady:
    connection_id: int
    peer_id: str


@dataclass(frozen=True)
class BitfieldReceived:
    connection_id: int
    bitfield: Sequence[bool]


@dataclass(frozen=True)
class HaveReceived:
    connection_id: int
    piece_index: int


@dataclass(frozen=True)
class ChokeReceived:
    connection_id: int


@dataclass(frozen=True)
class UnchokeReceived:
    connection_id: int


@dataclass(frozen=True)
class PeerInterestChanged:
    connection_id: int
    interested: bool


@dataclass(frozen=True)
class RequestSent:
    connection_id: int
    request_id: int
    piece_index: int
    sent_at: float


@dataclass(frozen=True)
class RequestSendFailed:
    connection_id: int
    request_id: int
    piece_index: int
    reason: str = ""


@dataclass(frozen=True)
class PieceReceived:
    connection_id: int
    request_id: int
    piece_index: int
    data: bytes


@dataclass(frozen=True)
class RejectReceived:
    connection_id: int
    request_id: int
    piece_index: int


@dataclass(frozen=True)
class Disconnected:
    connection_id: int


# returned by Coordinator.tick()
@dataclass(frozen=True)
class ExpiredRequest:
    connection_id: int
    request_id: int
    piece_index: int
    kind: str  # "response_timeout" or "send_unconfirmed"
