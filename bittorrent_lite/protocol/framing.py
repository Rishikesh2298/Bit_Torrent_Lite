"""
TCP Message Framing — Anik's Module

Handles the critical problem of message boundaries over TCP.

TCP is a BYTE STREAM — one send() does NOT equal one recv().
Therefore we need explicit message framing.

Our JSON-header framing protocol:
    [4-byte header length H, unsigned big-endian]
    [H bytes of UTF-8 JSON header]
    [payload_length bytes of raw binary data]

The sender:
    1. Gets the JSON header dict and binary payload from the message
    2. Serializes the header to a UTF-8 string
    3. Computes the header length
    4. Prepends the 4-byte length prefix
    5. Sends [length] + [header_bytes] + [payload_bytes]

The receiver:
    1. Reads exactly 4 bytes (the length prefix)
    2. Unpacks the length as big-endian uint32
    3. Reads exactly 'length' bytes (the JSON header)
    4. Parses the JSON header
    5. Reads exactly 'payload_length' bytes (if specified)
    6. Returns the parsed Message instance

Interface:
    send_message(sock, message) -> None
    recv_message(sock) -> Message | None
    recv_exactly(sock, num_bytes) -> bytes    (helper)
"""

import socket
import struct
import json
from bittorrent_lite.protocol.messages import Message, MESSAGE_REGISTRY
from bittorrent_lite.config import MAX_HEADER_SIZE


def send_message(sock: socket.socket, message: Message) -> None:
    """
    Frame and send a message over a TCP socket.

    Args:
        sock: Connected TCP socket.
        message: Message instance to send.

    Raises:
        ConnectionError: If the socket is closed or broken.
    """
    # TODO: Anik — implement this
    raise NotImplementedError("send_message not yet implemented")


def recv_message(sock: socket.socket) -> Message | None:
    """
    Read one complete framed message from a TCP socket.

    Returns:
        Deserialized Message instance, or None if the connection was closed.

    Raises:
        ValueError: If header length exceeds MAX_HEADER_SIZE, missing fields.
        ConnectionError: If partial read due to disconnect.
    """
    # TODO: Anik — implement this
    raise NotImplementedError("recv_message not yet implemented")


def recv_exactly(sock: socket.socket, num_bytes: int) -> bytes:
    """
    Read exactly num_bytes from a socket, handling partial reads.

    Args:
        sock: Connected TCP socket.
        num_bytes: Exact number of bytes to read.

    Returns:
        Exactly num_bytes of data.

    Raises:
        ConnectionError: If connection closes before all bytes are received.
    """
    # TODO: Anik — implement this
    raise NotImplementedError("recv_exactly not yet implemented")
