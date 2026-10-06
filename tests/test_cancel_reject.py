import socket
import threading

from bittorrent_lite.peer.connection import PeerConnection
from bittorrent_lite.protocol.framing import send_message, recv_message
from bittorrent_lite.protocol.messages import Cancel, Reject


def test_cancel_callback():
    sock1, sock2 = socket.socketpair()

    received = []
    event = threading.Event()

    def on_cancel(message):
        received.append(message)
        event.set()

    try:
        conn = PeerConnection(
            sock1,
            callbacks={"on_cancel": on_cancel},
        )
        conn.start()

        cancel = Cancel(
            request_id=10,
            piece_index=5,
        )

        send_message(sock2, cancel)

        assert event.wait(timeout=2)
        assert len(received) == 1
        assert isinstance(received[0], Cancel)
        assert received[0].request_id == 10
        assert received[0].piece_index == 5

        conn.close()

    finally:
        try:
            sock2.close()
        except OSError:
            pass


def test_cancel_can_be_sent():
    sock1, sock2 = socket.socketpair()

    try:
        conn = PeerConnection(sock1)
        conn.start()

        cancel = Cancel(
            request_id=20,
            piece_index=7,
        )

        conn.send(cancel)

        received = recv_message(sock2)

        assert isinstance(received, Cancel)
        assert received.request_id == 20
        assert received.piece_index == 7

        conn.close()

    finally:
        try:
            sock2.close()
        except OSError:
            pass


def test_reject_callback():
    sock1, sock2 = socket.socketpair()

    received = []
    event = threading.Event()

    def on_reject(message):
        received.append(message)
        event.set()

    try:
        conn = PeerConnection(
            sock1,
            callbacks={"on_reject": on_reject},
        )
        conn.start()

        reject = Reject(
            request_id=15,
            piece_index=3,
            reason="piece unavailable",
        )

        send_message(sock2, reject)

        assert event.wait(timeout=2)
        assert len(received) == 1
        assert isinstance(received[0], Reject)
        assert received[0].request_id == 15
        assert received[0].piece_index == 3
        assert received[0].reason == "piece unavailable"

        conn.close()

    finally:
        try:
            sock2.close()
        except OSError:
            pass


def test_reject_can_be_sent():
    sock1, sock2 = socket.socketpair()

    try:
        conn = PeerConnection(sock1)
        conn.start()

        reject = Reject(
            request_id=30,
            piece_index=9,
            reason="not available",
        )

        conn.send(reject)

        received = recv_message(sock2)

        assert isinstance(received, Reject)
        assert received.request_id == 30
        assert received.piece_index == 9
        assert received.reason == "not available"

        conn.close()

    finally:
        try:
            sock2.close()
        except OSError:
            pass


def test_cancel_request_flow():
    sock1, sock2 = socket.socketpair()

    cancel_received = threading.Event()
    received_cancel = []

    def on_cancel(message):
        received_cancel.append(message)
        cancel_received.set()

    try:
        conn = PeerConnection(
            sock1,
            callbacks={"on_cancel": on_cancel},
        )
        conn.start()

        send_message(
            sock2,
            Cancel(
                request_id=100,
                piece_index=4,
            ),
        )

        assert cancel_received.wait(timeout=2)
        assert len(received_cancel) == 1
        assert received_cancel[0].request_id == 100
        assert received_cancel[0].piece_index == 4

        conn.close()

    finally:
        try:
            sock2.close()
        except OSError:
            pass


def test_reject_request_flow():
    sock1, sock2 = socket.socketpair()

    reject_received = threading.Event()
    received_reject = []

    def on_reject(message):
        received_reject.append(message)
        reject_received.set()

    try:
        conn = PeerConnection(
            sock1,
            callbacks={"on_reject": on_reject},
        )
        conn.start()

        send_message(
            sock2,
            Reject(
                request_id=200,
                piece_index=6,
                reason="choked",
            ),
        )

        assert reject_received.wait(timeout=2)
        assert len(received_reject) == 1
        assert received_reject[0].request_id == 200
        assert received_reject[0].piece_index == 6
        assert received_reject[0].reason == "choked"

        conn.close()

    finally:
        try:
            sock2.close()
        except OSError:
            pass