"""
BitTorrent-Lite protocol message definitions.

Wire format:
    [4-byte big-endian JSON-header length]
    [JSON header bytes]
    [optional raw payload bytes]

The module provides:
    - Handshake
    - BitfieldMsg
    - Have
    - Interested / NotInterested
    - Choke / Unchoke
    - Request
    - Piece
    - Cancel
    - Reject

The implementation intentionally supports the existing project tests and
the networking layer's JSON-header framing design.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Dict, Type
import json


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be a non-negative integer")
    if value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _require_string(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


# ---------------------------------------------------------------------------
# Base message
# ---------------------------------------------------------------------------

@dataclass(eq=False)
class Message:
    """
    Base protocol message.

    Equality is value-based rather than relying on dataclass-generated
    equality so that reconstructed messages compare correctly even when
    subclasses have different internal representations.
    """

    type: ClassVar[str] = "message"

    @property
    def payload(self) -> bytes:
        return b""

    def to_header(self) -> Dict[str, Any]:
        return {"type": self.type}

    @classmethod
    def from_header(
        cls,
        header: Dict[str, Any],
        payload: bytes = b"",
    ) -> "Message":
        return cls()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Message):
            return NotImplemented

        return (
            self.type == other.type
            and self.to_header() == other.to_header()
            and self.payload == other.payload
        )

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}"
            f"(header={self.to_header()!r}, payload={self.payload!r})"
        )


# ---------------------------------------------------------------------------
# Handshake
# ---------------------------------------------------------------------------

@dataclass(eq=False)
class Handshake(Message):
    """
    Initial peer handshake.

    `protocol_version` is intentionally allowed to be either an integer or
    string because the existing tests and older project code use both forms.
    """

    protocol_version: str | int
    file_id: str
    peer_id: str

    type: ClassVar[str] = "HANDSHAKE"

    def __post_init__(self) -> None:
        if not isinstance(self.protocol_version, (int, str)):
            raise ValueError("protocol_version must be an integer or string")

        if not isinstance(self.file_id, str):
            raise ValueError("file_id must be a string")

        if not isinstance(self.peer_id, str):
            raise ValueError("peer_id must be a string")

        # A peer ID is allowed to be any string, including a short test ID
        # such as "p". Do not impose a fixed length here.

    def to_header(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "protocol_version": self.protocol_version,
            "file_id": self.file_id,
            "peer_id": self.peer_id,
        }

    @classmethod
    def from_header(
        cls,
        header: Dict[str, Any],
        payload: bytes = b"",
    ) -> "Handshake":
        from bittorrent_lite.config import PROTOCOL_VERSION
        if payload:
            raise ValueError("handshake message must not contain a payload")
        pv = header.get("protocol_version")
        if isinstance(pv, bool) or pv != PROTOCOL_VERSION:
            raise ValueError(
                f"unsupported protocol_version {pv!r}; expected {PROTOCOL_VERSION!r}"
            )
        return cls(
            protocol_version=header["protocol_version"],
            file_id=header["file_id"],
            peer_id=header["peer_id"],
        )



# ---------------------------------------------------------------------------
# Bitfield
# ---------------------------------------------------------------------------

@dataclass(eq=False)
class BitfieldMsg(Message):
    pieces: list[int]

    type: ClassVar[str] = "BITFIELD"

    def __post_init__(self) -> None:
        if not isinstance(self.pieces, list):
            raise ValueError("pieces must be a list")

        for value in self.pieces:
            if value not in (0, 1, False, True):
                raise ValueError("bitfield values must be 0 or 1")

        self.pieces = [int(value) for value in self.pieces]

    def to_header(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "pieces": self.pieces,
        }

    @classmethod
    def from_header(
        cls,
        header: Dict[str, Any],
        payload: bytes = b"",
    ) -> "BitfieldMsg":
        return cls(list(header["pieces"]))


# ---------------------------------------------------------------------------
# HAVE
# ---------------------------------------------------------------------------

@dataclass(eq=False)
class Have(Message):
    piece_index: int

    type: ClassVar[str] = "HAVE"

    def __post_init__(self) -> None:
        self.piece_index = _require_non_negative_int(
            self.piece_index,
            "piece_index",
        )

    def to_header(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "piece_index": self.piece_index,
        }

    @classmethod
    def from_header(
        cls,
        header: Dict[str, Any],
        payload: bytes = b"",
    ) -> "Have":
        return cls(header["piece_index"])


# ---------------------------------------------------------------------------
# Stateless messages
# ---------------------------------------------------------------------------

@dataclass(eq=False)
class Interested(Message):
    type: ClassVar[str] = "INTERESTED"

    def to_header(self) -> Dict[str, Any]:
        return {"type": self.type}

    @classmethod
    def from_header(
        cls,
        header: Dict[str, Any],
        payload: bytes = b"",
    ) -> "Interested":
        return cls()


@dataclass(eq=False)
class NotInterested(Message):
    type: ClassVar[str] = "NOT_INTERESTED"

    def to_header(self) -> Dict[str, Any]:
        return {"type": self.type}

    @classmethod
    def from_header(
        cls,
        header: Dict[str, Any],
        payload: bytes = b"",
    ) -> "NotInterested":
        return cls()


@dataclass(eq=False)
class Choke(Message):
    type: ClassVar[str] = "CHOKE"

    def to_header(self) -> Dict[str, Any]:
        return {"type": self.type}

    @classmethod
    def from_header(
        cls,
        header: Dict[str, Any],
        payload: bytes = b"",
    ) -> "Choke":
        return cls()


@dataclass(eq=False)
class Unchoke(Message):
    type: ClassVar[str] = "UNCHOKE"

    def to_header(self) -> Dict[str, Any]:
        return {"type": self.type}

    @classmethod
    def from_header(
        cls,
        header: Dict[str, Any],
        payload: bytes = b"",
    ) -> "Unchoke":
        return cls()


# ---------------------------------------------------------------------------
# REQUEST
# ---------------------------------------------------------------------------

@dataclass(eq=False)
class Request(Message):
    request_id: int
    piece_index: int

    type: ClassVar[str] = "REQUEST"

    def __post_init__(self) -> None:
        self.request_id = _require_non_negative_int(
            self.request_id,
            "request_id",
        )
        self.piece_index = _require_non_negative_int(
            self.piece_index,
            "piece_index",
        )

    def to_header(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "request_id": self.request_id,
            "piece_index": self.piece_index,
        }

    @classmethod
    def from_header(
        cls,
        header: Dict[str, Any],
        payload: bytes = b"",
    ) -> "Request":
        return cls(
            request_id=header["request_id"],
            piece_index=header["piece_index"],
        )


# ---------------------------------------------------------------------------
# PIECE
# ---------------------------------------------------------------------------

@dataclass(eq=False, init=False)
class Piece(Message):
    request_id: int
    piece_index: int
    _payload: bytes

    type: ClassVar[str] = "PIECE"

    def __init__(
        self,
        request_id: int,
        piece_index: int,
        _payload: bytes = b"",
    ) -> None:
        self.request_id = _require_non_negative_int(
            request_id,
            "request_id",
        )
        self.piece_index = _require_non_negative_int(
            piece_index,
            "piece_index",
        )

        if not isinstance(_payload, (bytes, bytearray)):
            raise ValueError("payload must be bytes")

        self._payload = bytes(_payload)

    @property
    def payload(self) -> bytes:
        return self._payload

    def to_header(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "request_id": self.request_id,
            "piece_index": self.piece_index,
            "payload_length": len(self._payload),
        }

    @classmethod
    def from_header(
        cls,
        header: Dict[str, Any],
        payload: bytes = b"",
    ) -> "Piece":
        expected_length = header.get("payload_length")

        if expected_length is not None:
            expected_length = _require_non_negative_int(
                expected_length,
                "payload_length",
            )

            if expected_length != len(payload):
                raise ValueError(
                    "payload length does not match payload_length"
                )

        return cls(
            request_id=header["request_id"],
            piece_index=header["piece_index"],
            _payload=payload,
        )


# ---------------------------------------------------------------------------
# CANCEL
# ---------------------------------------------------------------------------

@dataclass(eq=False)
class Cancel(Message):
    request_id: int
    piece_index: int

    type: ClassVar[str] = "CANCEL"

    def __post_init__(self) -> None:
        self.request_id = _require_non_negative_int(
            self.request_id,
            "request_id",
        )
        self.piece_index = _require_non_negative_int(
            self.piece_index,
            "piece_index",
        )

    def to_header(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "request_id": self.request_id,
            "piece_index": self.piece_index,
        }

    @classmethod
    def from_header(
        cls,
        header: Dict[str, Any],
        payload: bytes = b"",
    ) -> "Cancel":
        return cls(
            request_id=header["request_id"],
            piece_index=header["piece_index"],
        )


# ---------------------------------------------------------------------------
# REJECT
# ---------------------------------------------------------------------------

@dataclass(eq=False)
class Reject(Message):
    request_id: int
    piece_index: int
    reason: str

    type: ClassVar[str] = "REJECT"

    def __post_init__(self) -> None:
        self.request_id = _require_non_negative_int(
            self.request_id,
            "request_id",
        )
        self.piece_index = _require_non_negative_int(
            self.piece_index,
            "piece_index",
        )

        self.reason = _require_string(
            self.reason,
            "reason",
        )

    def to_header(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "request_id": self.request_id,
            "piece_index": self.piece_index,
            "reason": self.reason,
        }

    @classmethod
    def from_header(
        cls,
        header: Dict[str, Any],
        payload: bytes = b"",
    ) -> "Reject":
        return cls(
            request_id=header["request_id"],
            piece_index=header["piece_index"],
            reason=header["reason"],
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

MESSAGE_REGISTRY: Dict[str, Type[Message]] = {
    Handshake.type: Handshake,
    BitfieldMsg.type: BitfieldMsg,
    Have.type: Have,
    Interested.type: Interested,
    NotInterested.type: NotInterested,
    Choke.type: Choke,
    Unchoke.type: Unchoke,
    Request.type: Request,
    Piece.type: Piece,
    Cancel.type: Cancel,
    Reject.type: Reject,
}


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def message_from_header(
    header: Dict[str, Any],
    payload: bytes = b"",
) -> Message:
    """
    Construct the correct Message subclass from a decoded header.
    """
    if not isinstance(header, dict):
        raise ValueError("header must be a dictionary")

    message_type = header.get("type")

    if message_type not in MESSAGE_REGISTRY:
        raise ValueError(f"unknown message type: {message_type!r}")

    return MESSAGE_REGISTRY[message_type].from_header(
        header,
        payload,
    )


def encode_header(message: Message) -> bytes:
    """
    Encode a message header as compact UTF-8 JSON.
    """
    return json.dumps(
        message.to_header(),
        separators=(",", ":"),
    ).encode("utf-8")


def decode_header(data: bytes) -> Dict[str, Any]:
    """
    Decode UTF-8 JSON header bytes.
    """
    try:
        header = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid message header") from exc

    if not isinstance(header, dict):
        raise ValueError("message header must be a JSON object")

    return header


__all__ = [
    "Message",
    "Handshake",
    "BitfieldMsg",
    "Have",
    "Interested",
    "NotInterested",
    "Choke",
    "Unchoke",
    "Request",
    "Piece",
    "Cancel",
    "Reject",
    "MESSAGE_REGISTRY",
    "message_from_header",
    "encode_header",
    "decode_header",
]