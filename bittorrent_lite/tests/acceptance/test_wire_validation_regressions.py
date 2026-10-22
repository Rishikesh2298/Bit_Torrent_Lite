"""Direct v1 wire regressions from final plan A.8, NW03/NW05/NW12.

Finite codec streams are synthetic unit inputs, never real-network credit.
Legacy convenience constructors are intentionally outside these wire assertions.
"""
import json

import pytest

from bittorrent_lite.networking.framing import recv_message, send_message
from bittorrent_lite.networking.messages import Message


class WireBytes:
    def __init__(self, header, payload=b""):
        encoded = json.dumps(header, separators=(",", ":"), allow_nan=False).encode("utf-8")
        self.remaining = len(encoded).to_bytes(4, "big") + encoded + payload

    def recv(self, count):
        result, self.remaining = self.remaining[:count], self.remaining[count:]
        return result


CONTROL_HEADERS = [
    {"type": "INTERESTED"},
    {"type": "NOT_INTERESTED"},
    {"type": "CHOKE"},
    {"type": "UNCHOKE"},
    {"type": "HAVE", "piece_index": 0},
    {"type": "BITFIELD", "pieces": [1, 0]},
    {"type": "REQUEST", "request_id": 1, "piece_index": 0},
    {"type": "CANCEL", "request_id": 1, "piece_index": 0},
    {"type": "REJECT", "request_id": 1, "piece_index": 0, "reason": "busy"},
    {"type": "HANDSHAKE", "protocol_version": 1, "file_id": "f" * 64, "peer_id": "peer-01"},
]


@pytest.mark.parametrize("header", CONTROL_HEADERS, ids=[row["type"] for row in CONTROL_HEADERS])
def test_all_control_types_reject_nonzero_wire_payload(header):
    valid = recv_message(WireBytes({**header, "payload_length": 0}))
    assert valid.type == header["type"] and valid.payload == b""
    with pytest.raises(ValueError):
        recv_message(WireBytes({**header, "payload_length": 1}, b"\x00"))


@pytest.mark.parametrize("pieces", [[True], [False], [0.0], [1.0], [0, True], [1, 0.0],
                                    {}, "01", None, 1, [[1]], [2], [-1]],
                         ids=["true", "false", "float-zero", "float-one", "mixed-bool", "mixed-float",
                              "object", "string", "null", "integer", "nested", "two", "negative"])
def test_bitfield_wire_requires_array_of_integer_zero_or_one(pieces):
    with pytest.raises(ValueError):
        recv_message(WireBytes({"type": "BITFIELD", "pieces": pieces, "payload_length": 0}))


@pytest.mark.parametrize("pieces", [[0], [1], [0, 1, 0, 1]])
def test_bitfield_wire_keeps_valid_integer_array_exact(pieces):
    message = recv_message(WireBytes({"type": "BITFIELD", "pieces": pieces, "payload_length": 0}))
    assert message.pieces == pieces
    assert all(type(value) is int for value in message.pieces)


@pytest.mark.parametrize("kind", ["REQUEST", "PIECE", "CANCEL", "REJECT"])
@pytest.mark.parametrize("request_id", [0, -1, True, False, 2 ** 63],
                         ids=["zero", "negative", "true", "false", "above-signed-63-bit"])
def test_request_bearing_wire_types_reject_identity_outside_v1_range(kind, request_id):
    payload = b"piece" if kind == "PIECE" else b""
    header = {"type": kind, "request_id": request_id, "piece_index": 0, "payload_length": len(payload)}
    if kind == "REJECT":
        header["reason"] = "busy"
    with pytest.raises(ValueError):
        recv_message(WireBytes(header, payload))


@pytest.mark.parametrize("kind", ["REQUEST", "PIECE", "CANCEL", "REJECT"])
@pytest.mark.parametrize("request_id", [1, 2 ** 63 - 1], ids=["minimum", "maximum"])
def test_request_bearing_wire_types_accept_v1_identity_endpoints(kind, request_id):
    payload = b"piece" if kind == "PIECE" else b""
    header = {"type": kind, "request_id": request_id, "piece_index": 0, "payload_length": len(payload)}
    if kind == "REJECT":
        header["reason"] = "busy"
    message = recv_message(WireBytes(header, payload))
    assert (message.type, message.request_id, message.piece_index, message.payload) == (kind, request_id, 0, payload)


class HeaderMessage(Message):
    """Explicit adversarial Message implementation without constructor repair."""
    def __init__(self, header, payload=b""):
        self.header, self.data = header, payload

    def to_header(self):
        return dict(self.header)

    @property
    def payload(self):
        return self.data


class WriteRecorder:
    def __init__(self):
        self.writes = []

    def sendall(self, data):
        self.writes.append(bytes(data))


SEND_INVALID = [(f"control-{header['type']}", header, b"x") for header in CONTROL_HEADERS]
SEND_INVALID += [(f"bitfield-{name}", {"type": "BITFIELD", "pieces": pieces}, b"")
                 for name, pieces in [("boolean", [True]), ("float", [0.0]), ("object", {}), ("string", "01")]]
SEND_INVALID += [(f"identity-{kind}-{name}", {"type": kind, "request_id": request_id, "piece_index": 0,
                                           **({"reason": "busy"} if kind == "REJECT" else {})},
                  b"piece" if kind == "PIECE" else b"")
                 for kind in ("REQUEST", "PIECE", "CANCEL", "REJECT")
                 for name, request_id in (("zero", 0), ("too-large", 2 ** 63))]


@pytest.mark.parametrize("name,header,payload", SEND_INVALID, ids=[row[0] for row in SEND_INVALID])
def test_encoder_rejects_invalid_v1_fields_before_any_socket_write(name, header, payload):
    recorder = WriteRecorder()
    with pytest.raises(ValueError):
        send_message(recorder, HeaderMessage(header, payload))
    assert recorder.writes == [], name


def test_decoder_rejects_bounded_deep_json_with_controlled_error():
    raw_header = b'{"type":"INTERESTED","payload_length":0,"extra":' + b"[" * 4000 + b"0" + b"]" * 4000 + b"}"
    assert len(raw_header) < 16384
    stream = WireBytes.__new__(WireBytes)
    stream.remaining = len(raw_header).to_bytes(4, "big") + raw_header
    with pytest.raises(ValueError):
        recv_message(stream)


def test_encoder_rejects_deep_header_before_any_socket_write():
    nested = 0
    for _ in range(4000):
        nested = [nested]
    recorder = WriteRecorder()
    with pytest.raises(ValueError):
        send_message(recorder, HeaderMessage({"type": "INTERESTED", "extra": nested}))
    assert recorder.writes == []
