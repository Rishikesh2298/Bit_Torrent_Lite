import socket
import threading

from bittorrent_lite.peer.connection import PeerConnection
from bittorrent_lite.protocol.messages import (
    Interested,
    Have,
    Piece,
)


def test_connection_can_send_message():

    sock1, sock2 = socket.socketpair()

    try:
        conn = PeerConnection(sock1)
        conn.start()

        conn.send(Interested())

        from bittorrent_lite.protocol.framing import recv_message

        message = recv_message(sock2)

        assert isinstance(message, Interested)

        conn.close()

    finally:
        sock2.close()


def test_connection_send_uses_sender_thread():

    sock1, sock2 = socket.socketpair()

    try:
        conn = PeerConnection(sock1)
        conn.start()

        conn.send(Have(5))

        from bittorrent_lite.protocol.framing import recv_message

        message = recv_message(sock2)

        assert isinstance(message, Have)
        assert message.piece_index == 5

        conn.close()

    finally:
        sock2.close()


def test_piece_callback():

    sock1, sock2 = socket.socketpair()

    received = []
    event = threading.Event()

    def on_piece(message):
        received.append(message)
        event.set()

    try:
        conn = PeerConnection(
            sock1,
            callbacks={
                "on_piece": on_piece
            },
        )

        conn.start()

        piece = Piece(
            request_id=1,
            piece_index=2,
            _payload=b"hello world",
        )

        from bittorrent_lite.protocol.framing import send_message

        send_message(sock2, piece)

        assert event.wait(timeout=2)

        assert len(received) == 1
        assert isinstance(received[0], Piece)
        assert received[0].piece_index == 2
        assert received[0].request_id == 1
        assert received[0].payload == b"hello world"

        conn.close()

    finally:
        sock2.close()


def test_disconnect_callback():

    sock1, sock2 = socket.socketpair()

    disconnected = threading.Event()

    def on_disconnect(*args):
        disconnected.set()

    try:
        conn = PeerConnection(
            sock1,
            callbacks={
                "on_disconnect": on_disconnect
            },
        )

        conn.start()

        sock2.close()

        assert disconnected.wait(timeout=2)

        conn.close()

    finally:
        try:
            sock2.close()
        except OSError:
            pass