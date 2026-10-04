from pathlib import Path
from tempfile import NamedTemporaryFile

from bittorrent_lite.types import TorrentMetadata
from bittorrent_lite.config import DEFAULT_PIECES_DIR

from bittorrent_lite.file_manager.hasher import (
    hash_file,
    verify_piece
)


class FileStore:

    def __init__(
        self,
        metadata: TorrentMetadata,
        file_id: str,
        pieces_dir: str = DEFAULT_PIECES_DIR,
        source_path: str | None = None
    ):

        self.metadata = metadata
        self.file_id = file_id
        self.pieces_dir = Path(pieces_dir) / self.file_id
        self.source_path = Path(source_path) if source_path else None

        self._bitfield: list[int] = [0] * metadata.num_pieces
        self._lock = None

        if self.source_path is None:
            self.pieces_dir.mkdir(
                parents=True,
                exist_ok=True
            )

    def _validate_index(self, index: int) -> None:

        if not isinstance(index, int) or isinstance(index, bool):
            raise IndexError("piece index must be an integer")

        if index < 0 or index >= self.metadata.num_pieces:
            raise IndexError("piece index out of range")

    def _piece_path(self, index: int) -> Path:

        return self.pieces_dir / f"{index}.piece"

    def read_piece(self, index: int) -> bytes:

        self._validate_index(index)

        if self.source_path is not None:

            offset = index * self.metadata.piece_size

            with open(self.source_path, "rb") as file:
                file.seek(offset)
                data = file.read(
                    self.metadata.expected_piece_size(index)
                )

            if len(data) != self.metadata.expected_piece_size(index):
                self._bitfield[index] = 0
                raise FileNotFoundError(
                    f"piece {index} is not available"
                )

            if not verify_piece(data, self.metadata.piece_hashes[index]):
                self._bitfield[index] = 0
                raise ValueError(f"piece {index} failed hash verification")
            return data

        piece_path = self._piece_path(index)

        if not piece_path.exists():
            self._bitfield[index] = 0
            raise FileNotFoundError(
                f"piece {index} is not available"
            )

        with open(piece_path, "rb") as file:
            data = file.read()

        if (len(data) != self.metadata.expected_piece_size(index)
                or not verify_piece(data, self.metadata.piece_hashes[index])):
            self._bitfield[index] = 0
            raise ValueError(
                f"piece {index} failed hash verification"
            )

        return data

    def verify_and_store(
        self,
        index: int,
        data: bytes
    ) -> bool:

        self._validate_index(index)

        if not isinstance(data, bytes):
            return False

        expected_size = self.metadata.expected_piece_size(index)

        if len(data) != expected_size:
            return False

        expected_hash = self.metadata.piece_hashes[index]

        if not verify_piece(data, expected_hash):
            return False

        self.pieces_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        piece_path = self._piece_path(index)

        temporary = None
        try:
            with NamedTemporaryFile(dir=self.pieces_dir, suffix=".tmp", delete=False) as file:
                temporary = Path(file.name)
                file.write(data)
            temporary.replace(piece_path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

        self._bitfield[index] = 1

        return True

    def has_piece(self, index: int) -> bool:

        self._validate_index(index)

        if self.source_path is not None and not self._bitfield[index]:
            return False
        try:
            self.read_piece(index)
        except (FileNotFoundError, ValueError):
            self._bitfield[index] = 0
            return False

        self._bitfield[index] = 1

        return True

    def get_bitfield(self) -> list[int]:

        return self._bitfield.copy()

    def assemble_file(
        self,
        output_path: str
    ) -> bool:

        for index in range(self.metadata.num_pieces):

            if not self.has_piece(index):
                return False

        output = Path(output_path)
        if any(output.resolve() == self._piece_path(index).resolve()
               for index in range(self.metadata.num_pieces)):
            raise ValueError("output must not overwrite a stored piece")

        temporary = None
        try:
            with NamedTemporaryFile(dir=output.parent, suffix=".tmp", delete=False) as file:
                temporary = Path(file.name)
                for index in range(self.metadata.num_pieces):
                    file.write(self.read_piece(index))
            if (temporary.stat().st_size != self.metadata.file_size
                    or hash_file(str(temporary)) != self.metadata.file_sha256):
                return False
            temporary.replace(output)
            return True
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def validate_source(self) -> None:

        self._bitfield = [0] * self.metadata.num_pieces

        if self.source_path is None:
            raise ValueError(
                "source_path is required for validation"
            )

        if not self.source_path.exists():
            raise FileNotFoundError(
                str(self.source_path)
            )

        if not self.source_path.is_file():
            raise ValueError(
                "source_path is not a file"
            )

        actual_file_hash = hash_file(
            str(self.source_path)
        )

        if actual_file_hash != self.metadata.file_sha256:
            raise ValueError(
                "source file hash does not match metadata"
            )

        for index in range(self.metadata.num_pieces):
            self.read_piece(index)

        self._bitfield = [1] * self.metadata.num_pieces
