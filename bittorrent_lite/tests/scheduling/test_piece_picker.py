import pytest

from bittorrent_lite.scheduling.legacy.piece_picker import PiecePicker


def test_rarest_piece_is_selected_first():
    picker = PiecePicker(piece_count=5)

    picker.update_peer("peer1", [0, 1, 2])
    picker.update_peer("peer2", [0, 1])
    picker.update_peer("peer3", [0])

    assert picker.availability(0) == 3
    assert picker.availability(1) == 2
    assert picker.availability(2) == 1

    assert picker.pick_piece() == 2


def test_piece_with_zero_availability_is_not_selected():
    picker = PiecePicker(piece_count=4)

    picker.update_peer("peer1", [0, 1])

    first = picker.pick_piece()
    second = picker.pick_piece()
    third = picker.pick_piece()

    assert first in [0, 1]
    assert second in [0, 1]
    assert first != second
    assert third is None


def test_local_piece_is_not_selected():
    picker = PiecePicker(
        piece_count=4,
        local_pieces=[1],
    )

    picker.update_peer(
        "peer1",
        [0, 1, 2, 3],
    )

    selected = picker.pick_pieces(3)

    assert 1 not in selected
    assert set(selected) == {0, 2, 3}


def test_same_availability_uses_lowest_index():
    picker = PiecePicker(piece_count=4)

    picker.update_peer(
        "peer1",
        [0, 1, 2],
    )

    assert picker.pick_piece() == 0


def test_peer_update_recalculates_availability():
    picker = PiecePicker(piece_count=4)

    picker.update_peer(
        "peer1",
        [0, 1],
    )

    picker.update_peer(
        "peer2",
        [0, 2],
    )

    assert picker.availability(0) == 2
    assert picker.availability(1) == 1
    assert picker.availability(2) == 1

    picker.update_peer(
        "peer1",
        [2, 3],
    )

    assert picker.availability(0) == 1
    assert picker.availability(1) == 0
    assert picker.availability(2) == 2
    assert picker.availability(3) == 1


def test_remove_peer_updates_availability():
    picker = PiecePicker(piece_count=3)

    picker.update_peer(
        "peer1",
        [0, 1],
    )

    picker.update_peer(
        "peer2",
        [0, 2],
    )

    picker.remove_peer("peer1")

    assert picker.availability(0) == 1
    assert picker.availability(1) == 0
    assert picker.availability(2) == 1


def test_have_message_style_update():
    picker = PiecePicker(piece_count=3)

    picker.update_peer(
        "peer1",
        [0],
    )

    picker.add_peer_piece(
        "peer1",
        2,
    )

    assert picker.availability(0) == 1
    assert picker.availability(2) == 1

    assert picker.pick_piece() == 0


def test_duplicate_have_does_not_increase_availability():
    picker = PiecePicker(piece_count=3)

    picker.update_peer(
        "peer1",
        [0],
    )

    picker.add_peer_piece(
        "peer1",
        0,
    )

    assert picker.availability(0) == 1


def test_reservation_prevents_duplicate_selection():
    picker = PiecePicker(piece_count=3)

    picker.update_peer(
        "peer1",
        [0, 1],
    )

    first = picker.pick_piece()
    second = picker.pick_piece()

    assert first == 0
    assert second == 1


def test_release_makes_piece_selectable_again():
    picker = PiecePicker(piece_count=3)

    picker.update_peer(
        "peer1",
        [0, 1],
    )

    first = picker.pick_piece()

    assert first == 0

    picker.release(0)

    assert picker.pick_piece() == 0


def test_completed_piece_is_not_selected():
    picker = PiecePicker(piece_count=3)

    picker.update_peer(
        "peer1",
        [0, 1, 2],
    )

    picker.piece_completed(0)

    selected = picker.pick_pieces(2)

    assert 0 not in selected
    assert set(selected) == {1, 2}


def test_peers_for_piece():
    picker = PiecePicker(piece_count=3)

    picker.update_peer(
        "peer1",
        [0, 1],
    )

    picker.update_peer(
        "peer2",
        [0, 2],
    )

    peers = picker.peers_for_piece(0)

    assert set(peers) == {
        "peer1",
        "peer2",
    }


def test_complete_status():
    picker = PiecePicker(
        piece_count=3
    )

    assert not picker.is_complete
    assert picker.remaining_count == 3

    picker.piece_completed(0)
    picker.piece_completed(1)
    picker.piece_completed(2)

    assert picker.is_complete
    assert picker.completed_count == 3
    assert picker.remaining_count == 0


def test_invalid_piece_index():
    picker = PiecePicker(piece_count=3)

    with pytest.raises(ValueError):
        picker.add_local_piece(3)

    with pytest.raises(ValueError):
        picker.availability(-1)


def test_invalid_piece_count():
    with pytest.raises(ValueError):
        PiecePicker(-1)


def test_invalid_pick_count():
    picker = PiecePicker(piece_count=3)

    with pytest.raises(ValueError):
        picker.pick_pieces(-1)


def test_clear_preserves_local_pieces():
    picker = PiecePicker(
        piece_count=3,
        local_pieces=[0],
    )

    picker.update_peer(
        "peer1",
        [1, 2],
    )

    picker.pick_piece()

    picker.clear()

    assert picker.local_pieces() == {0}
    assert picker.availability(1) == 0
    assert picker.availability(2) == 0
    assert picker.reserved_count == 0


def test_reset_clears_everything():
    picker = PiecePicker(
        piece_count=3,
        local_pieces=[0],
    )

    picker.update_peer(
        "peer1",
        [1, 2],
    )

    picker.pick_piece()

    picker.reset()

    assert picker.local_pieces() == set()
    assert picker.availability(0) == 0
    assert picker.availability(1) == 0
    assert picker.availability(2) == 0
    assert picker.reserved_count == 0
    assert picker.completed_count == 0