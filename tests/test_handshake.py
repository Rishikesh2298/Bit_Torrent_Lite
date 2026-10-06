import socket
import threading

from bittorrent_lite.peer.connection import PeerConnection
from bittorrent_lite.protocol.framing import send_message, recv_message
from bittorrent_lite.protocol.messages import Handshake


PROTOCOL_VERSION = "1.0"
FILE_ID = "test-file-123"


def test_handshake_updates_remote_peer_id():

    sock1, sock2 = socket.socketpair()

    received = []
    event = threading.Event()

    def on_handshake(message):
        received.append(message)
        event.set()

    try:

        conn = PeerConnection(
            sock1,
            callbacks={
                "on_handshake": on_handshake
            },
        )

        conn.start()

        handshake = Handshake(
            protocol_version=PROTOCOL_VERSION,
            file_id=FILE_ID,
            peer_id="peer-B",
        )

        send_message(
            sock2,
            handshake,
        )

        assert event.wait(timeout=2)

        assert conn.remote_peer_id == "peer-B"

        assert len(received) == 1

        assert isinstance(
            received[0],
            Handshake,
        )

        assert received[0].peer_id == "peer-B"
        assert received[0].protocol_version == PROTOCOL_VERSION
        assert received[0].file_id == FILE_ID

        conn.close()

    finally:

        try:
            sock2.close()
        except OSError:
            pass


def test_handshake_can_be_sent():

    sock1, sock2 = socket.socketpair()

    try:

        conn = PeerConnection(sock1)

        conn.start()

        handshake = Handshake(
            protocol_version=PROTOCOL_VERSION,
            file_id=FILE_ID,
            peer_id="peer-A",
        )

        conn.send(handshake)

        received = recv_message(sock2)

        assert isinstance(
            received,
            Handshake,
        )

        assert received.peer_id == "peer-A"
        assert received.protocol_version == PROTOCOL_VERSION
        assert received.file_id == FILE_ID

        conn.close()

    finally:

        try:
            sock2.close()
        except OSError:
            pass


def test_two_connections_exchange_handshakes():

    sock1, sock2 = socket.socketpair()

    event1 = threading.Event()
    event2 = threading.Event()

    received1 = []
    received2 = []

    def on_handshake_1(message):

        received1.append(message)
        event1.set()

    def on_handshake_2(message):

        received2.append(message)
        event2.set()

    try:

        conn1 = PeerConnection(
            sock1,
            callbacks={
                "on_handshake": on_handshake_1
            },
        )

        conn2 = PeerConnection(
            sock2,
            callbacks={
                "on_handshake": on_handshake_2
            },
        )

        conn1.start()
        conn2.start()

        conn1.send(
            Handshake(
                protocol_version=PROTOCOL_VERSION,
                file_id=FILE_ID,
                peer_id="peer-A",
            )
        )

        conn2.send(
            Handshake(
                protocol_version=PROTOCOL_VERSION,
                file_id=FILE_ID,
                peer_id="peer-B",
            )
        )

        assert event1.wait(timeout=2)
        assert event2.wait(timeout=2)

        assert conn1.remote_peer_id == "peer-B"
        assert conn2.remote_peer_id == "peer-A"

        assert received1[0].peer_id == "peer-B"
        assert received2[0].peer_id == "peer-A"

        assert received1[0].protocol_version == PROTOCOL_VERSION
        assert received2[0].protocol_version == PROTOCOL_VERSION

        assert received1[0].file_id == FILE_ID
        assert received2[0].file_id == FILE_ID

        conn1.close()
        conn2.close()

    finally:

        try:
            sock1.close()
        except OSError:
            pass

        try:
            sock2.close()
        except OSError:
            pass