"""Prabhat's socket-free piece-picker contract tests (P02/P06 subset)."""

import random

import pytest

from bittorrent_lite.piece_manager.piece_picker import PiecePicker


@pytest.fixture
def picker():
    return PiecePicker(5)


def test_new_picker_has_zero_availability(picker):
    assert picker.get_availability() == [0, 0, 0, 0, 0]


def test_availability_snapshot_cannot_mutate_picker(picker):
    snapshot = picker.get_availability()
    snapshot[0] = 99
    assert picker.get_availability() == [0, 0, 0, 0, 0]


def test_distinct_neighbor_counts_match_plan_example(picker):
    picker.update_availability("A", [1, 1, 0, 1, 0])
    picker.update_availability("B", [1, 0, 1, 0, 0])
    picker.update_availability("C", [0, 1, 1, 0, 1])
    assert picker.get_availability() == [2, 2, 2, 1, 1]


def test_duplicate_bitfield_does_not_count_neighbor_twice(picker):
    picker.update_availability("A", [1, 0, 1, 0, 0])
    picker.update_availability("A", [1, 0, 1, 0, 0])
    assert picker.get_availability() == [1, 0, 1, 0, 0]


def test_duplicate_have_is_idempotent(picker):
    picker.update_availability("A", [0, 0, 0, 0, 0])
    picker.peer_has_piece("A", 3)
    picker.peer_has_piece("A", 3)
    assert picker.get_availability() == [0, 0, 0, 1, 0]


def test_repeated_disconnect_preserves_other_neighbors(picker):
    bits = [1, 0, 1, 0, 0]
    picker.update_availability("A", bits)
    picker.update_availability("B", [1, 1, 0, 0, 0])
    picker.peer_disconnected("A", bits)
    picker.peer_disconnected("A", bits)
    assert picker.get_availability() == [1, 1, 0, 0, 0]


def test_unique_rarest_piece_is_selected(picker):
    picker.update_availability("A", [1, 1, 0, 1, 0])
    picker.update_availability("B", [1, 1, 0, 0, 0])
    assert picker.pick_piece([0] * 5, [1, 1, 0, 1, 0], set()) == 3


def test_owned_reserved_and_source_unavailable_pieces_are_excluded(picker):
    picker.update_availability("A", [1, 1, 1, 0, 0])
    picker.update_availability("B", [0, 0, 0, 1, 0])
    # 0 is owned, 1 is reserved, 3 belongs only to another source.
    assert picker.pick_piece([1, 0, 0, 0, 0], [1, 1, 1, 0, 0], {1}) == 2


@pytest.mark.parametrize(
    "owned,remote,reserved",
    [([1] * 5, [1] * 5, set()),
     ([0] * 5, [0] * 5, set()),
     ([0] * 5, [1, 0, 0, 0, 0], {0})],
    ids=["all-owned", "no-source-pieces", "only-piece-reserved"],
)
def test_no_eligible_piece_returns_none(picker, owned, remote, reserved):
    picker.update_availability("A", remote)
    assert picker.pick_piece(owned, remote, reserved) is None


def test_replacement_bitfield_removes_old_advertisements(picker):
    picker.update_availability("A", [1, 0, 1, 0, 0])
    picker.update_availability("A", [0, 1, 0, 0, 0])
    assert picker.get_availability() == [0, 1, 0, 0, 0]


def test_neighbor_snapshot_is_independent_of_callers_list(picker):
    bits = [1, 0, 0, 0, 0]
    picker.update_availability("A", bits)
    bits[1] = 1
    picker.peer_has_piece("A", 2)
    assert picker.get_availability() == [1, 0, 1, 0, 0]


def test_disconnect_uses_snapshot_including_later_have(picker):
    original = [1, 0, 0, 0, 0]
    picker.update_availability("A", original)
    picker.peer_has_piece("A", 2)
    picker.peer_disconnected("A", original)
    assert picker.get_availability() == [0] * 5


def test_seeded_ties_are_repeatable_and_only_choose_rarest(picker, monkeypatch):
    picker.update_availability("A", [1, 1, 0, 1, 1])
    picker.update_availability("B", [1, 1, 0, 0, 0])

    def selections(seed):
        monkeypatch.setattr(
            "bittorrent_lite.piece_manager.piece_picker.random.choice",
            random.Random(seed).choice,
        )
        return [picker.pick_piece([0] * 5, [1, 1, 0, 1, 1]) for _ in range(20)]

    first = selections(42)
    assert first == selections(42)
    assert set(first) == {3, 4}


@pytest.mark.parametrize("bits", [[1], [0, 0, 2, 0, 0], [0, 0, "1", 0, 0]])
def test_invalid_bitfield_leaves_counts_unchanged(picker, bits):
    picker.update_availability("A", [1, 0, 0, 0, 0])
    with pytest.raises(ValueError):
        picker.update_availability("A", bits)
    assert picker.get_availability() == [1, 0, 0, 0, 0]


@pytest.mark.parametrize("index", [-1, 5, True])
def test_invalid_have_index_leaves_counts_unchanged(picker, index):
    picker.update_availability("A", [0] * 5)
    with pytest.raises(ValueError):
        picker.peer_has_piece("A", index)
    assert picker.get_availability() == [0] * 5


def test_have_requires_initial_neighbor_snapshot(picker):
    with pytest.raises(ValueError):
        picker.peer_has_piece("unknown", 0)
    assert picker.get_availability() == [0] * 5
