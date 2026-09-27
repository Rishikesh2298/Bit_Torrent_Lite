import hashlib
import json
from pathlib import Path

from bittorrent_lite.types import TorrentMetadata
from bittorrent_lite.config import (
    PIECE_SIZE,
    PROTOCOL_VERSION,
    MAX_FILE_SIZE,
    HASH_ALGORITHM
)

from bittorrent_lite.file_manager.hasher import hash_file, hash_piece
from bittorrent_lite.file_manager.splitter import split_file


def calc_num_pieces(file_size: int, piece_size: int) -> int:

    if file_size < 0:
        raise ValueError("file_size cannot be negative")

    if piece_size <= 0:
        raise ValueError("piece_size must be greater than zero")

    return (file_size + piece_size - 1) // piece_size


def create_metadata(
    file_path: str,
    piece_size: int = PIECE_SIZE
) -> TorrentMetadata:

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(file_path)

    if not path.is_file():
        raise ValueError("source path is not a file")

    if piece_size <= 0:
        raise ValueError("piece_size must be greater than zero")

    file_size = path.stat().st_size

    if file_size == 0:
        raise ValueError("cannot create metadata for an empty file")

    if file_size > MAX_FILE_SIZE:
        raise ValueError("file exceeds maximum allowed size")

    piece_hashes = []

    for index, data in split_file(str(path), piece_size):
        piece_hashes.append(hash_piece(data))

    file_sha256 = hash_file(str(path))

    return TorrentMetadata(
        format_version=PROTOCOL_VERSION,
        filename=path.name,
        file_size=file_size,
        piece_size=piece_size,
        piece_hashes=piece_hashes,
        file_sha256=file_sha256
    )


def save_metadata(
    metadata: TorrentMetadata,
    output_path: str
) -> None:

    data = {
        "file_sha256": metadata.file_sha256,
        "file_size": metadata.file_size,
        "filename": metadata.filename,
        "format_version": metadata.format_version,
        "piece_hashes": metadata.piece_hashes,
        "piece_size": metadata.piece_size
    }

    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            sort_keys=True,
            separators=(",", ":")
        )


def load_metadata(
    metadata_path: str
) -> tuple[TorrentMetadata, str]:

    path = Path(metadata_path)

    if not path.exists():
        raise FileNotFoundError(metadata_path)

    with open(path, "rb") as file:
        raw_data = file.read()

    hasher = hashlib.new(HASH_ALGORITHM)
    hasher.update(raw_data)

    file_id = hasher.hexdigest()

    data = json.loads(raw_data.decode("utf-8"))

    metadata = TorrentMetadata(
        format_version=data["format_version"],
        filename=data["filename"],
        file_size=data["file_size"],
        piece_size=data["piece_size"],
        piece_hashes=data["piece_hashes"],
        file_sha256=data["file_sha256"]
    )

    validate_metadata(metadata, file_id)

    return metadata, file_id


def validate_metadata(
    metadata: TorrentMetadata,
    file_id: str
) -> None:

    if metadata.piece_size <= 0:
        raise ValueError("piece_size must be greater than zero")

    if metadata.file_size <= 0:
        raise ValueError("file_size must be greater than zero")

    if metadata.file_size > MAX_FILE_SIZE:
        raise ValueError("file exceeds maximum allowed size")

    if metadata.format_version != PROTOCOL_VERSION:
        raise ValueError("unsupported metadata format version")

    expected_num_pieces = calc_num_pieces(
        metadata.file_size,
        metadata.piece_size
    )

    if metadata.num_pieces != expected_num_pieces:
        raise ValueError("piece count does not match file size")

    if len(metadata.piece_hashes) != metadata.num_pieces:
        raise ValueError(
            "piece hash count does not match piece count"
        )

    if not isinstance(metadata.filename, str):
        raise ValueError("filename must be a string")

    if metadata.filename == "":
        raise ValueError("filename cannot be empty")

    if not isinstance(metadata.file_sha256, str):
        raise ValueError("file_sha256 must be a string")

    if len(metadata.file_sha256) != 64:
        raise ValueError("invalid file_sha256")

    if not isinstance(file_id, str):
        raise ValueError("file_id must be a string")

    if len(file_id) != 64:
        raise ValueError("invalid file_id")

    for piece_hash in metadata.piece_hashes:

        if not isinstance(piece_hash, str):
            raise ValueError("piece hash must be a string")

        if len(piece_hash) != 64:
            raise ValueError("invalid piece hash")