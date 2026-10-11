import random
from typing import Optional

from . import events as ev
from .interfaces import Clock, PieceStore, Transport
from .models import NeighborState, PendingRequest, PieceState, SchedulerConfig
from .piece_picker import PiecePicker
from .request_manager import RequestManager


class Coordinator:
    def __init__(
        self,
        num_pieces: int,
        transport: Transport,
        store: PieceStore,
        clock: Clock,
        config: Optional[SchedulerConfig] = None,
        rng: Optional[random.Random] = None,
    ):
        self._n = num_pieces
        self._transport = transport
        self._store = store
        self._clock = clock
        self._config = config or SchedulerConfig()
        self._picker = PiecePicker(num_pieces, rng)
        self._requests = RequestManager(clock, self._config)
        self._neighbors: dict[int, NeighborState] = {}

        local = list(store.verified_bitfield())
        self._picker.validate_bitfield(local)
        local = [bool(b) for b in local]
        self._local = local
        self._state = [PieceState.HAVE if have else PieceState.MISSING for have in local]

        self._storage_error: Optional[str] = None
        self._invalid_pieces: list[tuple[int, int, float]] = []
        self._problems: list[tuple[int, str]] = []

        self._handlers = {
            ev.ConnectionReady: self._on_ready,
            ev.BitfieldReceived: self._on_bitfield,
            ev.HaveReceived: self._on_have,
            ev.ChokeReceived: self._on_choke,
            ev.UnchokeReceived: self._on_unchoke,
            ev.PeerInterestChanged: self._on_peer_interest,
            ev.RequestSent: self._on_request_sent,
            ev.RequestSendFailed: self._on_send_failed,
            ev.PieceReceived: self._on_piece,
            ev.RejectReceived: self._on_reject,
            ev.Disconnected: self._on_disconnected,
        }

    # public interface

    def handle_event(self, event) -> None:
        handler = self._handlers.get(type(event))
        if handler is None:
            raise TypeError(f"unknown event type {type(event).__name__}")
        handler(event)
        self.schedule()

    def schedule(self) -> int:
        issued = 0
        progress = True
        while progress:
            progress = False
            for cid in sorted(self._neighbors):
                if self._try_schedule(self._neighbors[cid]):
                    issued += 1
                    progress = True
        return issued

    def tick(self) -> list[ev.ExpiredRequest]:
        now = self._clock.now()
        out = []
        for req in self._requests.get_expired(now):
            out.append(self._expire(req, "response_timeout"))
        for req in self._requests.get_unsent_expired(now):
            out.append(self._expire(req, "send_unconfirmed"))
        return [o for o in out if o is not None]

    def snapshot(self) -> dict:
        counts = {s.value: 0 for s in PieceState}
        for s in self._state:
            counts[s.value] += 1
        return {
            "owned": sum(self._local),
            "total": self._n,
            "ready_to_assemble": all(self._local),
            "piece_states": counts,
            "availability": self._picker.availability_snapshot(),
            "paused": self._storage_error is not None,
            "storage_error": self._storage_error,
            "invalid_pieces": list(self._invalid_pieces),
            "problems": list(self._problems),
            "neighbors": {
                cid: {
                    "peer_id": n.peer_id,
                    "active": n.active,
                    "am_interested": n.am_interested,
                    "peer_interested": n.peer_interested,
                    "am_choking": n.am_choking,
                    "peer_choking": n.peer_choking,
                    "has_bitfield": n.bitfield is not None,
                    "outstanding": self._requests.outstanding_count(cid),
                }
                for cid, n in self._neighbors.items()
            },
            "pending": [
                {
                    "connection_id": r.connection_id,
                    "request_id": r.request_id,
                    "piece_index": r.piece_index,
                    "sent": r.sent_at is not None,
                    "verifying": r.verifying,
                    "deadline": r.deadline,
                }
                for r in self._requests.all_pending()
            ],
        }

    def resume_after_storage_error(self) -> None:
        self._storage_error = None
        self.schedule()

    # scheduling

    def _try_schedule(self, n: NeighborState) -> bool:
        if not n.active or n.bitfield is None:
            return False

        wanted = any(has and not self._local[i] for i, has in enumerate(n.bitfield))
        if wanted != n.am_interested and self._transport.send_interest(n.connection_id, wanted):
            n.am_interested = wanted

        if self._storage_error is not None or n.peer_choking or not n.am_interested:
            return False
        if not self._requests.can_request(n.connection_id):
            return False

        piece = self._picker.pick_piece(self._local, n.bitfield, self._requests.reserved_pieces())
        if piece is None:
            return False
        req = self._requests.reserve(n.connection_id, piece)
        if req is None:
            return False
        self._state[piece] = PieceState.REQUESTED

        if not self._transport.send_request(n.connection_id, req.request_id, piece):
            self._requests.cancel(n.connection_id, req.request_id, piece)
            self._release_piece(piece)
            self._problems.append((n.connection_id, f"enqueue failed for piece {piece}"))
            return False
        return True

    def _release_piece(self, piece: int) -> None:
        if self._state[piece] is not PieceState.HAVE:
            self._state[piece] = PieceState.MISSING

    def _active(self, connection_id: int) -> Optional[NeighborState]:
        n = self._neighbors.get(connection_id)
        return n if n is not None and n.active else None

    def _expire(self, req: PendingRequest, kind: str) -> Optional[ev.ExpiredRequest]:
        if self._requests.cancel(req.connection_id, req.request_id, req.piece_index) is None:
            return None
        self._release_piece(req.piece_index)
        return ev.ExpiredRequest(req.connection_id, req.request_id, req.piece_index, kind)

    # event handlers

    def _on_ready(self, e: ev.ConnectionReady) -> None:
        if self._active(e.connection_id) is not None:
            return
        if e.connection_id in self._neighbors:
            self._problems.append((e.connection_id, "connection id reused after disconnect"))
            return
        self._neighbors[e.connection_id] = NeighborState(e.connection_id, e.peer_id)

    def _on_bitfield(self, e: ev.BitfieldReceived) -> None:
        n = self._active(e.connection_id)
        if n is None:
            return
        try:
            self._picker.validate_bitfield(e.bitfield)
        except (ValueError, TypeError):
            self._problems.append((e.connection_id, "invalid bitfield"))
            return
        n.bitfield = [bool(b) for b in e.bitfield]
        self._picker.update_bitfield(e.connection_id, n.bitfield)

    def _on_have(self, e: ev.HaveReceived) -> None:
        n = self._active(e.connection_id)
        if n is None:
            return
        if type(e.piece_index) is not int or not 0 <= e.piece_index < self._n:
            self._problems.append((e.connection_id, f"bad HAVE index {e.piece_index}"))
            return
        if n.bitfield is None:
            n.bitfield = [False] * self._n
        n.bitfield[e.piece_index] = True
        self._picker.record_have(e.connection_id, e.piece_index)

    def _on_choke(self, e: ev.ChokeReceived) -> None:
        n = self._active(e.connection_id)
        if n is None:
            return
        n.peer_choking = True
        # a choking peer drops requests that were not answered yet
        for req in self._requests.all_pending():
            if req.connection_id == e.connection_id and not req.verifying:
                self._requests.cancel(req.connection_id, req.request_id, req.piece_index)
                self._release_piece(req.piece_index)

    def _on_unchoke(self, e: ev.UnchokeReceived) -> None:
        n = self._active(e.connection_id)
        if n is not None:
            n.peer_choking = False

    def _on_peer_interest(self, e: ev.PeerInterestChanged) -> None:
        n = self._active(e.connection_id)
        if n is not None:
            n.peer_interested = e.interested

    def _on_request_sent(self, e: ev.RequestSent) -> None:
        # unknown or already finished requests are ignored, so a late confirmation recreates nothing
        self._requests.mark_sent(e.connection_id, e.request_id, e.piece_index, e.sent_at)

    def _on_send_failed(self, e: ev.RequestSendFailed) -> None:
        if self._requests.cancel(e.connection_id, e.request_id, e.piece_index) is not None:
            self._release_piece(e.piece_index)
            self._problems.append((e.connection_id, f"send failed for piece {e.piece_index}: {e.reason}"))

    def _on_reject(self, e: ev.RejectReceived) -> None:
        req = self._requests.get(e.connection_id, e.request_id, e.piece_index)
        if req is None or req.verifying:
            return
        self._requests.cancel(e.connection_id, e.request_id, e.piece_index)
        self._release_piece(e.piece_index)

    def _on_disconnected(self, e: ev.Disconnected) -> None:
        n = self._neighbors.get(e.connection_id)
        if n is not None:
            n.active = False
        self._picker.remove_connection(e.connection_id)
        for req in self._requests.cancel_connection(e.connection_id):
            self._release_piece(req.piece_index)

    def _on_piece(self, e: ev.PieceReceived) -> None:
        if self._active(e.connection_id) is None:
            return
        req = self._requests.get(e.connection_id, e.request_id, e.piece_index)
        if req is None or req.verifying:
            return  # unsolicited, stale, or mismatched

        # the request stays in the manager while verifying, so the piece stays reserved
        self._requests.mark_verifying(e.connection_id, e.request_id, e.piece_index)
        self._state[e.piece_index] = PieceState.VERIFYING

        try:
            ok = self._store.verify_and_store(e.piece_index, e.data)
        except OSError as exc:
            self._requests.cancel(e.connection_id, e.request_id, e.piece_index)
            self._release_piece(e.piece_index)
            self._storage_error = f"{type(exc).__name__}: {exc}"
            return

        self._requests.complete(e.connection_id, e.request_id, e.piece_index)
        if not ok:
            self._release_piece(e.piece_index)
            self._invalid_pieces.append((e.connection_id, e.piece_index, self._clock.now()))
            return

        self._local[e.piece_index] = True
        self._state[e.piece_index] = PieceState.HAVE
        for n in self._neighbors.values():
            if n.active and not self._transport.send_have(n.connection_id, e.piece_index):
                self._problems.append((n.connection_id, f"HAVE enqueue failed for piece {e.piece_index}"))
