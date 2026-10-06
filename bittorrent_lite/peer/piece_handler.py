from __future__ import annotations

from bittorrent_lite.file_store import FileStore
from bittorrent_lite.protocol.messages import (
    Piece,
    Reject,
)


class PieceHandler:
    """
    Connects incoming REQUEST messages to FileStore.

    When a peer requests a piece:
        REQUEST
           ↓
        FileStore.read_piece()
           ↓
        PIECE

    If the requested piece cannot be served:
        REQUEST
           ↓
        REJECT
    """

    def __init__(self, file_store):
        if not isinstance(file_store, FileStore):
            raise TypeError("file_store must be a FileStore instance")

        self.file_store = file_store

    def handle_request(self, request):
        """
        Handle a Request message and return either Piece or Reject.
        """

        piece_index = request.piece_index
        request_id = request.request_id

        try:
            data = self.file_store.read_piece(piece_index)

            return Piece(
                request_id=request_id,
                piece_index=piece_index,
                _payload=data,
            )

        except (IndexError, ValueError) as exc:
            return Reject(
                request_id=request_id,
                piece_index=piece_index,
                reason=str(exc),
            )

        except OSError as exc:
            return Reject(
                request_id=request_id,
                piece_index=piece_index,
                reason=f"file read error: {exc}",
            )

    def handle_piece(self, piece):
        """
        Write a received PIECE message into the local FileStore.

        Returns True when successfully written.
        """

        self.file_store.write_piece(
            piece.piece_index,
            piece.payload,
        )

        return True