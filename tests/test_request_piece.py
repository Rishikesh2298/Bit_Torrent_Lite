import socket
import threading

from bittorrent_lite.peer.connection import PeerConnection
from bittorrent_lite.protocol.framing import send_message, recv_message
from bittorrent_lite.protocol.messages import (
    Interested,
    NotInterested,
    Request,
    Piece,
)


def test_interested_callback():

    sock1, sock2 = socket.socketpair()

    received = []
    event = threading.Event()

    def on_interested(message):
        received.append(message)
        event.set()

    try:

        conn = PeerConnection(
            sock1,
            callbacks={
                "on_interested": on_interested
            },
        )

        conn.start()

        send_message(
            sock2,
            Interested(),
        )

        assert event.wait(timeout=2)

        assert len(received) == 1
        assert isinstance(
            received[0],
            Interested,
        )

        conn.close()

    finally:

        try:
            sock2.close()
        except OSError:
            pass


def test_not_interested_callback():

    sock1, sock2 = socket.socketpair()

    received = []
    event = threading.Event()

    def on_not_interested(message):
        received.append(message)
        event.set()

    try:

        conn = PeerConnection(
            sock1,
            callbacks={
                "on_not_interested": on_not_interested
            },
        )

        conn.start()

        send_message(
            sock2,
            NotInterested(),
        )

        assert event.wait(timeout=2)

        assert len(received) == 1
        assert isinstance(
            received[0],
            NotInterested,
        )

        conn.close()

    finally:

        try:
            sock2.close()
        except OSError:
            pass


def test_request_callback():

    sock1, sock2 = socket.socketpair()

    received = []
    event = threading.Event()

    def on_request(message):
        received.append(message)
        event.set()

    try:

        conn = PeerConnection(
            sock1,
            callbacks={
                "on_request": on_request
            },
        )

        conn.start()

        request = Request(
            request_id=1,
            piece_index=4,
        )

        send_message(
            sock2,
            request,
        )

        assert event.wait(timeout=2)

        assert len(received) == 1

        assert isinstance(
            received[0],
            Request,
        )

        assert received[0].request_id == 1
        assert received[0].piece_index == 4

        conn.close()

    finally:

        try:
            sock2.close()
        except OSError:
            pass


def test_piece_callback_and_payload():

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

        piece_data = b"This is the content of piece number 4."

        piece = Piece(
            request_id=1,
            piece_index=4,
            _payload=piece_data,
        )

        send_message(
            sock2,
            piece,
        )

        assert event.wait(timeout=2)

        assert len(received) == 1

        received_piece = received[0]

        assert isinstance(
            received_piece,
            Piece,
        )

        assert received_piece.request_id == 1
        assert received_piece.piece_index == 4
        assert received_piece.payload == piece_data

        conn.close()

    finally:

        try:
            sock2.close()
        except OSError:
            pass


def test_request_can_be_sent():

    sock1, sock2 = socket.socketpair()

    try:

        conn = PeerConnection(sock1)

        conn.start()

        request = Request(
            request_id=25,
            piece_index=8,
        )

        conn.send(request)

        received = recv_message(sock2)

        assert isinstance(
            received,
            Request,
        )

        assert received.request_id == 25
        assert received.piece_index == 8

        conn.close()

    finally:

        try:
            sock2.close()
        except OSError:
            pass


def test_piece_can_be_sent():

    sock1, sock2 = socket.socketpair()

    try:

        conn = PeerConnection(sock1)

        conn.start()

        piece_data = b"ABCDEFGHIJKLMNOPQRSTUVWXYZ"

        piece = Piece(
            request_id=25,
            piece_index=8,
            _payload=piece_data,
        )

        conn.send(piece)

        received = recv_message(sock2)

        assert isinstance(
            received,
            Piece,
        )

        assert received.request_id == 25
        assert received.piece_index == 8
        assert received.payload == piece_data

        conn.close()

    finally:

        try:
            sock2.close()
        except OSError:
            pass


def test_interested_request_piece_flow():

    sock1, sock2 = socket.socketpair()

    interested_received = threading.Event()
    request_received = threading.Event()

    received_interested = []
    received_request = []

    def on_interested(message):
        received_interested.append(message)
        interested_received.set()

    def on_request(message):
        received_request.append(message)
        request_received.set()

    try:

        conn = PeerConnection(
            sock1,
            callbacks={
                "on_interested": on_interested,
                "on_request": on_request,
            },
        )

        conn.start()

        # Downloader tells seeder that it wants pieces.
        send_message(
            sock2,
            Interested(),
        )

        assert interested_received.wait(timeout=2)

        assert len(received_interested) == 1

        # Downloader requests piece 2.
        send_message(
            sock2,
            Request(
                request_id=100,
                piece_index=2,
            ),
        )

        assert request_received.wait(timeout=2)

        assert len(received_request) == 1
        assert received_request[0].request_id == 100
        assert received_request[0].piece_index == 2

        # Seeder sends requested piece.
        piece_data = b"piece-two-data"

        conn.send(
            Piece(
                request_id=100,
                piece_index=2,
                _payload=piece_data,
            )
        )

        received_piece = recv_message(sock2)

        assert isinstance(
            received_piece,
            Piece,
        )

        assert received_piece.request_id == 100
        assert received_piece.piece_index == 2
        assert received_piece.payload == piece_data

        conn.close()

    finally:

        try:
            sock2.close()
        except OSError:
            pass