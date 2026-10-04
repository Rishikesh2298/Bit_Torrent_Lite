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

    if type(file_size) is not int or file_size < 0:
        raise ValueError("file_size must be a nonnegative integer")

    if type(piece_size) is not int or piece_size <= 0:
        raise ValueError("piece_size must be a positive integer")

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

    if type(piece_size) is not int or piece_size <= 0:
        raise ValueError("piece_size must be a positive integer")

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

    validate_metadata(metadata, "0" * 64)

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

    required = {"format_version", "filename", "file_size", "piece_size",
                "piece_hashes", "file_sha256"}
    if not isinstance(data, dict) or not required.issubset(data):
        raise ValueError("metadata must be an object with all required fields")

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

    if type(metadata.piece_size) is not int or metadata.piece_size <= 0:
        raise ValueError("piece_size must be a positive integer")

    if type(metadata.file_size) is not int or metadata.file_size <= 0:
        raise ValueError("file_size must be a positive integer")

    if metadata.file_size > MAX_FILE_SIZE:
        raise ValueError("file exceeds maximum allowed size")

    if (type(metadata.format_version) is not int
            or metadata.format_version != PROTOCOL_VERSION):
        raise ValueError("unsupported metadata format version")

    if not isinstance(metadata.piece_hashes, list):
        raise ValueError("piece_hashes must be a list")

    expected_num_pieces = calc_num_pieces(
        metadata.file_size,
        metadata.piece_size
    )

    if metadata.num_pieces != expected_num_pieces:
        raise ValueError("piece count does not match file size")

    if not isinstance(metadata.filename, str):
        raise ValueError("filename must be a string")

    if metadata.filename == "":
        raise ValueError("filename cannot be empty")

    for digest in [metadata.file_sha256, file_id, *metadata.piece_hashes]:
        if (not isinstance(digest, str) or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)):
            raise ValueError("hashes must be 64 lowercase hexadecimal characters")
