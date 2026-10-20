from bittorrent_lite.piece_manager.choking import (
    ChokingManager,
)


def test_peer_is_choked_by_default():
    manager = ChokingManager()

    manager.add_peer("peer1")

    assert manager.is_choked("peer1")


def test_unchoke_peer():
    manager = ChokingManager()

    manager.add_peer("peer1")

    manager.unchoke("peer1")

    assert not manager.is_choked("peer1")


def test_choke_peer():
    manager = ChokingManager()

    manager.add_peer(
        "peer1",
        choked=False,
    )

    manager.choke("peer1")

    assert manager.is_choked("peer1")


def test_interested_state():
    manager = ChokingManager()

    manager.add_peer("peer1")

    assert not manager.is_interested("peer1")

    manager.set_interested(
        "peer1",
        True,
    )

    assert manager.is_interested("peer1")


def test_not_interested_state():
    manager = ChokingManager()

    manager.add_peer(
        "peer1",
        interested=True,
    )

    manager.set_interested(
        "peer1",
        False,
    )

    assert not manager.is_interested("peer1")


def test_preferred_peers_only_include_interested():
    manager = ChokingManager(
        max_unchoked=2
    )

    manager.add_peer(
        "peer1",
        interested=True,
    )

    manager.add_peer(
        "peer2",
        interested=False,
    )

    manager.add_peer(
        "peer3",
        interested=True,
    )

    selected = manager.select_preferred_peers()

    assert "peer1" in selected
    assert "peer3" in selected
    assert "peer2" not in selected


def test_preferred_peer_limit():
    manager = ChokingManager(
        max_unchoked=2
    )

    for i in range(5):
        manager.add_peer(
            f"peer{i}",
            interested=True,
        )

    selected = manager.select_preferred_peers()

    assert len(selected) == 2


def test_download_contribution_affects_preference():
    manager = ChokingManager(
        max_unchoked=2
    )

    manager.add_peer(
        "peer1",
        interested=True,
    )

    manager.add_peer(
        "peer2",
        interested=True,
    )

    manager.add_peer(
        "peer3",
        interested=True,
    )

    manager.record_download(
        "peer2",
        1000,
    )

    manager.record_download(
        "peer3",
        500,
    )

    selected = manager.select_preferred_peers()

    assert "peer2" in selected
    assert "peer3" in selected


def test_apply_choking_policy():
    manager = ChokingManager(
        max_unchoked=2
    )

    manager.add_peer(
        "peer1",
        interested=True,
    )

    manager.add_peer(
        "peer2",
        interested=True,
    )

    manager.add_peer(
        "peer3",
        interested=True,
    )

    selected = manager.apply_choking_policy()

    assert len(selected) == 2

    assert all(
        not manager.is_choked(peer)
        for peer in selected
    )

    assert len(
        manager.choked_peers()
    ) == 1


def test_optimistic_peer():
    manager = ChokingManager(
        max_unchoked=2
    )

    for i in range(3):
        manager.add_peer(
            f"peer{i}",
            interested=True,
        )

    manager.set_optimistic_peer(
        "peer2"
    )

    assert (
        manager.optimistic_peer()
        == "peer2"
    )


def test_record_upload():
    manager = ChokingManager()

    manager.add_peer("peer1")

    manager.record_upload(
        "peer1",
        4096,
    )

    assert (
        manager.uploaded_bytes("peer1")
        == 4096
    )


def test_record_download():
    manager = ChokingManager()

    manager.add_peer("peer1")

    manager.record_download(
        "peer1",
        8192,
    )

    assert (
        manager.downloaded_bytes("peer1")
        == 8192
    )


def test_remove_peer():
    manager = ChokingManager()

    manager.add_peer("peer1")

    assert manager.remove_peer("peer1")

    assert manager.peer_count() == 0


def test_unknown_peer_raises():
    manager = ChokingManager()

    try:
        manager.is_choked("unknown")
        assert False
    except KeyError:
        assert True


def test_reset():
    manager = ChokingManager()

    manager.add_peer("peer1")
    manager.add_peer("peer2")

    manager.set_optimistic_peer(
        "peer1"
    )

    manager.reset()

    assert manager.peer_count() == 0
    assert manager.optimistic_peer() is None