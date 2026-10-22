import socket
import threading
import time

from bittorrent_lite.networking.network import PeerNetwork
from bittorrent_lite.networking.connection import PeerConnection
from bittorrent_lite.networking.messages import Interested


def test_peer_network_starts_and_assigns_port():

    network = PeerNetwork(
        host="127.0.0.1",
        port=0,
    )

    try:
        network.start()

        assert network.server_socket is not None

        assert network.port > 0

        assert network.address[0] == "127.0.0.1"

        assert network.address[1] == network.port

    finally:
        network.stop()


def test_peer_network_accepts_connection():

    received = threading.Event()

    received_message = {
        "message": None
    }

    def on_interested(message):

        received_message["message"] = message

        received.set()

    network = PeerNetwork(
        host="127.0.0.1",
        port=0,
        callbacks={
            "on_interested": on_interested
        },
    )

    client = None

    try:

        network.start()

        client = socket.create_connection(
            (
                "127.0.0.1",
                network.port,
            ),
            timeout=2,
        )

        # Wait until the server accepts the connection.
        deadline = time.time() + 3

        while (
            network.connection_count == 0
            and time.time() < deadline
        ):
            time.sleep(0.01)

        assert network.connection_count == 1

        connection = network.connections[0]

        assert isinstance(
            connection,
            PeerConnection,
        )

        # Send a real protocol message through
        # the accepted TCP connection.
        from bittorrent_lite.networking.framing import send_message

        send_message(
            client,
            Interested(),
        )

        assert received.wait(
            timeout=3
        )

        assert received_message[
            "message"
        ].__class__ is Interested

    finally:

        if client is not None:

            try:
                client.shutdown(
                    socket.SHUT_RDWR
                )
            except OSError:
                pass

            try:
                client.close()
            except OSError:
                pass

        network.stop()


def test_peer_network_removes_disconnected_peer():

    network = PeerNetwork(
        host="127.0.0.1",
        port=0,
    )

    client = None

    try:

        network.start()

        client = socket.create_connection(
            (
                "127.0.0.1",
                network.port,
            ),
            timeout=2,
        )

        deadline = time.time() + 3

        while (
            network.connection_count == 0
            and time.time() < deadline
        ):
            time.sleep(0.01)

        assert network.connection_count == 1

        client.close()
        client = None

        deadline = time.time() + 3

        while (
            network.connection_count != 0
            and time.time() < deadline
        ):
            time.sleep(0.01)

        assert network.connection_count == 0

    finally:

        if client is not None:
            client.close()

        network.stop()


def test_peer_network_context_manager():

    with PeerNetwork(
        host="127.0.0.1",
        port=0,
    ) as network:

        assert network.port > 0

        assert network.server_socket is not None

    assert network.server_socket is None