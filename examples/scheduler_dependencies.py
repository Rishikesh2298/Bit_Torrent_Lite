import hashlib


class ManualClock:
    def __init__(self, start: float = 0.0):
        self._t = start

    def now(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


class RecordingTransport:
    def __init__(self):
        self.log: list[tuple] = []
        self.refuse = False

    def send_request(self, connection_id, request_id, piece_index):
        if self.refuse:
            return False
        self.log.append(("REQUEST", connection_id, request_id, piece_index))
        return True

    def send_interest(self, connection_id, interested):
        if self.refuse:
            return False
        self.log.append(("INTERESTED" if interested else "NOT_INTERESTED", connection_id))
        return True

    def send_have(self, connection_id, piece_index):
        if self.refuse:
            return False
        self.log.append(("HAVE", connection_id, piece_index))
        return True

    def drain(self) -> list[tuple]:
        out, self.log = self.log, []
        return out

    def send_cancel(self, connection_id, request_id, piece_index):
        if self.refuse:
            return False
        self.log.append(("CANCEL", connection_id, request_id, piece_index))
        return True


class InMemoryStore:
    def __init__(self, piece_hashes: list[bytes], piece_size: int):
        self._hashes = piece_hashes
        self._size = piece_size
        self._data: dict[int, bytes] = {}
        self.fail_io = False

    def verified_bitfield(self):
        return [i in self._data for i in range(len(self._hashes))]

    def verify_and_store(self, index, data):
        if self.fail_io:
            raise OSError("disk unavailable")
        if len(data) != self._size or hashlib.sha256(data).digest() != self._hashes[index]:
            return False
        self._data[index] = data
        return True


def make_file(num_pieces: int, piece_size: int):
    pieces = [bytes([i + 1]) * piece_size for i in range(num_pieces)]
    hashes = [hashlib.sha256(p).digest() for p in pieces]
    return pieces, hashes
