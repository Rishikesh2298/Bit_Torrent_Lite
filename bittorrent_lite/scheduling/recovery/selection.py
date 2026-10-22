"""Ordering strategies. Inputs are already validated and filtered."""

from __future__ import annotations

import random
from typing import Dict, List


def order_sequential(pieces: List[int]) -> List[int]:
    return sorted(pieces)


def order_random(pieces: List[int], rng: random.Random) -> List[int]:
    result = sorted(pieces)
    rng.shuffle(result)
    return result


def order_rarest_first(pieces: List[int], availability: List[int],
                       rng: random.Random) -> List[int]:
    groups: Dict[int, List[int]] = {}
    for piece in sorted(pieces):
        groups.setdefault(availability[piece], []).append(piece)
    result: List[int] = []
    for count in sorted(groups):
        group = groups[count]
        rng.shuffle(group)
        result.extend(group)
    return result


def order_pieces(strategy: str, pieces: List[int], availability: List[int],
                 rng: random.Random) -> List[int]:
    if strategy == "sequential":
        return order_sequential(pieces)
    if strategy == "random":
        return order_random(pieces, rng)
    return order_rarest_first(pieces, availability, rng)
