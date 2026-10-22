"""NC05 independent byte fixtures; no expected bytes come from project encoders."""
import pytest

from bittorrent_lite.networking import messages as m
from bittorrent_lite.networking.framing import recv_message, send_message


class ByteStream:
    """A finite fake byte stream. This is a codec unit oracle, not TCP evidence."""
    def __init__(self, data=b"", chunk=65536):
        self.input = bytearray(data)
        self.output = bytearray()
        self.chunk = chunk

    def recv(self, size):
        take = min(size, self.chunk, len(self.input))
        result = bytes(self.input[:take])
        del self.input[:take]
        return result

    def sendall(self, data):
        self.output.extend(data)


GOLDENS = [
    (m.Interested(), b'{"type":"INTERESTED","payload_length":0}', b""),
    (m.NotInterested(), b'{"type":"NOT_INTERESTED","payload_length":0}', b""),
    (m.Choke(), b'{"type":"CHOKE","payload_length":0}', b""),
    (m.Unchoke(), b'{"type":"UNCHOKE","payload_length":0}', b""),
    (m.Have(2), b'{"type":"HAVE","piece_index":2,"payload_length":0}', b""),
    (m.BitfieldMsg([1, 0, 1]), b'{"type":"BITFIELD","pieces":[1,0,1],"payload_length":0}', b""),
    (m.Request(17, 2), b'{"type":"REQUEST","request_id":17,"piece_index":2,"payload_length":0}', b""),
    (m.Cancel(17, 2), b'{"type":"CANCEL","request_id":17,"piece_index":2,"payload_length":0}', b""),
    (m.Reject(17, 2, "busy"), b'{"type":"REJECT","request_id":17,"piece_index":2,"reason":"busy","payload_length":0}', b""),
    (m.Piece(17, 2, b"\x00\xff\x80\x01"), b'{"type":"PIECE","request_id":17,"piece_index":2,"payload_length":4}', b"\x00\xff\x80\x01"),
    (m.Handshake(1, "f" * 64, "peer-01"), b'{"type":"HANDSHAKE","protocol_version":1,"file_id":"' + b"f" * 64 + b'","peer_id":"peer-01","payload_length":0}', b""),
]


@pytest.mark.parametrize("message,header,payload", GOLDENS, ids=[row[0].type for row in GOLDENS])
def test_encoder_matches_literal_golden_bytes(message, header, payload):
    stream = ByteStream()
    send_message(stream, message)
    assert bytes(stream.output) == len(header).to_bytes(4, "big") + header + payload


@pytest.mark.parametrize("message,header,payload", GOLDENS, ids=[row[0].type for row in GOLDENS])
def test_decoder_accepts_independent_literal_frames_byte_by_byte(message, header, payload):
    stream = ByteStream(len(header).to_bytes(4, "big") + header + payload, chunk=1)
    decoded = recv_message(stream)
    assert type(decoded) is type(message)
    assert decoded == message
    assert decoded.payload == payload
    assert stream.input == b""


def test_utf8_header_prefix_counts_encoded_bytes():
    # The reusable codec allows Unicode strings; v1 runtime admission separately
    # restricts operational peer IDs to ASCII. Do not claim this is a valid peer.
    header = b'{"type":"HANDSHAKE","protocol_version":1,"file_id":"' + b"f" * 64 + b'","peer_id":"caf\xc3\xa9","payload_length":0}'
    message = m.Handshake(1, "f" * 64, "caf\u00e9")
    stream = ByteStream()
    send_message(stream, message)
    assert int.from_bytes(stream.output[:4], "big") == len(header)
    assert len(header) == len(header.decode("utf-8")) + 1
    assert bytes(stream.output[4:]) == header
    decoded = recv_message(ByteStream(len(header).to_bytes(4, "big") + header, chunk=1))
    assert decoded.peer_id == "caf\u00e9"
