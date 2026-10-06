import socket

from bittorrent_lite.protocol.framing import (
    send_message,
    recv_message,
)

from bittorrent_lite.protocol.messages import (
    Interested,
    Have,
    Request,
    Piece,
)


def test_interested_round_trip():
    sock1, sock2 = socket.socketpair()

    try:
        original = Interested()

        send_message(sock1, original)

        received = recv_message(sock2)

        assert isinstance(received, Interested)

    finally:
        sock1.close()
        sock2.close()


def test_have_round_trip():
    sock1, sock2 = socket.socketpair()

    try:
        original = Have(piece_index=7)

        send_message(sock1, original)

        received = recv_message(sock2)

        assert isinstance(received, Have)
        assert received.piece_index == 7

    finally:
        sock1.close()
        sock2.close()


def test_request_round_trip():
    sock1, sock2 = socket.socketpair()

    try:
        original = Request(
            request_id=42,
            piece_index=5,
        )

        send_message(sock1, original)

        received = recv_message(sock2)

        assert isinstance(received, Request)
        assert received.request_id == 42
        assert received.piece_index == 5

    finally:
        sock1.close()
        sock2.close()


def test_piece_round_trip():
    sock1, sock2 = socket.socketpair()

    try:
        data = b"Hello BitTorrent-Lite!"

        original = Piece(
            request_id=10,
            piece_index=3,
            _payload=data,
        )

        send_message(sock1, original)

        received = recv_message(sock2)

        assert isinstance(received, Piece)
        assert received.request_id == 10
        assert received.piece_index == 3
        assert received.payload == data

    finally:
        sock1.close()
        sock2.close()