import socket
import threading

from bittorrent_lite.peer.connection import PeerConnection
from bittorrent_lite.protocol.framing import send_message, recv_message
from bittorrent_lite.protocol.messages import Choke, Unchoke


def test_choke_callback():
    sock1, sock2 = socket.socketpair()

    received = []
    event = threading.Event()

    def on_choke(message):
        received.append(message)
        event.set()

    try:
        conn = PeerConnection(
            sock1,
            callbacks={"on_choke": on_choke},
        )
        conn.start()

        send_message(sock2, Choke())

        assert event.wait(timeout=2)
        assert len(received) == 1
        assert isinstance(received[0], Choke)

        conn.close()

    finally:
        try:
            sock2.close()
        except OSError:
            pass


def test_unchoke_callback():
    sock1, sock2 = socket.socketpair()

    received = []
    event = threading.Event()

    def on_unchoke(message):
        received.append(message)
        event.set()

    try:
        conn = PeerConnection(
            sock1,
            callbacks={"on_unchoke": on_unchoke},
        )
        conn.start()

        send_message(sock2, Unchoke())

        assert event.wait(timeout=2)
        assert len(received) == 1
        assert isinstance(received[0], Unchoke)

        conn.close()

    finally:
        try:
            sock2.close()
        except OSError:
            pass


def test_choke_can_be_sent():
    sock1, sock2 = socket.socketpair()

    try:
        conn = PeerConnection(sock1)
        conn.start()

        conn.send(Choke())

        received = recv_message(sock2)

        assert isinstance(received, Choke)

        conn.close()

    finally:
        try:
            sock2.close()
        except OSError:
            pass


def test_unchoke_can_be_sent():
    sock1, sock2 = socket.socketpair()

    try:
        conn = PeerConnection(sock1)
        conn.start()

        conn.send(Unchoke())

        received = recv_message(sock2)

        assert isinstance(received, Unchoke)

        conn.close()

    finally:
        try:
            sock2.close()
        except OSError:
            pass


def test_choke_unchoke_sequence():
    sock1, sock2 = socket.socketpair()

    received = []
    events = [threading.Event(), threading.Event()]

    def on_choke(message):
        received.append(("choke", message))
        events[0].set()

    def on_unchoke(message):
        received.append(("unchoke", message))
        events[1].set()

    try:
        conn = PeerConnection(
            sock1,
            callbacks={
                "on_choke": on_choke,
                "on_unchoke": on_unchoke,
            },
        )
        conn.start()

        send_message(sock2, Choke())
        assert events[0].wait(timeout=2)

        send_message(sock2, Unchoke())
        assert events[1].wait(timeout=2)

        assert len(received) == 2
        assert received[0][0] == "choke"
        assert received[1][0] == "unchoke"

        assert isinstance(received[0][1], Choke)
        assert isinstance(received[1][1], Unchoke)

        conn.close()

    finally:
        try:
            sock2.close()
        except OSError:
            pass


def test_choke_unchoke_send_sequence():
    sock1, sock2 = socket.socketpair()

    try:
        conn = PeerConnection(sock1)
        conn.start()

        conn.send(Choke())
        conn.send(Unchoke())

        first = recv_message(sock2)
        second = recv_message(sock2)

        assert isinstance(first, Choke)
        assert isinstance(second, Unchoke)

        conn.close()

    finally:
        try:
            sock2.close()
        except OSError:
            pass