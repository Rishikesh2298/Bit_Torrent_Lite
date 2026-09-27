from typing import Generator
from bittorrent_lite.config import PIECE_SIZE

def split_file(file_path: str,piece_size: int = PIECE_SIZE) -> Generator[tuple[int, bytes], None, None]:

    if piece_size <= 0:
        raise ValueError("piece_size must be greater than zero")

    with open(file_path, "rb") as file:
        index = 0
        data = file.read(piece_size)

        if data == b"":
            raise ValueError("cannot split an empty file")

        while data != b"":
            yield index, data

            index += 1
            data = file.read(piece_size)