"""
Tests for PeerNetwork handshake integration.
"""

import threading
import time

from bittorrent_lite.peer.network import PeerNetwork
from bittorrent_lite.protocol.handshake import Handshake


def wait_until(condition, timeout=3.0, interval=0.01):
    """
    Wait until condition() becomes True or timeout expires.
    """
    deadline = time.time() + timeout

    while time.time() < deadline:
        if condition():
            return True

        time.sleep(interval)

    return False


def make_handshake(file_id, peer_id):
    return Handshake(
        protocol_version="1.0",
        file_id=file_id,
        peer_id=peer_id,
    )


def test_two_networks_complete_handshake():
    """
    Two PeerNetwork instances should automatically complete
    the handshake when they connect.
    """
    file_id = "file-123"

    peer1_handshake = make_handshake(
        file_id,
        "peer-1",
    )

    peer2_handshake = make_handshake(
        file_id,
        "peer-2",
    )

    peer1 = PeerNetwork(
        host="127.0.0.1",
        port=0,
        local_handshake=peer1_handshake,
        expected_file_id=file_id,
        expected_protocol_version="1.0",
        require_handshake=True,
    )

    peer2 = PeerNetwork(
        host="127.0.0.1",
        port=0,
        local_handshake=peer2_handshake,
        expected_file_id=file_id,
        expected_protocol_version="1.0",
        require_handshake=True,
    )

    try:
        peer1.start()
        peer2.start()

        peer1_connection = peer1.connect(
            *peer2.address
        )

        assert wait_until(
            lambda: peer1_connection.handshake_complete
        )

        assert wait_until(
            lambda: peer2.connection_count == 1
        )

        peer2_connection = peer2.connections[0]

        assert peer2_connection.handshake_complete

        assert peer1_connection.remote_peer_id == "peer-2"
        assert peer2_connection.remote_peer_id == "peer-1"

        assert peer1_connection.handshake_sent
        assert peer1_connection.handshake_received

        assert peer2_connection.handshake_sent
        assert peer2_connection.handshake_received

    finally:
        peer1.stop()
        peer2.stop()


def test_outgoing_connection_is_tracked():
    """
    An outgoing connection should appear in the local network's
    active connection set.
    """
    file_id = "file-456"

    peer1 = PeerNetwork(
        host="127.0.0.1",
        port=0,
        local_handshake=make_handshake(
            file_id,
            "peer-1",
        ),
        expected_file_id=file_id,
        expected_protocol_version="1.0",
        require_handshake=True,
    )

    peer2 = PeerNetwork(
        host="127.0.0.1",
        port=0,
        local_handshake=make_handshake(
            file_id,
            "peer-2",
        ),
        expected_file_id=file_id,
        expected_protocol_version="1.0",
        require_handshake=True,
    )

    try:
        peer1.start()
        peer2.start()

        connection = peer1.connect(
            *peer2.address
        )

        assert wait_until(
            lambda: peer1.connection_count == 1
        )

        assert connection in peer1.connections

        assert wait_until(
            lambda: peer2.connection_count == 1
        )

    finally:
        peer1.stop()
        peer2.stop()


def test_connection_removed_after_disconnect():
    """
    A disconnected connection should be removed from the
    PeerNetwork connection set.
    """
    file_id = "file-789"

    peer1 = PeerNetwork(
        host="127.0.0.1",
        port=0,
        local_handshake=make_handshake(
            file_id,
            "peer-1",
        ),
        expected_file_id=file_id,
        expected_protocol_version="1.0",
        require_handshake=True,
    )

    peer2 = PeerNetwork(
        host="127.0.0.1",
        port=0,
        local_handshake=make_handshake(
            file_id,
            "peer-2",
        ),
        expected_file_id=file_id,
        expected_protocol_version="1.0",
        require_handshake=True,
    )

    disconnected = threading.Event()

    def on_disconnect(connection, reason=None):
        disconnected.set()

    peer2.on_disconnect = on_disconnect

    try:
        peer1.start()
        peer2.start()

        connection = peer1.connect(
            *peer2.address
        )

        assert wait_until(
            lambda: peer2.connection_count == 1
        )

        connection.close()

        assert disconnected.wait(timeout=3.0)

        assert wait_until(
            lambda: peer2.connection_count == 0
        )

    finally:
        peer1.stop()
        peer2.stop()


def test_handshake_mismatch_does_not_complete():
    """
    Peers using different file IDs must not complete the handshake.
    """
    peer1 = PeerNetwork(
        host="127.0.0.1",
        port=0,
        local_handshake=make_handshake(
            "file-A",
            "peer-1",
        ),
        expected_file_id="file-A",
        expected_protocol_version="1.0",
        require_handshake=True,
    )

    peer2 = PeerNetwork(
        host="127.0.0.1",
        port=0,
        local_handshake=make_handshake(
            "file-B",
            "peer-2",
        ),
        expected_file_id="file-B",
        expected_protocol_version="1.0",
        require_handshake=True,
    )

    try:
        peer1.start()
        peer2.start()

        connection = peer1.connect(
            *peer2.address
        )

        time.sleep(0.5)

        assert not connection.handshake_complete

    finally:
        peer1.stop()
        peer2.stop()