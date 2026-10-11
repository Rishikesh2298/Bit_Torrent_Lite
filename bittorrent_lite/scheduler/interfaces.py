from typing import Protocol


class Transport(Protocol):
    # each call only queues a message; True means queued, False means the queue refused it
    def send_request(self, connection_id: int, request_id: int, piece_index: int) -> bool: ...

    def send_interest(self, connection_id: int, interested: bool) -> bool: ...

    def send_have(self, connection_id: int, piece_index: int) -> bool: ...


class PieceStore(Protocol):
    # bitfield must only describe pieces that are verified and stored
    def verified_bitfield(self) -> list[bool]: ...

    # True: size/hash ok and data stored. False: invalid data. Raises OSError on local I/O trouble
    def verify_and_store(self, index: int, data: bytes) -> bool: ...


class Clock(Protocol):
    def now(self) -> float: ...
