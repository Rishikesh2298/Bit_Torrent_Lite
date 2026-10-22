from unittest.mock import Mock

from bittorrent_lite.piece_manager.scheduler import (
    DownloadScheduler,
)


def make_connection(request_ids=None):
    """
    Create a lightweight mock PeerConnection.
    """

    connection = Mock()

    if request_ids is None:
        request_ids = iter(range(1, 100))

    def send_request(piece_index):
        request_id = next(request_ids)

        request = Mock()
        request.request_id = request_id
        request.piece_index = piece_index

        return request

    connection.send_request.side_effect = (
        send_request
    )

    connection.outstanding_request_count = 0

    return connection


def test_scheduler_selects_rarest_piece():
    scheduler = DownloadScheduler(
        piece_count=5
    )

    connection = make_connection()

    scheduler.add_peer(
        "peer1",
        connection,
        [0, 1, 2],
    )

    scheduler.add_peer(
        "peer2",
        make_connection(),
        [0, 1],
    )

    scheduler.add_peer(
        "peer3",
        make_connection(),
        [0],
    )

    selected = scheduler.schedule_one()

    assert selected == 2


def test_scheduler_does_not_select_local_piece():
    scheduler = DownloadScheduler(
        piece_count=4,
        local_pieces=[1],
    )

    connection = make_connection()

    scheduler.add_peer(
        "peer1",
        connection,
        [0, 1, 2, 3],
    )

    selected = scheduler.fill_pipeline()

    assert 1 not in selected
    assert set(selected) == {0, 2, 3}


def test_scheduler_records_request():
    scheduler = DownloadScheduler(
        piece_count=3
    )

    connection = make_connection()

    scheduler.add_peer(
        "peer1",
        connection,
        [0],
    )

    selected = scheduler.schedule_one()

    assert selected == 0

    pending = scheduler.pending_requests()

    assert len(pending) == 1

    request_id = next(iter(pending))

    assert pending[request_id] == (
        "peer1",
        0,
    )


def test_piece_received_marks_piece_complete():
    scheduler = DownloadScheduler(
        piece_count=2
    )

    connection = make_connection()

    scheduler.add_peer(
        "peer1",
        connection,
        [0],
    )

    scheduler.schedule_one()

    request_id = next(
        iter(
            scheduler.pending_requests()
        )
    )

    assert scheduler.piece_received(
        request_id,
        0,
    )

    assert scheduler.completed_count == 1
    assert scheduler.remaining_count == 1
    assert 0 in scheduler.local_pieces()


def test_piece_received_wrong_piece_is_rejected():
    scheduler = DownloadScheduler(
        piece_count=2
    )

    connection = make_connection()

    scheduler.add_peer(
        "peer1",
        connection,
        [0],
    )

    scheduler.schedule_one()

    request_id = next(
        iter(
            scheduler.pending_requests()
        )
    )

    assert not scheduler.piece_received(
        request_id,
        1,
    )

    assert scheduler.completed_count == 0
    assert request_id in (
        scheduler.pending_requests()
    )


def test_rejected_request_releases_piece():
    scheduler = DownloadScheduler(
        piece_count=2
    )

    connection = make_connection()

    scheduler.add_peer(
        "peer1",
        connection,
        [0],
    )

    scheduler.schedule_one()

    request_id = next(
        iter(
            scheduler.pending_requests()
        )
    )

    assert scheduler.request_rejected(
        request_id
    )

    assert scheduler.pending_requests() == {}

    assert scheduler.reserved_pieces() == set()


def test_failed_request_releases_piece():
    scheduler = DownloadScheduler(
        piece_count=2
    )

    connection = make_connection()

    scheduler.add_peer(
        "peer1",
        connection,
        [0],
    )

    scheduler.schedule_one()

    request_id = next(
        iter(
            scheduler.pending_requests()
        )
    )

    assert scheduler.request_failed(
        request_id
    )

    assert scheduler.pending_requests() == {}


def test_remove_peer_releases_pending_request():
    scheduler = DownloadScheduler(
        piece_count=2
    )

    connection = make_connection()

    scheduler.add_peer(
        "peer1",
        connection,
        [0],
    )

    scheduler.schedule_one()

    assert scheduler.reserved_pieces() == {
        0
    }

    scheduler.remove_peer(
        "peer1"
    )

    assert scheduler.pending_requests() == {}
    assert scheduler.reserved_pieces() == set()


def test_have_updates_peer_availability():
    scheduler = DownloadScheduler(
        piece_count=3
    )

    connection = make_connection()

    scheduler.add_peer(
        "peer1",
        connection,
        [0],
    )

    scheduler.add_peer_piece(
        "peer1",
        2,
    )

    assert (
        scheduler.piece_picker.availability(2)
        == 1
    )


def test_no_peer_means_no_request():
    scheduler = DownloadScheduler(
        piece_count=3
    )

    assert scheduler.schedule_one() is None


def test_fill_pipeline_requests_multiple_pieces():
    scheduler = DownloadScheduler(
        piece_count=6
    )

    connection = make_connection()

    scheduler.add_peer(
        "peer1",
        connection,
        [0, 1, 2, 3, 4, 5],
    )

    selected = scheduler.fill_pipeline()

    assert len(selected) == 6

    assert set(selected) == {
        0,
        1,
        2,
        3,
        4,
        5,
    }


def test_scheduler_completion():
    scheduler = DownloadScheduler(
        piece_count=2
    )

    connection = make_connection()

    scheduler.add_peer(
        "peer1",
        connection,
        [0, 1],
    )

    scheduler.schedule_one()

    request_id = next(
        iter(
            scheduler.pending_requests()
        )
    )

    piece_index = scheduler.pending_requests()[
        request_id
    ][1]

    assert scheduler.piece_received(
        request_id,
        piece_index,
    )

    scheduler.schedule_one()

    request_ids = scheduler.pending_requests()

    second_request_id = next(
        iter(request_ids)
    )

    second_piece = request_ids[
        second_request_id
    ][1]

    assert scheduler.piece_received(
        second_request_id,
        second_piece,
    )

    assert scheduler.is_complete