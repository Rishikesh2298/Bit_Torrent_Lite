"""
BitTorrent-Lite Protocol Messages

This module defines all protocol-level messages.

Wire format is handled by framing.py:

    [4-byte header length]
    [JSON header]
    [binary payload]

Each message provides:

    to_header()
        Convert message into a JSON-compatible header.

    payload
        Binary payload, if any.

    from_header()
        Reconstruct a message from a received header and payload.
"""

from dataclasses import dataclass
from typing import Any


# ============================================================
# Message Registry
# ============================================================

MESSAGE_REGISTRY: dict[str, type] = {}


def register_message(cls):
    """
    Register a Message class by its protocol type.

    Example:

        @register_message
        class Interested(Message):
            type = "INTERESTED"
    """

    if not getattr(cls, "type", None):
        raise ValueError(
            f"{cls.__name__} must define a non-empty 'type'"
        )

    if cls.type in MESSAGE_REGISTRY:
        raise ValueError(
            f"Duplicate message type: {cls.type}"
        )

    MESSAGE_REGISTRY[cls.type] = cls

    return cls


# ============================================================
# Base Message
# ============================================================

class Message:
    """
    Base class for all BitTorrent-Lite protocol messages.
    """

    type: str = ""

    def to_header(self) -> dict[str, Any]:
        """
        Convert this message to its JSON header.
        """

        return {
            "type": self.type,
        }

    @property
    def payload(self) -> bytes:
        """
        Return binary payload.

        Most messages have no payload.
        """

        return b""

    @classmethod
    def from_header(
        cls,
        header: dict[str, Any],
        payload: bytes
    ) -> "Message":
        """
        Construct a message from a decoded header.

        Base implementation is only suitable for messages
        without additional fields.
        """

        return cls()


# ============================================================
# Validation Helpers
# ============================================================

def _require_string(
    header: dict[str, Any],
    field: str
) -> str:
    """
    Require a non-empty string field.
    """

    value = header.get(field)

    if not isinstance(value, str):
        raise ValueError(
            f"'{field}' must be a string"
        )

    if not value:
        raise ValueError(
            f"'{field}' cannot be empty"
        )

    return value


def _require_non_negative_int(
    header: dict[str, Any],
    field: str
) -> int:
    """
    Require a non-negative integer.

    bool is explicitly rejected because bool is a subclass
    of int in Python.
    """

    value = header.get(field)

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"'{field}' must be an integer"
        )

    if value < 0:
        raise ValueError(
            f"'{field}' cannot be negative"
        )

    return value


def _require_positive_int(
    header: dict[str, Any],
    field: str
) -> int:
    """
    Require a positive integer.
    """

    value = _require_non_negative_int(
        header,
        field
    )

    if value == 0:
        raise ValueError(
            f"'{field}' must be greater than zero"
        )

    return value


def _validate_no_payload(payload: bytes) -> None:
    """
    Messages such as HAVE and INTERESTED must not carry
    a binary payload.
    """

    if payload:
        raise ValueError(
            "message must not contain a binary payload"
        )


# ============================================================
# HANDSHAKE
# ============================================================

@register_message
@dataclass
class Handshake(Message):

    type = "HANDSHAKE"

    protocol_version: str
    file_id: str
    peer_id: str

    def to_header(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "protocol_version": self.protocol_version,
            "file_id": self.file_id,
            "peer_id": self.peer_id,
        }

    @classmethod
    def from_header(
        cls,
        header: dict[str, Any],
        payload: bytes
    ) -> "Handshake":

        _validate_no_payload(payload)

        protocol_version = _require_string(
            header,
            "protocol_version"
        )

        file_id = _require_string(
            header,
            "file_id"
        )

        peer_id = _require_string(
            header,
            "peer_id"
        )

        return cls(
            protocol_version=protocol_version,
            file_id=file_id,
            peer_id=peer_id,
        )


# ============================================================
# BITFIELD
# ============================================================

