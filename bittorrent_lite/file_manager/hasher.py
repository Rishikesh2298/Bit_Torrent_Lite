import hashlib

from bittorrent_lite.config import HASH_ALGORITHM, PIECE_SIZE



def hash_piece(data: bytes) -> str:

    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")

    hasher = hashlib.new(HASH_ALGORITHM)
    hasher.update(data)

    return hasher.hexdigest()


def verify_piece(data: bytes, expected_hash: str) -> bool:

    if not isinstance(data, bytes):
        return False

    if not isinstance(expected_hash, str):
        return False

    actual_hash = hash_piece(data)

    return actual_hash == expected_hash.lower()


def hash_file(file_path: str) -> str:

    hasher = hashlib.new(HASH_ALGORITHM)

    with open(file_path, "rb") as file:
        while True:
            chunk = file.read(PIECE_SIZE)

            if chunk == b"":
                break

            hasher.update(chunk)

    return hasher.hexdigest()