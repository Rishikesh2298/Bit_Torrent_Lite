import pytest

from bittorrent_lite.piece_manager.request_manager import (
    RequestManager,
)

from bittorrent_lite.protocol.messages import (
    Piece,
    Reject,
)


def test_default_pipeline_window_is_four():

    manager = RequestManager()

    assert manager.pipeline_window == 4
    assert manager.outstanding_count == 0
    assert manager.available_slots == 4


def test_four_requests_can_be_outstanding():

    manager = RequestManager()

    requests = []

    for piece_index in range(4):

        request = manager.create_request(
            piece_index
        )

        assert request is not None

        requests.append(request)

    assert len(requests) == 4

    assert manager.outstanding_count == 4

    assert manager.available_slots == 0


def test_fifth_request_is_blocked():

    manager = RequestManager()

    for piece_index in range(4):

        request = manager.create_request(
            piece_index
        )

        assert request is not None

    fifth = manager.create_request(4)

    assert fifth is None

    assert manager.outstanding_count == 4

    assert manager.available_slots == 0


def test_completed_piece_frees_pipeline_slot():

    manager = RequestManager()

    requests = []

    for piece_index in range(4):

        request = manager.create_request(
            piece_index
        )

        requests.append(request)

    assert manager.available_slots == 0

    piece = Piece(
        request_id=requests[0].request_id,
        piece_index=requests[0].piece_index,
        _payload=b"piece-data",
    )

    assert manager.handle_piece(
        piece
    )

    assert manager.outstanding_count == 3

    assert manager.available_slots == 1

    next_request = manager.create_request(4)

    assert next_request is not None

    assert manager.outstanding_count == 4


def test_reject_frees_pipeline_slot():

    manager = RequestManager()

    requests = []

    for piece_index in range(4):

        request = manager.create_request(
            piece_index
        )

        requests.append(request)

    reject = Reject(
        request_id=requests[0].request_id,
        piece_index=requests[0].piece_index,
        reason="piece unavailable",
    )

    assert manager.handle_reject(
        reject
    )

    assert manager.outstanding_count == 3

    assert manager.available_slots == 1


def test_piece_must_match_piece_index():

    manager = RequestManager()

    request = manager.create_request(5)

    wrong_piece = Piece(
        request_id=request.request_id,
        piece_index=6,
        _payload=b"wrong",
    )

    assert not manager.handle_piece(
        wrong_piece
    )

    assert manager.outstanding_count == 1

    assert manager.is_outstanding(
        request.request_id
    )


def test_unknown_piece_does_not_complete_request():

    manager = RequestManager()

    manager.create_request(2)

    unknown_piece = Piece(
        request_id=999,
        piece_index=2,
        _payload=b"data",
    )

    assert not manager.handle_piece(
        unknown_piece
    )

    assert manager.outstanding_count == 1


def test_request_ids_are_unique():

    manager = RequestManager(
        pipeline_window=10
    )

    requests = [
        manager.create_request(i)
        for i in range(10)
    ]

    request_ids = [
        request.request_id
        for request in requests
    ]

    assert len(
        request_ids
    ) == len(
        set(request_ids)
    )


def test_custom_pipeline_window():

    manager = RequestManager(
        pipeline_window=2
    )

    assert manager.create_request(0) is not None
    assert manager.create_request(1) is not None

    assert manager.create_request(2) is None


def test_invalid_pipeline_window():

    with pytest.raises(ValueError):

        RequestManager(
            pipeline_window=0
        )

    with pytest.raises(ValueError):

        RequestManager(
            pipeline_window=-1
        )


def test_negative_piece_index_is_rejected():

    manager = RequestManager()

    with pytest.raises(ValueError):

        manager.create_request(-1)


def test_outstanding_requests_snapshot():

    manager = RequestManager()

    request1 = manager.create_request(3)
    request2 = manager.create_request(7)

    outstanding = (
        manager.outstanding_requests()
    )

    assert outstanding == {
        request1.request_id: 3,
        request2.request_id: 7,
    }


def test_piece_for_request():

    manager = RequestManager()

    request = manager.create_request(10)

    assert manager.piece_for_request(
        request.request_id
    ) == 10


def test_clear_removes_outstanding_requests():

    manager = RequestManager()

    manager.create_request(0)
    manager.create_request(1)

    manager.clear()

    assert manager.outstanding_count == 0
    assert manager.available_slots == 4


def test_reset_restores_request_state():

    manager = RequestManager()

    request = manager.create_request(5)

    piece = Piece(
        request_id=request.request_id,
        piece_index=5,
        _payload=b"data",
    )

    manager.handle_piece(piece)

    manager.create_request(6)

    manager.reset()

    assert manager.outstanding_count == 0
    assert manager.completed_count == 0
    assert manager.rejected_count == 0
    assert manager.available_slots == 4

    new_request = manager.create_request(0)

    assert new_request.request_id == 1