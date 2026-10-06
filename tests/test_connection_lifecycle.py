import socket
import threading

from bittorrent_lite.peer.connection import PeerConnection
from bittorrent_lite.protocol.framing import send_message, recv_message
from bittorrent_lite.protocol.messages import (
    Handshake,
    BitfieldMsg,
    Interested,
    Unchoke,
    Request,
    Piece,
)


PROTOCOL_VERSION = "1.0"
FILE_ID = "test-file-123"


def test_full_peer_connection_lifecycle():
    sock1, sock2 = socket.socketpair()

    received = {
        "handshake": [],
        "bitfield": [],
        "interested": [],
        "unchoke": [],
        "request": [],
        "piece": [],
    }

    events = {
        "handshake": threading.Event(),
        "bitfield": threading.Event(),
        "interested": threading.Event(),
        "unchoke": threading.Event(),
        "request": threading.Event(),
        "piece": threading.Event(),
    }

    def on_handshake(message):
        received["handshake"].append(message)
        events["handshake"].set()

    def on_bitfield(message):
        received["bitfield"].append(message)
        events["bitfield"].set()

    def on_interested(message):
        received["interested"].append(message)
        events["interested"].set()

    def on_unchoke(message):
        received["unchoke"].append(message)
        events["unchoke"].set()

    def on_request(message):
        received["request"].append(message)
        events["request"].set()

    def on_piece(message):
        received["piece"].append(message)
        events["piece"].set()

    try:
        conn = PeerConnection(
            sock1,
            callbacks={
                "on_handshake": on_handshake,
                "on_bitfield": on_bitfield,
                "on_interested": on_interested,
                "on_unchoke": on_unchoke,
                "on_request": on_request,
                "on_piece": on_piece,
            },
        )

        conn.start()

        # ---------------------------------------------------------
        # 1. HANDSHAKE
        # ---------------------------------------------------------
        send_handshake = Handshake(
            protocol_version=PROTOCOL_VERSION,
            file_id=FILE_ID,
            peer_id="peer-02",
        )

        conn.send(send_handshake)

        received_handshake = recv_message(sock2)

        assert isinstance(received_handshake, Handshake)
        assert received_handshake.protocol_version == PROTOCOL_VERSION
        assert received_handshake.file_id == FILE_ID
        assert received_handshake.peer_id == "peer-02"

        remote_handshake = Handshake(
            protocol_version=PROTOCOL_VERSION,
            file_id=FILE_ID,
            peer_id="peer-01",
        )

        send_message(sock2, remote_handshake)

        assert events["handshake"].wait(timeout=2)
        assert len(received["handshake"]) == 1
        assert received["handshake"][0].peer_id == "peer-01"
        assert conn.remote_peer_id == "peer-01"

        # ---------------------------------------------------------
        # 2. BITFIELD
        # ---------------------------------------------------------
        bitfield = BitfieldMsg([1, 0, 1, 0, 1])

        send_message(sock2, bitfield)

        assert events["bitfield"].wait(timeout=2)
        assert len(received["bitfield"]) == 1
        assert received["bitfield"][0].pieces == [1, 0, 1, 0, 1]

        # ---------------------------------------------------------
        # 3. INTERESTED
        # ---------------------------------------------------------
        send_message(sock2, Interested())

        assert events["interested"].wait(timeout=2)
        assert len(received["interested"]) == 1
        assert isinstance(received["interested"][0], Interested)

        # ---------------------------------------------------------
        # 4. UNCHOKE
        # ---------------------------------------------------------
        send_message(sock2, Unchoke())

        assert events["unchoke"].wait(timeout=2)
        assert len(received["unchoke"]) == 1
        assert isinstance(received["unchoke"][0], Unchoke)

        # ---------------------------------------------------------
        # 5. REQUEST
        # ---------------------------------------------------------
        request = Request(
            request_id=101,
            piece_index=2,
        )

        send_message(sock2, request)

        assert events["request"].wait(timeout=2)
        assert len(received["request"]) == 1
        assert received["request"][0].request_id == 101
        assert received["request"][0].piece_index == 2

        # ---------------------------------------------------------
        # 6. PIECE
        # ---------------------------------------------------------
        piece_data = b"hello bittorrent"

        piece = Piece(
            request_id=101,
            piece_index=2,
            _payload=piece_data,
        )

        send_message(sock2, piece)

        assert events["piece"].wait(timeout=2)
        assert len(received["piece"]) == 1

        received_piece = received["piece"][0]

        assert received_piece.request_id == 101
        assert received_piece.piece_index == 2
        assert received_piece.payload == piece_data

        conn.close()

    finally:
        try:
            sock2.close()
        except OSError:
            pass


def test_connection_detects_remote_close():
    sock1, sock2 = socket.socketpair()

    disconnected = threading.Event()

    def on_disconnect(*args):
        disconnected.set()

    try:
        conn = PeerConnection(
            sock1,
            callbacks={
                "on_disconnect": on_disconnect,
            },
        )

        conn.start()

        sock2.close()

        assert disconnected.wait(timeout=2)

    finally:
        try:
            conn.close()
        except Exception:
            pass


def test_connection_can_continue_after_multiple_messages():
    sock1, sock2 = socket.socketpair()

    received = []
    event = threading.Event()

    def on_interested(message):
        received.append(message)

        if len(received) == 3:
            event.set()

    try:
        conn = PeerConnection(
            sock1,
            callbacks={
                "on_interested": on_interested,
            },
        )

        conn.start()

        send_message(sock2, Interested())
        send_message(sock2, Interested())
        send_message(sock2, Interested())

        assert event.wait(timeout=2)
        assert len(received) == 3

        for message in received:
            assert isinstance(message, Interested)

        conn.close()

    finally:
        try:
            sock2.close()
        except OSError:
            pass