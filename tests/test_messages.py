"""Message-object JSON round trips; TCP framing is a separate, unfinished layer.

BITFIELD uses a JSON list in the current protocol, not binary bit packing.
REQUEST/CANCEL identify a whole piece by request ID and piece index.
"""
import json

import pytest

from bittorrent_lite.protocol import messages as m
from bittorrent_lite.config import PROTOCOL_VERSION


def roundtrip(message):
    header = json.loads(json.dumps(message.to_header()))
    restored = m.MESSAGE_REGISTRY[header['type']].from_header(header, message.payload)
    assert type(restored) is type(message)
    assert restored.to_header() == header
    assert restored.payload == message.payload
    return restored


class TestMessageSerialization:
    def test_choke_roundtrip(self):
        assert roundtrip(m.Choke()).to_header() == {'type': 'CHOKE'}

    def test_unchoke_roundtrip(self):
        assert roundtrip(m.Unchoke()).to_header() == {'type': 'UNCHOKE'}

    def test_interested_roundtrip(self):
        assert roundtrip(m.Interested()).to_header() == {'type': 'INTERESTED'}

    def test_not_interested_roundtrip(self):
        assert roundtrip(m.NotInterested()).to_header() == {'type': 'NOT_INTERESTED'}

    def test_have_roundtrip(self):
        assert roundtrip(m.Have(42)).piece_index == 42

    def test_bitfield_roundtrip(self):
        original = m.BitfieldMsg([1, 0, 1])
        restored = roundtrip(original)
        original.pieces[0] = 0
        assert restored.pieces == [1, 0, 1]

    def test_request_roundtrip(self):
        r = roundtrip(m.Request(17, 3))
        assert (r.request_id, r.piece_index) == (17, 3)

    def test_piece_roundtrip(self):
        data = bytes(range(256)) * 256
        r = roundtrip(m.Piece(17, 3, data))
        assert (r.request_id, r.piece_index, r.payload) == (17, 3, data)
        assert r.to_header()['payload_length'] == len(data)

    def test_cancel_roundtrip(self):
        r = roundtrip(m.Cancel(17, 3))
        assert (r.request_id, r.piece_index) == (17, 3)


class TestHandshake:
    def test_handshake_roundtrip(self):
        r = roundtrip(m.Handshake(PROTOCOL_VERSION, 'f'*64, 'peer-1'))
        assert (r.protocol_version, r.file_id, r.peer_id) == (PROTOCOL_VERSION, 'f'*64, 'peer-1')

    def test_handshake_wrong_protocol(self):
        # This protocol carries a numeric version, not a protocol-name field.
        for version in (PROTOCOL_VERSION + 1, True, str(PROTOCOL_VERSION), None):
            header = m.Handshake(version, 'f'*64, 'peer-1').to_header()
            with pytest.raises(ValueError):
                m.Handshake.from_header(header, b'')


class TestBitfieldEncoding:
    def test_bitfield_10_pieces(self):
        bits = [1, 0, 1, 1, 0, 0, 1, 0, 1, 0]
        assert roundtrip(m.BitfieldMsg(bits)).to_header() == {'type': 'BITFIELD', 'pieces': bits}

    def test_bitfield_exact_byte_boundary(self):
        # Eight pieces remain eight JSON entries, not a packed byte.
        bits = [1, 0] * 4
        assert roundtrip(m.BitfieldMsg(bits)).pieces == bits

    def test_bitfield_all_true(self):
        assert roundtrip(m.BitfieldMsg([1]*10)).pieces == [1]*10

    def test_bitfield_all_false(self):
        assert roundtrip(m.BitfieldMsg([0]*10)).pieces == [0]*10