@register_message
@dataclass
class BitfieldMsg(Message):

    type = "BITFIELD"

    pieces: list[int]

    def __post_init__(self):
        if not isinstance(self.pieces, list):
            raise ValueError(
                "pieces must be a list"
            )

        for piece in self.pieces:
            if piece not in (0, 1):
                raise ValueError(
                    "bitfield values must be 0 or 1"
                )

    def to_header(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "pieces": self.pieces,
        }

    @classmethod
    def from_header(
        cls,
        header: dict[str, Any],
        payload: bytes
    ) -> "BitfieldMsg":

        _validate_no_payload(payload)

        pieces = header.get("pieces")

        if not isinstance(pieces, list):
            raise ValueError(
                "'pieces' must be a list"
            )

        validated_pieces = []

        for piece in pieces:

            if isinstance(piece, bool) or piece not in (0, 1):
                raise ValueError(
                    "bitfield values must be 0 or 1"
                )

            validated_pieces.append(int(piece))

        return cls(
            pieces=validated_pieces
        )


# ============================================================
# HAVE
# ============================================================

@register_message
@dataclass
class Have(Message):

    type = "HAVE"

    piece_index: int

    def __post_init__(self):
        if (
            isinstance(self.piece_index, bool)
            or not isinstance(self.piece_index, int)
            or self.piece_index < 0
        ):
            raise ValueError(
                "piece_index must be a non-negative integer"
            )

    def to_header(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "piece_index": self.piece_index,
        }

    @classmethod
    def from_header(
        cls,
        header: dict[str, Any],
        payload: bytes
    ) -> "Have":

        _validate_no_payload(payload)

        piece_index = _require_non_negative_int(
            header,
            "piece_index"
        )

        return cls(
            piece_index=piece_index
        )


# ============================================================
# INTERESTED
# ============================================================

@register_message
class Interested(Message):

    type = "INTERESTED"

    @classmethod
    def from_header(
        cls,
        header: dict[str, Any],
        payload: bytes
    ) -> "Interested":

        _validate_no_payload(payload)

        return cls()


# ============================================================
# NOT_INTERESTED
# ============================================================

@register_message
class NotInterested(Message):

    type = "NOT_INTERESTED"

    @classmethod
    def from_header(
        cls,
        header: dict[str, Any],
        payload: bytes
    ) -> "NotInterested":

        _validate_no_payload(payload)

        return cls()


# ============================================================
# CHOKE
# ============================================================

@register_message
class Choke(Message):

    type = "CHOKE"

    @classmethod
    def from_header(
        cls,
        header: dict[str, Any],
        payload: bytes
    ) -> "Choke":

        _validate_no_payload(payload)

        return cls()


# ============================================================
# UNCHOKE
# ============================================================

@register_message
class Unchoke(Message):

    type = "UNCHOKE"

    @classmethod
    def from_header(
        cls,
        header: dict[str, Any],
        payload: bytes
    ) -> "Unchoke":

        _validate_no_payload(payload)

        return cls()


# ============================================================
# REQUEST
# ============================================================

@register_message
@dataclass
class Request(Message):

    type = "REQUEST"

    request_id: int
    piece_index: int

    def __post_init__(self):

        if (
            isinstance(self.request_id, bool)
            or not isinstance(self.request_id, int)
            or self.request_id < 0
        ):
            raise ValueError(
                "request_id must be a non-negative integer"
            )

        if (
            isinstance(self.piece_index, bool)
            or not isinstance(self.piece_index, int)
            or self.piece_index < 0
        ):
            raise ValueError(
                "piece_index must be a non-negative integer"
            )

    def to_header(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "request_id": self.request_id,
            "piece_index": self.piece_index,
        }

    @classmethod
    def from_header(
        cls,
        header: dict[str, Any],
        payload: bytes
    ) -> "Request":

        _validate_no_payload(payload)

        request_id = _require_non_negative_int(
            header,
            "request_id"
        )

        piece_index = _require_non_negative_int(
            header,
            "piece_index"
        )

        return cls(
            request_id=request_id,
            piece_index=piece_index,
        )


# ============================================================
# PIECE
# ============================================================

