from bittorrent_lite.common.config import PROTOCOL_VERSION
import time

from bittorrent_lite.networking.network import PeerNetwork
from bittorrent_lite.networking.session import Handshake


def wait_until(condition, timeout=2.0, interval=0.01):
    deadline = time.time() + timeout

    while time.time() < deadline:
        if condition():
            return True
        time.sleep(interval)

    return False


def make_handshake(file_id, peer_id):
    return Handshake(
        protocol_version=PROTOCOL_VERSION,
        file_id=file_id,
        peer_id=peer_id,
    )


def test_bitfield_is_exchanged_after_handshake():

    file_id = "file-bitfield"

    peer1 = PeerNetwork(
        host="127.0.0.1",
        port=0,
        local_handshake=make_handshake(
            file_id,
            "peer-1",
        ),
        expected_file_id=file_id,
        expected_protocol_version=PROTOCOL_VERSION,
        require_handshake=True,
        local_bitfield=[
            1,
            0,
            1,
            0,
        ],
    )

    peer2 = PeerNetwork(
        host="127.0.0.1",
        port=0,
        local_handshake=make_handshake(
            file_id,
            "peer-2",
        ),
        expected_file_id=file_id,
        expected_protocol_version=PROTOCOL_VERSION,
        require_handshake=True,
        local_bitfield=[
            0,
            1,
            0,
            1,
        ],
    )

    try:

        peer1.start()
        peer2.start()

        connection = peer1.connect(
            *peer2.address
        )

        assert wait_until(
            lambda: connection.handshake_complete
        )

        assert wait_until(
            lambda: connection.bitfield_sent
        )

        assert wait_until(
            lambda:
            len(peer2.connections) >= 1
        )

        remote_connection = peer2.connections[0]

        assert wait_until(
            lambda:
            remote_connection.bitfield_received
        )

        assert remote_connection.remote_bitfield == [
            1,
            0,
            1,
            0,
        ]

    finally:

        peer1.stop()
        peer2.stop()


def test_have_updates_remote_bitfield():

    file_id = "file-have"

    peer1 = PeerNetwork(
        host="127.0.0.1",
        port=0,
        local_handshake=make_handshake(
            file_id,
            "peer-1",
        ),
        expected_file_id=file_id,
        expected_protocol_version=PROTOCOL_VERSION,
        require_handshake=True,
        local_bitfield=[
            1,
            0,
            0,
        ],
    )

    peer2 = PeerNetwork(
        host="127.0.0.1",
        port=0,
        local_handshake=make_handshake(
            file_id,
            "peer-2",
        ),
        expected_file_id=file_id,
        expected_protocol_version=PROTOCOL_VERSION,
        require_handshake=True,
        local_bitfield=[
            0,
            0,
            0,
        ],
    )

    try:

        peer1.start()
        peer2.start()

        connection = peer1.connect(
            *peer2.address
        )

        assert wait_until(
            lambda:
            connection.handshake_complete
        )

        assert wait_until(
            lambda:
            connection.bitfield_sent
        )

        # Wait until the incoming connection has been
        # registered by peer2.
        assert wait_until(
            lambda:
            len(peer2.connections) >= 1
        )

        remote_connection = peer2.connections[0]

        assert wait_until(
            lambda:
            remote_connection.bitfield_received
        )

        assert remote_connection.remote_bitfield == [
            1,
            0,
            0,
        ]

        # Peer 1 announces that it now has piece 1.
        connection.send_have(1)

        assert wait_until(
            lambda:
            remote_connection.remote_bitfield == [
                1,
                1,
                0,
            ]
        )

        assert remote_connection.remote_bitfield == [
            1,
            1,
            0,
        ]

    finally:

        peer1.stop()
        peer2.stop()


def test_have_round_trip():

    file_id = "file-have-round-trip"

    peer1 = PeerNetwork(
        host="127.0.0.1",
        port=0,
        local_handshake=make_handshake(
            file_id,
            "peer-1",
        ),
        expected_file_id=file_id,
        expected_protocol_version=PROTOCOL_VERSION,
        require_handshake=True,
        local_bitfield=[
            0,
            0,
            0,
        ],
    )

    peer2 = PeerNetwork(
        host="127.0.0.1",
        port=0,
        local_handshake=make_handshake(
            file_id,
            "peer-2",
        ),
        expected_file_id=file_id,
        expected_protocol_version=PROTOCOL_VERSION,
        require_handshake=True,
        local_bitfield=[
            0,
            0,
            0,
        ],
    )

    try:

        peer1.start()
        peer2.start()

        connection = peer1.connect(
            *peer2.address
        )

        assert wait_until(
            lambda:
            connection.handshake_complete
        )

        assert wait_until(
            lambda:
            len(peer2.connections) >= 1
        )

        remote_connection = peer2.connections[0]

        assert wait_until(
            lambda:
            remote_connection.handshake_complete
        )

        connection.send_have(2)

        assert wait_until(
            lambda:
            remote_connection.remote_bitfield == [
                0,
                0,
                1,
            ]
        )

        assert remote_connection.remote_bitfield == [
            0,
            0,
            1,
        ]

    finally:

        peer1.stop()
        peer2.stop()