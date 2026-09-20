"""
Protocol Messages — Anik's Module

Defines all message types for the BitTorrent-Lite peer wire protocol.

Each message is represented as a dataclass.
The framing layer handles prepending the 4-byte total length prefix.
This module defines the JSON header structure and optional binary payload.

Message formats:
All messages have a JSON header with at least a "type" string.
Some messages also carry a binary payload.

Types:
    "HANDSHAKE", "CHOKE", "UNCHOKE", "INTERESTED", "NOT_INTERESTED",
    "HAVE", "BITFIELD", "REQUEST", "PIECE", "CANCEL", "REJECT"
"""

from dataclasses import dataclass
from typing import Any

# Registry for deserialization dispatch
MESSAGE_REGISTRY: dict[str, type] = {}


def register_message(cls):
    """Decorator to register a message class by its type name."""
    MESSAGE_REGISTRY[cls.type] = cls
    return cls


class Message:
    """Base class for all protocol messages."""
    type: str = ""

    def to_header(self) -> dict[str, Any]:
        """Return the dictionary to be serialized as the JSON header."""
        raise NotImplementedError

    @property
    def payload(self) -> bytes:
        """Return the binary payload for this message (empty by default)."""
        return b""

    @classmethod
    def from_header(cls, header: dict[str, Any], payload: bytes) -> 'Message':
        """Construct a message instance from its parsed JSON header and binary payload."""
        raise NotImplementedError


@register_message
@dataclass
class Handshake(Message):
    type = "HANDSHAKE"
    protocol_version: int
    file_id: str
    peer_id: str

    def to_header(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "protocol_version": self.protocol_version,
            "file_id": self.file_id,
            "peer_id": self.peer_id
        }

    @classmethod
    def from_header(cls, header: dict[str, Any], payload: bytes) -> 'Handshake':
        return cls(
            protocol_version=header["protocol_version"],
            file_id=header["file_id"],
            peer_id=header["peer_id"]
        )


@register_message
@dataclass
class BitfieldMsg(Message):
    type = "BITFIELD"
    pieces: list[int]  # List of 0/1 integers

    def to_header(self) -> dict[str, Any]:
        return {"type": self.type, "pieces": self.pieces}

    @classmethod
    def from_header(cls, header: dict[str, Any], payload: bytes) -> 'BitfieldMsg':
        return cls(pieces=header["pieces"])


@register_message
@dataclass
class Have(Message):
    type = "HAVE"
    piece_index: int

    def to_header(self) -> dict[str, Any]:
        return {"type": self.type, "piece_index": self.piece_index}

    @classmethod
    def from_header(cls, header: dict[str, Any], payload: bytes) -> 'Have':
        return cls(piece_index=header["piece_index"])


@register_message
@dataclass
class Interested(Message):
    type = "INTERESTED"

    def to_header(self) -> dict[str, Any]:
        return {"type": self.type}

    @classmethod
    def from_header(cls, header: dict[str, Any], payload: bytes) -> 'Interested':
        return cls()


@register_message
@dataclass
class NotInterested(Message):
    type = "NOT_INTERESTED"

    def to_header(self) -> dict[str, Any]:
        return {"type": self.type}

    @classmethod
    def from_header(cls, header: dict[str, Any], payload: bytes) -> 'NotInterested':
        return cls()


@register_message
@dataclass
class Choke(Message):
    type = "CHOKE"

    def to_header(self) -> dict[str, Any]:
        return {"type": self.type}

    @classmethod
    def from_header(cls, header: dict[str, Any], payload: bytes) -> 'Choke':
        return cls()


@register_message
@dataclass
class Unchoke(Message):
    type = "UNCHOKE"

    def to_header(self) -> dict[str, Any]:
        return {"type": self.type}

    @classmethod
    def from_header(cls, header: dict[str, Any], payload: bytes) -> 'Unchoke':
        return cls()


@register_message
@dataclass
class Request(Message):
    type = "REQUEST"
    request_id: int
    piece_index: int

    def to_header(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "request_id": self.request_id,
            "piece_index": self.piece_index
        }

    @classmethod
    def from_header(cls, header: dict[str, Any], payload: bytes) -> 'Request':
        return cls(
            request_id=header["request_id"],
            piece_index=header["piece_index"]
        )


@register_message
@dataclass
class Piece(Message):
    type = "PIECE"
    request_id: int
    piece_index: int
    _payload: bytes

    def to_header(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "request_id": self.request_id,
            "piece_index": self.piece_index,
            "payload_length": len(self._payload)
        }

    @property
    def payload(self) -> bytes:
        return self._payload

    @classmethod
    def from_header(cls, header: dict[str, Any], payload: bytes) -> 'Piece':
        return cls(
            request_id=header["request_id"],
            piece_index=header["piece_index"],
            _payload=payload
        )


@register_message
@dataclass
class Cancel(Message):
    type = "CANCEL"
    request_id: int
    piece_index: int

    def to_header(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "request_id": self.request_id,
            "piece_index": self.piece_index
        }

    @classmethod
    def from_header(cls, header: dict[str, Any], payload: bytes) -> 'Cancel':
        return cls(
            request_id=header["request_id"],
            piece_index=header["piece_index"]
        )


@register_message
@dataclass
class Reject(Message):
    type = "REJECT"
    request_id: int
    piece_index: int
    reason: str

    def to_header(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "request_id": self.request_id,
            "piece_index": self.piece_index,
            "reason": self.reason
        }

    @classmethod
    def from_header(cls, header: dict[str, Any], payload: bytes) -> 'Reject':
        return cls(
            request_id=header["request_id"],
            piece_index=header["piece_index"],
            reason=header["reason"]
        )
