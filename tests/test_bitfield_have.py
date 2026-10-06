import socket
import threading

from bittorrent_lite.peer.connection import PeerConnection
from bittorrent_lite.protocol.framing import send_message
from bittorrent_lite.protocol.messages import (
    BitfieldMsg,
    Have,
)


def test_bitfield_callback():

    sock1, sock2 = socket.socketpair()

    received = []
    event = threading.Event()

    def on_bitfield(message):
        received.append(message)
        event.set()

    try:

        conn = PeerConnection(
            sock1,
            callbacks={
                "on_bitfield": on_bitfield
            },
        )

        conn.start()

        bitfield = BitfieldMsg(
            pieces=[1, 0, 1, 1, 0, 0, 1]
        )

        send_message(
            sock2,
            bitfield,
        )

        assert event.wait(timeout=2)

        assert len(received) == 1

        assert isinstance(
            received[0],
            BitfieldMsg,
        )

        assert received[0].pieces == [
            1,
            0,
            1,
            1,
            0,
            0,
            1,
        ]

        conn.close()

    finally:

        try:
            sock2.close()
        except OSError:
            pass


def test_have_callback():

    sock1, sock2 = socket.socketpair()

    received = []
    event = threading.Event()

    def on_have(message):
        received.append(message)
        event.set()

    try:

        conn = PeerConnection(
            sock1,
            callbacks={
                "on_have": on_have
            },
        )

        conn.start()

        have = Have(
            piece_index=7
        )

        send_message(
            sock2,
            have,
        )

        assert event.wait(timeout=2)

        assert len(received) == 1

        assert isinstance(
            received[0],
            Have,
        )

        assert received[0].piece_index == 7

        conn.close()

    finally:

        try:
            sock2.close()
        except OSError:
            pass


def test_bitfield_and_have_sequence():

    sock1, sock2 = socket.socketpair()

    bitfield_received = threading.Event()
    have_received = threading.Event()

    received_bitfields = []
    received_haves = []

    def on_bitfield(message):

        received_bitfields.append(message)
        bitfield_received.set()

    def on_have(message):

        received_haves.append(message)
        have_received.set()

    try:

        conn = PeerConnection(
            sock1,
            callbacks={
                "on_bitfield": on_bitfield,
                "on_have": on_have,
            },
        )

        conn.start()

        send_message(
            sock2,
            BitfieldMsg(
                pieces=[1, 0, 0, 1, 1]
            ),
        )

        send_message(
            sock2,
            Have(
                piece_index=3
            ),
        )

        assert bitfield_received.wait(timeout=2)
        assert have_received.wait(timeout=2)

        assert len(received_bitfields) == 1
        assert len(received_haves) == 1

        assert received_bitfields[0].pieces == [
            1,
            0,
            0,
            1,
            1,
        ]

        assert received_haves[0].piece_index == 3

        conn.close()

    finally:

        try:
            sock2.close()
        except OSError:
            pass


def test_bitfield_can_be_sent():

    sock1, sock2 = socket.socketpair()

    try:

        conn = PeerConnection(sock1)

        conn.start()

        message = BitfieldMsg(
            pieces=[1, 1, 0, 0, 1]
        )

        conn.send(message)

        from bittorrent_lite.protocol.framing import recv_message

        received = recv_message(sock2)

        assert isinstance(
            received,
            BitfieldMsg,
        )

        assert received.pieces == [
            1,
            1,
            0,
            0,
            1,
        ]

        conn.close()

    finally:

        try:
            sock2.close()
        except OSError:
            pass


def test_have_can_be_sent():

    sock1, sock2 = socket.socketpair()

    try:

        conn = PeerConnection(sock1)

        conn.start()

        message = Have(
            piece_index=10
        )

        conn.send(message)

        from bittorrent_lite.protocol.framing import recv_message

        received = recv_message(sock2)

        assert isinstance(
            received,
            Have,
        )

        assert received.piece_index == 10

        conn.close()

    finally:

        try:
            sock2.close()
        except OSError:
            pass