import random
from typing import AbstractSet, Optional, Sequence


class PiecePicker:
    def __init__(self, num_pieces: int, rng: Optional[random.Random] = None):
        if type(num_pieces) is not int or num_pieces < 0:
            raise ValueError("num_pieces must be a nonnegative integer")
        self._n = num_pieces
        self._rng = rng or random.Random()
        self._bitfields: dict[int, list[bool]] = {}
        self._counts = [0] * num_pieces

    def update_bitfield(self, connection_id: int, bitfield: Sequence[bool]) -> None:
        self.validate_bitfield(bitfield)
        self.remove_connection(connection_id)
        copy = [bool(b) for b in bitfield]
        self._bitfields[connection_id] = copy
        for i, has in enumerate(copy):
            if has:
                self._counts[i] += 1

    def record_have(self, connection_id: int, piece_index: int) -> None:
        if type(piece_index) is not int or not 0 <= piece_index < self._n:
            raise ValueError(f"piece index {piece_index} out of range")
        bf = self._bitfields.get(connection_id)
        if bf is None:
            bf = [False] * self._n
            self._bitfields[connection_id] = bf
        if not bf[piece_index]:
            bf[piece_index] = True
            self._counts[piece_index] += 1

    def remove_connection(self, connection_id: int) -> None:
        bf = self._bitfields.pop(connection_id, None)
        if bf is None:
            return
        for i, has in enumerate(bf):
            if has:
                self._counts[i] -= 1

    def pick_piece(
        self,
        local_bitfield: Sequence[bool],
        source_bitfield: Sequence[bool],
        reserved_pieces: AbstractSet[int],
    ) -> Optional[int]:
        self.validate_bitfield(local_bitfield)
        self.validate_bitfield(source_bitfield)
        candidates = [
            i
            for i in range(self._n)
            if not local_bitfield[i] and i not in reserved_pieces and source_bitfield[i]
            and self._counts[i] > 0
        ]
        if not candidates:
            return None
        rarest = min(self._counts[i] for i in candidates)
        return self._rng.choice([i for i in candidates if self._counts[i] == rarest])

    def availability_snapshot(self) -> list[int]:
        return list(self._counts)

    def candidate_order(self, local_bitfield, source_bitfield) -> list[int]:
        """Rarest first, with randomized ties, for the pipeline's fair fill."""
        self.validate_bitfield(local_bitfield)
        self.validate_bitfield(source_bitfield)
        candidates = [i for i in range(self._n)
                      if source_bitfield[i] and not local_bitfield[i]
                      and self._counts[i] > 0]
        self._rng.shuffle(candidates)
        candidates.sort(key=self._counts.__getitem__)
        return candidates

    def validate_bitfield(self, bitfield: Sequence[bool]) -> None:
        if len(bitfield) != self._n or any(
            type(b) not in (bool, int) or b not in (0, 1) for b in bitfield
        ):
            raise ValueError("bitfield must contain one zero/one entry per piece")
