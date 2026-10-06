from bittorrent_lite.file_store import FileStore
from bittorrent_lite.peer.piece_handler import PieceHandler
from bittorrent_lite.protocol.messages import (
    Request,
    Piece,
    Reject,
)


def test_request_returns_real_piece(tmp_path):
    file_path = tmp_path / "source.bin"

    data = b"abcdefghijklmnop"

    file_path.write_bytes(data)

    store = FileStore(
        file_path,
        piece_size=4,
    )

    handler = PieceHandler(store)

    request = Request(
        request_id=101,
        piece_index=1,
    )

    response = handler.handle_request(request)

    assert isinstance(response, Piece)
    assert response.request_id == 101
    assert response.piece_index == 1
    assert response.payload == b"efgh"


def test_request_returns_final_piece(tmp_path):
    file_path = tmp_path / "source.bin"

    data = b"abcdefghij"

    file_path.write_bytes(data)

    store = FileStore(
        file_path,
        piece_size=4,
    )

    handler = PieceHandler(store)

    request = Request(
        request_id=102,
        piece_index=2,
    )

    response = handler.handle_request(request)

    assert isinstance(response, Piece)
    assert response.request_id == 102
    assert response.piece_index == 2
    assert response.payload == b"ij"


def test_invalid_request_returns_reject(tmp_path):
    file_path = tmp_path / "source.bin"

    file_path.write_bytes(b"abcdefgh")

    store = FileStore(
        file_path,
        piece_size=4,
    )

    handler = PieceHandler(store)

    request = Request(
        request_id=200,
        piece_index=99,
    )

    response = handler.handle_request(request)

    assert isinstance(response, Reject)
    assert response.request_id == 200
    assert response.piece_index == 99
    assert response.reason


def test_received_piece_is_written(tmp_path):
    source_path = tmp_path / "source.bin"
    destination_path = tmp_path / "destination.bin"

    source_data = b"abcdefghijklmnop"

    source_path.write_bytes(source_data)
    destination_path.write_bytes(b"\x00" * len(source_data))

    source_store = FileStore(
        source_path,
        piece_size=4,
    )

    destination_store = FileStore(
        destination_path,
        piece_size=4,
    )

    source_handler = PieceHandler(source_store)
    destination_handler = PieceHandler(destination_store)

    request = Request(
        request_id=300,
        piece_index=2,
    )

    piece = source_handler.handle_request(request)

    assert isinstance(piece, Piece)

    result = destination_handler.handle_piece(piece)

    assert result is True
    assert destination_store.read_piece(2) == b"ijkl"


def test_multiple_pieces_can_be_transferred(tmp_path):
    source_path = tmp_path / "source.bin"
    destination_path = tmp_path / "destination.bin"

    source_data = b"abcdefghijklmnopqrst"

    source_path.write_bytes(source_data)
    destination_path.write_bytes(b"\x00" * len(source_data))

    source_store = FileStore(
        source_path,
        piece_size=5,
    )

    destination_store = FileStore(
        destination_path,
        piece_size=5,
    )

    source_handler = PieceHandler(source_store)
    destination_handler = PieceHandler(destination_store)

    for piece_index in range(source_store.piece_count):
        request = Request(
            request_id=1000 + piece_index,
            piece_index=piece_index,
        )

        piece = source_handler.handle_request(request)

        assert isinstance(piece, Piece)

        destination_handler.handle_piece(piece)

    assert destination_path.read_bytes() == source_data