@register_message
@dataclass
class Piece(Message):

    type = "PIECE"

    request_id: int
    piece_index: int
    _payload: bytes

    def __post_init__(self):

        if (
            isinstance(self.request_id, bool)
            or not isinstance(self.request_id, int)
            or self.request_id < 0
        ):
            raise ValueError(
                "request_id must be a non-negative integer"
            )

        if (
            isinstance(self.piece_index, bool)
            or not isinstance(self.piece_index, int)
            or self.piece_index < 0
        ):
            raise ValueError(
                "piece_index must be a non-negative integer"
            )

        if not isinstance(self._payload, bytes):
            raise TypeError(
                "_payload must be bytes"
            )

    def to_header(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "request_id": self.request_id,
            "piece_index": self.piece_index,
            "payload_length": len(self._payload),
        }

    @property
    def payload(self) -> bytes:
        return self._payload

    @classmethod
    def from_header(
        cls,
        header: dict[str, Any],
        payload: bytes
    ) -> "Piece":

        request_id = _require_non_negative_int(
            header,
            "request_id"
        )

        piece_index = _require_non_negative_int(
            header,
            "piece_index"
        )

        declared_length = _require_non_negative_int(
            header,
            "payload_length"
        )

        if declared_length != len(payload):
            raise ValueError(
                f"PIECE payload length mismatch: "
                f"header={declared_length}, "
                f"received={len(payload)}"
            )

        return cls(
            request_id=request_id,
            piece_index=piece_index,
            _payload=payload,
        )


# ============================================================
# CANCEL
# ============================================================

@register_message
@dataclass
class Cancel(Message):

    type = "CANCEL"

    request_id: int
    piece_index: int

    def __post_init__(self):

        if (
            isinstance(self.request_id, bool)
            or not isinstance(self.request_id, int)
            or self.request_id < 0
        ):
            raise ValueError(
                "request_id must be a non-negative integer"
            )

        if (
            isinstance(self.piece_index, bool)
            or not isinstance(self.piece_index, int)
            or self.piece_index < 0
        ):
            raise ValueError(
                "piece_index must be a non-negative integer"
            )

    def to_header(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "request_id": self.request_id,
            "piece_index": self.piece_index,
        }

    @classmethod
    def from_header(
        cls,
        header: dict[str, Any],
        payload: bytes
    ) -> "Cancel":

        _validate_no_payload(payload)

        request_id = _require_non_negative_int(
            header,
            "request_id"
        )

        piece_index = _require_non_negative_int(
            header,
            "piece_index"
        )

        return cls(
            request_id=request_id,
            piece_index=piece_index,
        )


# ============================================================
# REJECT
# ============================================================

@register_message
@dataclass
class Reject(Message):

    type = "REJECT"

    request_id: int
    piece_index: int
    reason: str

    def __post_init__(self):

        if (
            isinstance(self.request_id, bool)
            or not isinstance(self.request_id, int)
            or self.request_id < 0
        ):
            raise ValueError(
                "request_id must be a non-negative integer"
            )

        if (
            isinstance(self.piece_index, bool)
            or not isinstance(self.piece_index, int)
            or self.piece_index < 0
        ):
            raise ValueError(
                "piece_index must be a non-negative integer"
            )

        if not isinstance(self.reason, str):
            raise ValueError(
                "reason must be a string"
            )

        if not self.reason:
            raise ValueError(
                "reason cannot be empty"
            )

    def to_header(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "request_id": self.request_id,
            "piece_index": self.piece_index,
            "reason": self.reason,
        }

    @classmethod
    def from_header(
        cls,
        header: dict[str, Any],
        payload: bytes
    ) -> "Reject":

        _validate_no_payload(payload)

        request_id = _require_non_negative_int(
            header,
            "request_id"
        )

        piece_index = _require_non_negative_int(
            header,
            "piece_index"
        )

        reason = _require_string(
            header,
            "reason"
        )

        return cls(
            request_id=request_id,
            piece_index=piece_index,
            reason=reason,
        )