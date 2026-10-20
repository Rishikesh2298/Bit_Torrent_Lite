import socket
import time

from bittorrent_lite.peer.connection import (
    PeerConnection,
)
from bittorrent_lite.protocol.messages import (
    Choke,
    Interested,
    Request,
    Unchoke,
)


def make_pair():
    left, right = socket.socketpair()

    left_conn = PeerConnection(
        left,
        peer_id="peer-right",
    )

    right_conn = PeerConnection(
        right,
        peer_id="peer-left",
    )

    return left_conn, right_conn


def test_send_unchoke_updates_local_state():
    left, right = make_pair()

    assert left.local_choking

    left.send_unchoke()

    assert not left.local_choking

    left.close()
    right.close()


def test_send_choke_updates_local_state():
    left, right = make_pair()

    left.send_unchoke()
    assert not left.local_choking

    left.send_choke()

    assert left.local_choking

    left.close()
    right.close()


def test_remote_unchoke_is_received():
    left, right = make_pair()

    right.start()

    left.send_unchoke()

    deadline = time.time() + 1.0

    while (
        right.remote_choked
        and time.time() < deadline
    ):
        time.sleep(0.01)

    assert not right.remote_choked

    left.close()
    right.close()


def test_remote_choke_is_received():
    left, right = make_pair()

    right.start()

    left.send_unchoke()

    deadline = time.time() + 1.0

    while (
        right.remote_choked
        and time.time() < deadline
    ):
        time.sleep(0.01)

    assert not right.remote_choked

    left.send_choke()

    deadline = time.time() + 1.0

    while (
        not right.remote_choked
        and time.time() < deadline
    ):
        time.sleep(0.01)

    assert right.remote_choked

    left.close()
    right.close()


def test_choked_peer_cannot_send_request():
    left, right = make_pair()

    # left initially considers right to be choking it.
    assert left.remote_choked

    request = left.send_request(0)

    assert request is None

    left.close()
    right.close()


def test_unchoked_peer_can_create_request():
    left, right = make_pair()

    left._remote_choked = False

    request = left.send_request(0)

    assert request is not None
    assert request.piece_index == 0

    left.close()
    right.close()


def test_interested_message_is_received():
    received = []

    left, right = make_pair()

    right.callbacks["on_interested"] = (
        lambda connection, message:
        received.append(message)
    )

    right.start()

    left.send_interested()

    deadline = time.time() + 1.0

    while (
        not received
        and time.time() < deadline
    ):
        time.sleep(0.01)

    assert len(received) == 1
    assert isinstance(
        received[0],
        Interested,
    )

    left.close()
    right.close()


def test_choke_message_callback():
    received = []

    left, right = make_pair()

    right.callbacks["on_choke"] = (
        lambda connection, message:
        received.append(message)
    )

    right.start()

    left.send_choke()

    deadline = time.time() + 1.0

    while (
        not received
        and time.time() < deadline
    ):
        time.sleep(0.01)

    assert len(received) == 1
    assert isinstance(
        received[0],
        Choke,
    )

    left.close()
    right.close()


def test_unchoke_message_callback():
    received = []

    left, right = make_pair()

    right.callbacks["on_unchoke"] = (
        lambda connection, message:
        received.append(message)
    )

    right.start()

    left.send_unchoke()

    deadline = time.time() + 1.0

    while (
        not received
        and time.time() < deadline
    ):
        time.sleep(0.01)

    assert len(received) == 1
    assert isinstance(
        received[0],
        Unchoke,
    )

    left.close()
    right.close()