import socket
import threading

from bittorrent_lite.file_store import FileStore
from bittorrent_lite.peer.connection import PeerConnection
from bittorrent_lite.peer.piece_handler import PieceHandler
from bittorrent_lite.protocol.messages import (
    Request,
    Piece,
    Reject,
)


def test_request_is_served_as_piece_over_connection(tmp_path):
    """
    Test complete flow:

        Peer A
          |
          | REQUEST
          v
        Peer B
          |
          | PieceHandler reads file
          |
          | PIECE
          v
        Peer A

    The received piece must be written to the destination file.
    """

    source_file = tmp_path / "source.bin"
    destination_file = tmp_path / "destination.bin"

    source_data = (
        b"BitTorrent-Lite networking test data. "
        b"This piece is transferred between two peers."
    )

    source_file.write_bytes(source_data)

    # Destination file must already have the expected size.
    destination_file.write_bytes(
        b"\x00" * len(source_data)
    )

    source_store = FileStore(
        source_file,
        piece_size=64 * 1024,
    )

    destination_store = FileStore(
        destination_file,
        piece_size=64 * 1024,
    )

    source_handler = PieceHandler(
        source_store
    )

    destination_handler = PieceHandler(
        destination_store
    )

    sock1, sock2 = socket.socketpair()

    peer1 = PeerConnection(
        sock1,
        piece_handler=destination_handler,
    )

    peer2 = PeerConnection(
        sock2,
        piece_handler=source_handler,
    )

    try:
        peer1.start()
        peer2.start()

        request = Request(
            request_id=1,
            piece_index=0,
        )

        peer1.send(request)

        # Wait until destination receives the piece.
        received_event = threading.Event()

        original_handler = destination_handler.handle_piece

        def handle_piece_and_signal(piece):
            result = original_handler(piece)
            received_event.set()
            return result

        destination_handler.handle_piece = (
            handle_piece_and_signal
        )

        # Send another request so that the wrapped handler
        # can observe the response.
        request = Request(
            request_id=2,
            piece_index=0,
        )

        peer1.send(request)

        assert received_event.wait(
            timeout=3
        ), "Timed out waiting for PIECE"

        assert (
            destination_store.read_piece(0)
            == source_data
        )

    finally:
        peer1.close()
        peer2.close()


def test_invalid_piece_request_returns_reject(tmp_path):

    source_file = tmp_path / "source.bin"

    source_file.write_bytes(
        b"small test file"
    )

    source_store = FileStore(
        source_file,
        piece_size=64 * 1024,
    )

    source_handler = PieceHandler(
        source_store
    )

    sock1, sock2 = socket.socketpair()

    received = {
        "message": None
    }

    event = threading.Event()

    def on_message(message):

        received["message"] = message
        event.set()

    peer1 = PeerConnection(
        sock1,
        callbacks={
            "on_reject": on_message
        },
    )

    peer2 = PeerConnection(
        sock2,
        piece_handler=source_handler,
    )

    try:
        peer1.start()
        peer2.start()

        invalid_request = Request(
            request_id=100,
            piece_index=999,
        )

        peer1.send(invalid_request)

        assert event.wait(
            timeout=3
        ), "Timed out waiting for REJECT"

        assert isinstance(
            received["message"],
            Reject,
        )

        assert (
            received["message"].request_id
            == 100
        )

        assert (
            received["message"].piece_index
            == 999
        )

    finally:
        peer1.close()
        peer2.close()


def test_piece_received_callback_is_called(tmp_path):

    source_file = tmp_path / "source.bin"

    source_data = b"callback test data"

    source_file.write_bytes(
        source_data
    )

    source_store = FileStore(
        source_file,
        piece_size=64 * 1024,
    )

    source_handler = PieceHandler(
        source_store
    )

    sock1, sock2 = socket.socketpair()

    received = {
        "piece": None
    }

    event = threading.Event()

    def on_piece(piece):

        received["piece"] = piece
        event.set()

    peer1 = PeerConnection(
        sock1,
        callbacks={
            "on_piece": on_piece
        },
    )

    peer2 = PeerConnection(
        sock2,
        piece_handler=source_handler,
    )

    try:
        peer1.start()
        peer2.start()

        request = Request(
            request_id=55,
            piece_index=0,
        )

        peer1.send(request)

        assert event.wait(
            timeout=3
        ), "Timed out waiting for PIECE"

        assert isinstance(
            received["piece"],
            Piece,
        )

        assert (
            received["piece"].request_id
            == 55
        )

        assert (
            received["piece"].piece_index
            == 0
        )

        assert (
            received["piece"].payload
            == source_data
        )

    finally:
        peer1.close()
        peer2.close()