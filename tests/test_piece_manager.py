"""Selection and lifecycle acceptance checks against the integrated Part 1/2 APIs."""
import random

from bittorrent_lite.scheduler.piece_picker import PiecePicker
from request_pipeline import PipelineManager


def picker():
    p = PiecePicker(4, random.Random(17))
    p.update_bitfield(1, [1, 1, 1, 0])
    p.update_bitfield(2, [1, 1, 0, 1])
    return p


def manager():
    p = PipelineManager(6)
    for cid in (1, 2):
        p.register_connection(cid, str(cid), now=0)
        p.set_available(cid, list(range(6)), now=0)
        p.set_permissions(cid, interested=True, unchoked=True, now=0)
    return p


class TestAvailability:
    def test_update_from_bitfield(self):
        p = picker()
        assert p.availability_snapshot() == [2, 2, 1, 1]
        p.update_bitfield(1, [0, 1, 1, 0])
        assert p.availability_snapshot() == [1, 2, 1, 1]

    def test_have_increments(self):
        p = picker()
        p.record_have(1, 3)
        p.record_have(1, 3)
        assert p.availability_snapshot() == [2, 2, 1, 2]

    def test_disconnect_decrements(self):
        p = picker()
        p.remove_connection(1)
        assert p.availability_snapshot() == [1, 1, 0, 1]

    def test_availability_never_negative(self):
        p = picker()
        for _ in range(3):
            for cid in (1, 2, 99):
                p.remove_connection(cid)
        assert p.availability_snapshot() == [0] * 4


class TestRarestFirst:
    def test_picks_rarest(self):
        assert picker().pick_piece([0]*4, [1, 1, 1, 0], set()) == 2

    def test_skips_owned_pieces(self):
        assert picker().pick_piece([0, 0, 1, 0], [1, 1, 1, 0], set()) in (0, 1)

    def test_skips_unavailable_pieces(self):
        assert picker().pick_piece([0]*4, [0, 1, 0, 0], set()) == 1

    def test_skips_requested_pieces(self):
        assert picker().pick_piece([0]*4, [1, 1, 1, 0], {2}) in (0, 1)

    def test_returns_none_when_nothing_available(self):
        p = picker()
        assert p.pick_piece([1]*4, [1]*4, set()) is None
        assert p.pick_piece([0]*4, [0]*4, set()) is None
        assert p.pick_piece([0]*4, [1]*4, set(range(4))) is None

    def test_tie_breaking_is_random(self):
        p = picker()
        chosen = [p.pick_piece([0]*4, [1]*4, set()) for _ in range(100)]
        assert set(chosen) == {2, 3}


class TestRequestManager:
    def test_add_and_check(self):
        p = manager()
        r = p.reserve(1, 0, now=0)
        assert r.key.piece_index == 0
        assert p.snapshot()['piece_state_counts']['REQUESTED'] == 1
        assert p.snapshot()['outstanding'][0]['count'] == 1

    def test_complete_removes(self):
        p = manager()
        r = p.reserve(1, 0, now=0)
        assert p.start_verification(r.key, now=0)
        assert p.finish_verification(r.key, valid=True, now=0)[0].kind == 'completed'
        assert p.snapshot()['pending'] == []
        assert p.snapshot()['owned'] == [0]

    def test_duplicate_rejected(self):
        p = manager()
        assert p.reserve(1, 0, now=0)
        assert p.reserve(1, 0, now=0) is None
        assert p.reserve(2, 0, now=0) is None
        assert len(p.snapshot()['pending']) == 1

    def test_pipelining_limit(self):
        p = manager()
        assert len(p.fill({1: list(range(6))}, now=0)) == 4
        assert p.reserve(1, 4, now=0) is None
        assert p.reserve(2, 4, now=0)

    def test_timeout_detection(self):
        p = manager()
        sent = p.reserve(1, 0, now=0)
        unsent = p.reserve(1, 1, now=0)
        p.confirm_sent(sent.key, sent_at=2, now=2)
        assert p.expire(now=4) == ()
        assert [(o.key, o.reason) for o in p.expire(now=5)] == [(unsent.key, 'send_unconfirmed')]
        assert p.expire(now=11.99) == ()
        assert [(o.key, o.reason) for o in p.expire(now=12)] == [(sent.key, 'response_timeout')]
        assert p.snapshot()['pending'] == []
