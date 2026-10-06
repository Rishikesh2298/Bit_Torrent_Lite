"""
TCP Message Framing — Anik's Module

Handles message boundaries over TCP.

TCP is a BYTE STREAM:
one send() does NOT necessarily equal one recv().

Our framing format:

    [4-byte header length, unsigned big-endian]
    [JSON header bytes]
    [payload bytes]

The JSON header must contain:
    - "type"
    - "payload_length"

Only the PIECE message currently carries a non-empty
binary payload.
"""

import json
import socket
import struct

from bittorrent_lite.protocol.messages import Message, MESSAGE_REGISTRY
from bittorrent_lite.config import MAX_HEADER_SIZE


# Maximum payload we are willing to receive.
#
# This should be consistent with the project's maximum piece size.
# If your config.py already defines MAX_PAYLOAD_SIZE, import that
# instead of using this fallback.
MAX_PAYLOAD_SIZE = 64 * 1024


def send_message(sock: socket.socket, message: Message) -> None:
    """
    Serialize, frame, and send one Message over a TCP socket.

    Frame format:

        [4-byte header length]
        [JSON header]
        [binary payload]

    Args:
        sock:
            Connected TCP socket.

        message:
            Message instance to send.

    Raises:
        ConnectionError:
            If the socket connection fails.
        ValueError:
            If the message/header is invalid or too large.
    """

    if not isinstance(message, Message):
        raise TypeError("message must be a Message instance")

    # ---------------------------------------------------------
    # 1. Obtain the JSON header from the Message object
    # ---------------------------------------------------------
    header = message.to_header()

    if not isinstance(header, dict):
        raise ValueError("message.to_header() must return a dictionary")

    if "type" not in header:
        raise ValueError("message header must contain 'type'")

    # ---------------------------------------------------------
    # 2. Obtain binary payload
    # ---------------------------------------------------------
    payload = message.payload

    if payload is None:
        payload = b""

    if not isinstance(payload, bytes):
        raise TypeError("message.payload must be bytes")

    # ---------------------------------------------------------
    # 3. Add/validate payload_length
    # ---------------------------------------------------------
    actual_payload_length = len(payload)

    declared_payload_length = header.get(
        "payload_length",
        actual_payload_length
    )

    if declared_payload_length != actual_payload_length:
        raise ValueError(
            f"payload_length mismatch: "
            f"header says {declared_payload_length}, "
            f"actual payload is {actual_payload_length}"
        )

    header["payload_length"] = actual_payload_length

    if actual_payload_length > MAX_PAYLOAD_SIZE:
        raise ValueError(
            f"payload too large: {actual_payload_length} bytes "
            f"(maximum {MAX_PAYLOAD_SIZE})"
        )

    # ---------------------------------------------------------
    # 4. Serialize JSON header
    # ---------------------------------------------------------
    try:
        header_bytes = json.dumps(
            header,
            separators=(",", ":"),
            ensure_ascii=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("header cannot be serialized as JSON") from exc

    # ---------------------------------------------------------
    # 5. Validate header size
    # ---------------------------------------------------------
    if len(header_bytes) > MAX_HEADER_SIZE:
        raise ValueError(
            f"header too large: {len(header_bytes)} bytes "
            f"(maximum {MAX_HEADER_SIZE})"
        )

    # ---------------------------------------------------------
    # 6. Pack header length as unsigned big-endian uint32
    # ---------------------------------------------------------
    try:
        length_prefix = struct.pack(
            "!I",
            len(header_bytes)
        )
    except struct.error as exc:
        raise ValueError("header length cannot be encoded") from exc

    # ---------------------------------------------------------
    # 7. Send complete frame
    # ---------------------------------------------------------
    frame = length_prefix + header_bytes + payload

    try:
        sock.sendall(frame)
    except (BrokenPipeError, ConnectionResetError, OSError) as exc:
        raise ConnectionError(
            "failed to send message over TCP connection"
        ) from exc


def recv_message(sock: socket.socket) -> Message | None:
    """
    Read exactly one complete framed message.

    Returns:
        Message:
            Successfully decoded message.

        None:
            The peer closed the connection cleanly before
            starting another message.

    Raises:
        ValueError:
            Invalid header length, malformed JSON, missing fields,
            invalid payload length, or unknown message type.

        ConnectionError:
            Connection closed in the middle of a frame.
    """

    # ---------------------------------------------------------
    # 1. Read the 4-byte header-length prefix
    # ---------------------------------------------------------
    prefix = recv_exactly(
        sock,
        4,
        allow_clean_close=True
    )

    if prefix is None:
        # No bytes received means clean TCP shutdown.
        return None

    # ---------------------------------------------------------
    # 2. Decode unsigned big-endian uint32
    # ---------------------------------------------------------
    try:
        header_length = struct.unpack("!I", prefix)[0]
    except struct.error as exc:
        raise ValueError("invalid header length prefix") from exc

    # ---------------------------------------------------------
    # 3. Validate header length
    # ---------------------------------------------------------
    if header_length == 0:
        raise ValueError("header length cannot be zero")

    if header_length > MAX_HEADER_SIZE:
        raise ValueError(
            f"header length {header_length} exceeds "
            f"maximum {MAX_HEADER_SIZE}"
        )

    # ---------------------------------------------------------
    # 4. Read the complete JSON header
    # ---------------------------------------------------------
    header_bytes = recv_exactly(
        sock,
        header_length
    )

    # ---------------------------------------------------------
    # 5. Decode UTF-8
    # ---------------------------------------------------------
    try:
        header_text = header_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("header is not valid UTF-8") from exc

    # ---------------------------------------------------------
    # 6. Parse JSON
    # ---------------------------------------------------------
    try:
        header = json.loads(header_text)
    except json.JSONDecodeError as exc:
        raise ValueError("header contains invalid JSON") from exc

    if not isinstance(header, dict):
        raise ValueError("JSON header must be an object")

    # ---------------------------------------------------------
    # 7. Validate required fields
    # ---------------------------------------------------------
    if "type" not in header:
        raise ValueError("header missing required field: type")

    if "payload_length" not in header:
        raise ValueError(
            "header missing required field: payload_length"
        )

    message_type = header["type"]

    if not isinstance(message_type, str):
        raise ValueError("message type must be a string")

    payload_length = header["payload_length"]

    if (
        isinstance(payload_length, bool)
        or not isinstance(payload_length, int)
        or payload_length < 0
    ):
        raise ValueError(
            "payload_length must be a non-negative integer"
        )

    if payload_length > MAX_PAYLOAD_SIZE:
        raise ValueError(
            f"payload length {payload_length} exceeds "
            f"maximum {MAX_PAYLOAD_SIZE}"
        )

    # ---------------------------------------------------------
    # 8. Check that message type is known
    # ---------------------------------------------------------
    message_class = MESSAGE_REGISTRY.get(message_type)

    if message_class is None:
        raise ValueError(
            f"unknown message type: {message_type}"
        )

    # ---------------------------------------------------------
    # 9. Read binary payload
    # ---------------------------------------------------------
    if payload_length == 0:
        payload = b""
    else:
        payload = recv_exactly(
            sock,
            payload_length
        )

    # ---------------------------------------------------------
    # 10. Construct Message object
    # ---------------------------------------------------------
    try:
        message = message_class.from_header(
            header,
            payload
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"invalid {message_type} message fields"
        ) from exc

    return message


def recv_exactly(
    sock: socket.socket,
    num_bytes: int,
    allow_clean_close: bool = False
) -> bytes | None:
    """
    Read exactly num_bytes from a TCP socket.

    TCP may return fewer bytes than requested, so this function
    repeatedly calls recv() until the requested amount has arrived.

    Args:
        sock:
            Connected TCP socket.

        num_bytes:
            Exact number of bytes required.

        allow_clean_close:
            If True, returning b"" before receiving anything means
            the peer cleanly closed the connection and None is returned.

            If False, any early connection close raises ConnectionError.

    Returns:
        Exactly num_bytes bytes.

        None if allow_clean_close=True and the connection closed
        before any bytes were received.

    Raises:
        ValueError:
            If num_bytes is negative.

        ConnectionError:
            If the peer closes the connection before all requested
            bytes arrive.
    """

    if num_bytes < 0:
        raise ValueError("num_bytes cannot be negative")

    if num_bytes == 0:
        return b""

    received = bytearray()

    while len(received) < num_bytes:

        remaining = num_bytes - len(received)

        try:
            chunk = sock.recv(remaining)
        except socket.timeout:
            raise
        except (ConnectionResetError, BrokenPipeError, OSError) as exc:
            raise ConnectionError(
                "socket error while receiving data"
            ) from exc

        # -----------------------------------------------------
        # recv() returning b"" means EOF.
        # -----------------------------------------------------
        if chunk == b"":

            if len(received) == 0 and allow_clean_close:
                return None

            raise ConnectionError(
                f"connection closed while receiving data "
                f"(received {len(received)} of {num_bytes} bytes)"
            )

        received.extend(chunk)

    return bytes(received)