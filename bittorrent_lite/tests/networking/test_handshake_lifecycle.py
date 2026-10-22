from bittorrent_lite.common.config import PROTOCOL_VERSION
import socket
import threading

from bittorrent_lite.networking.connection import PeerConnection

from bittorrent_lite.networking.messages import Handshake
from bittorrent_lite.networking.messages import Interested


def create_handshake(
    peer_id,
    file_id="file-123",
    protocol_version=PROTOCOL_VERSION,
):
    return Handshake(
        protocol_version=protocol_version,
        file_id=file_id,
        peer_id=peer_id,
    )


def test_handshake_is_sent_and_received():

    sock1, sock2 = socket.socketpair()

    received = {
        "handshake": None
    }

    event = threading.Event()

    def on_handshake(message):

        received["handshake"] = message

        event.set()

    handshake1 = create_handshake(
        peer_id="peer-A"
    )

    handshake2 = create_handshake(
        peer_id="peer-B"
    )

    peer1 = PeerConnection(
        sock1,
        callbacks={
            "on_handshake": on_handshake
        },
        local_handshake=handshake1,
        expected_file_id="file-123",
        expected_protocol_version=PROTOCOL_VERSION,
        require_handshake=True,
    )

    peer2 = PeerConnection(
        sock2,
        local_handshake=handshake2,
        expected_file_id="file-123",
        expected_protocol_version=PROTOCOL_VERSION,
        require_handshake=True,
    )

    try:

        peer1.start()
        peer2.start()

        assert event.wait(
            timeout=3
        )

        assert (
            received["handshake"].peer_id
            == "peer-B"
        )

        assert (
            peer1.handshake_sent
        )

        assert (
            peer1.handshake_received
        )

        assert (
            peer1.handshake_complete
        )

        assert (
            peer2.handshake_sent
        )

        assert (
            peer2.handshake_received
        )

        assert (
            peer2.handshake_complete
        )

        assert (
            peer1.remote_peer_id
            == "peer-B"
        )

        assert (
            peer2.remote_peer_id
            == "peer-A"
        )

    finally:

        peer1.close()
        peer2.close()


def test_send_handshake_only_once():

    sock1, sock2 = socket.socketpair()

    handshake = create_handshake(
        peer_id="peer-A"
    )

    peer = PeerConnection(
        sock1,
        local_handshake=handshake,
    )

    try:

        peer.start()

        # start() already queues the handshake.
        assert peer.handshake_sent

        # A second attempt must not queue another one.
        assert (
            peer.send_handshake()
            is False
        )

    finally:

        peer.close()

        try:
            sock2.close()
        except OSError:
            pass


def test_protocol_version_mismatch_closes_connection():

    sock1, sock2 = socket.socketpair()

    received_disconnect = threading.Event()

    def on_disconnect(*args):
        received_disconnect.set()

    local_handshake = create_handshake(
        peer_id="peer-A",
        protocol_version=PROTOCOL_VERSION,
    )

    remote_handshake = create_handshake(
        peer_id="peer-B",
        protocol_version=PROTOCOL_VERSION + 1,
    )

    peer1 = PeerConnection(
        sock1,
        local_handshake=local_handshake,
        expected_file_id="file-123",
        expected_protocol_version=PROTOCOL_VERSION,
        callbacks={
            "on_disconnect": on_disconnect
        },
        require_handshake=True,
    )

    peer2 = PeerConnection(
        sock2,
        local_handshake=remote_handshake,
        expected_file_id="file-123",
        expected_protocol_version=PROTOCOL_VERSION,
        require_handshake=True,
    )

    try:

        peer1.start()
        peer2.start()

        assert received_disconnect.wait(
            timeout=3
        )

        # A rejected wire handshake must also release its socket and workers.
        peer1.join(timeout=2)
        assert peer1.closed
        assert peer1.sock.fileno() == -1
        assert not peer1._reader_thread.is_alive()
        assert not peer1._writer_thread.is_alive()

        assert (
            not peer1.handshake_complete
            or not peer2.handshake_complete
        )

    finally:

        peer1.close()
        peer2.close()


def test_file_id_mismatch_closes_connection():

    sock1, sock2 = socket.socketpair()

    disconnected = threading.Event()

    def on_disconnect(*args):
        disconnected.set()

    handshake1 = create_handshake(
        peer_id="peer-A",
        file_id="file-A",
    )

    handshake2 = create_handshake(
        peer_id="peer-B",
        file_id="file-B",
    )

    peer1 = PeerConnection(
        sock1,
        local_handshake=handshake1,
        expected_file_id="file-A",
        expected_protocol_version=PROTOCOL_VERSION,
        require_handshake=True,
        callbacks={
            "on_disconnect": on_disconnect
        },
    )

    peer2 = PeerConnection(
        sock2,
        local_handshake=handshake2,
        expected_file_id="file-A",
        expected_protocol_version=PROTOCOL_VERSION,
        require_handshake=True,
    )

    try:

        peer1.start()
        peer2.start()

        assert disconnected.wait(
            timeout=3
        )

    finally:

        peer1.close()
        peer2.close()


def test_normal_message_blocked_before_handshake():

    sock1, sock2 = socket.socketpair()

    peer = PeerConnection(
        sock1,
        require_handshake=True,
    )

    try:

        peer.start()

        try:

            peer.send(
                Interested()
            )

            assert False, (
                "Expected ConnectionError"
            )

        except ConnectionError:

            pass

    finally:

        peer.close()

        try:
            sock2.close()
        except OSError:
            pass
