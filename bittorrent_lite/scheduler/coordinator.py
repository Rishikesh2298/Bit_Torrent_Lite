"""Single-owner scheduler combining request accounting and recovery policy."""
import random
from typing import Optional

from request_pipeline import PipelineManager, RequestKey
from recovery_policy import RecoveryPolicy, CapacityError
from . import events as ev
from .interfaces import Clock, PieceStore, Transport
from .models import NeighborState, SchedulerConfig
from .piece_picker import PiecePicker


class Coordinator:
    def __init__(self, num_pieces: int, transport: Transport, store: PieceStore,
                 clock: Clock, config: Optional[SchedulerConfig] = None,
                 rng: Optional[random.Random] = None):
        self._n = num_pieces
        self._transport = transport
        self._store = store
        self._clock = clock
        self._config = config or SchedulerConfig()
        self._picker = PiecePicker(num_pieces, rng)
        local = list(store.verified_bitfield())
        self._picker.validate_bitfield(local)
        self._local = [bool(b) for b in local]
        self._pipeline = PipelineManager(
            num_pieces, initially_owned=[i for i, have in enumerate(local) if have],
            config=self._config.pipeline_config())
        self._recovery = RecoveryPolicy(num_pieces, self._config.recovery,
                                        seed=(rng.getrandbits(64) if rng is not None
                                              else self._config.recovery_seed))
        for i, have in enumerate(local):
            if have:
                self._recovery.succeeded(now=clock.now(), provider="local", piece=i)
        self._neighbors: dict[int, NeighborState] = {}
        self._storage_error = None
        self._recovery_error = None
        self._invalid_pieces = []
        self._problems = []
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

    def handle_event(self, event) -> None:
        handler = self._handlers.get(type(event))
        if handler is None:
            raise TypeError(f"unknown event type {type(event).__name__}")
        handler(event)
        self.schedule()

    def _permissions(self, n, reason=None):
        outcomes = self._pipeline.set_permissions(
            n.connection_id, interested=n.am_interested,
            unchoked=not n.peer_choking, now=self._clock.now())
        for outcome in outcomes:
            if reason:
                self._record_failure(outcome.key, reason)
            self._cancel_wire(outcome.key)

    def _record_failure(self, key, kind):
        try:
            self._recovery.failed(now=self._clock.now(),
                                  provider=self._neighbors[key.connection_id].peer_id,
                                  piece=key.piece_index, kind=kind)
        except CapacityError as exc:
            # Accounting cleanup has already happened. Never issue more work
            # after losing the ability to remember a required penalty.
            self._recovery_error = str(exc)

    def _cancel_wire(self, key):
        send = getattr(self._transport, "send_cancel", None)
        if not callable(send):
            return
        try:
            sent = send(key.connection_id, key.request_id, key.piece_index)
        except OSError:
            sent = False
        if not sent:
            self._problems.append((key.connection_id,
                                   f"CANCEL enqueue failed for request {key.request_id}"))

    def _enqueue(self, request):
        k = request.key
        if self._transport.send_request(k.connection_id, k.request_id, k.piece_index):
            return 1
        self._pipeline.send_failed(k, reason="enqueue_failed", now=self._clock.now())
        self._record_failure(k, "enqueue_failed")
        self._problems.append((k.connection_id, f"enqueue failed for piece {k.piece_index}"))
        return 0

    def schedule(self) -> int:
        orders = {}
        availability = self._picker.availability_snapshot()
        for cid, n in self._neighbors.items():
            if not n.active or n.bitfield is None:
                continue
            wanted = any(has and not self._local[i] for i, has in enumerate(n.bitfield))
            if wanted != n.am_interested and self._transport.send_interest(cid, wanted):
                n.am_interested = wanted
            self._permissions(n)
            if (self._storage_error is None and self._recovery_error is None
                    and n.am_interested and not n.peer_choking):
                orders[cid] = self._recovery.rank_candidates(
                    now=self._clock.now(), provider=n.peer_id,
                    candidates=[i for i, has in enumerate(n.bitfield)
                                if has and not self._local[i]], availability=availability)
        if not orders:
            return 0
        # Reserve the entire bounded batch before enqueueing. A rejected enqueue
        # is cleaned once; retry waits for the next scheduling call.
        requests = self._pipeline.fill(orders, now=self._clock.now())
        issued = 0
        for r in requests:
            if self._recovery_error is None:
                issued += self._enqueue(r)
            else:
                self._pipeline.cancel(r.key, reason="recovery_capacity", now=self._clock.now())
        if self._recovery_error is None:
            issued += self._schedule_duplicates(orders)
        return issued

    def _schedule_duplicates(self, orders):
        # Legacy transports may still download normally, but duplicates need
        # a cancellation channel for the losing provider.
        if not callable(getattr(self._transport, "send_cancel", None)):
            return 0
        snapshot = self._pipeline.snapshot()
        missing = self._n - len(snapshot["owned"])
        cfg = self._config.recovery
        if (not cfg.endgame_enabled or cfg.max_copies != 2
                or not 1 <= missing <= cfg.endgame_remaining):
            return 0
        reserved = {r["piece_index"] for r in snapshot["pending"]}
        if any(piece not in reserved for order in orders.values() for piece in order):
            return 0
        issued = 0
        for cid, order in orders.items():
            for piece in order:
                pending = [r for r in self._pipeline.snapshot()["pending"]
                           if r["piece_index"] == piece]
                records = [{"request_id": r["request_id"], "provider": r["provider_id"],
                            "piece": piece, "queued_at": r["queued_at"],
                            "sent_at": r["sent_at"], "verifying": r["verifying"]}
                           for r in pending]
                if not self._recovery.allow_duplicate(
                        now=self._clock.now(), piece=piece,
                        provider=self._neighbors[cid].peer_id, pending=records,
                        missing_count=missing, no_unreserved_candidates=True):
                    continue
                req = self._pipeline.reserve(cid, piece, now=self._clock.now(),
                                             allow_duplicate=True)
                if req is not None:
                    issued += self._enqueue(req)
                    if self._recovery_error is not None:
                        return issued
        return issued

    def tick(self) -> list[ev.ExpiredRequest]:
        outcomes = self._pipeline.expire(now=self._clock.now())
        for o in outcomes:
            self._record_failure(o.key, o.reason)
            self._cancel_wire(o.key)
        return [ev.ExpiredRequest(o.key.connection_id, o.key.request_id,
                                  o.key.piece_index, o.reason) for o in outcomes]

    def snapshot(self) -> dict:
        pipeline = self._pipeline.snapshot()
        outstanding = {r["connection_id"]: r["count"] for r in pipeline["outstanding"]}
        return {
            "owned": len(pipeline["owned"]), "total": self._n,
            "ready_to_assemble": len(pipeline["owned"]) == self._n,
            "piece_states": pipeline["piece_state_counts"],
            "availability": self._picker.availability_snapshot(),
            "paused": self._storage_error is not None or self._recovery_error is not None,
            "storage_error": self._storage_error,
            "recovery_error": self._recovery_error,
            "recovery": self._recovery.snapshot(now=self._clock.now()),
            "invalid_pieces": list(self._invalid_pieces),
            "problems": list(self._problems),
            "pipeline_counters": pipeline["counters"],
            "neighbors": {
                cid: {"peer_id": n.peer_id, "active": n.active,
                      "am_interested": n.am_interested,
                      "peer_interested": n.peer_interested,
                      "am_choking": n.am_choking, "peer_choking": n.peer_choking,
                      "has_bitfield": n.bitfield is not None,
                      "outstanding": outstanding.get(cid, 0)}
                for cid, n in self._neighbors.items()},
            "pending": [{"connection_id": r["connection_id"],
                         "request_id": r["request_id"], "piece_index": r["piece_index"],
                         "sent": r["sent_at"] is not None, "verifying": r["verifying"],
                         "deadline": r["deadline"]} for r in pipeline["pending"]],
        }

    def resume_after_storage_error(self) -> None:
        self._storage_error = None
        self.schedule()

    def _active(self, connection_id):
        n = self._neighbors.get(connection_id)
        return n if n is not None and n.active else None

    @staticmethod
    def _key(e):
        return RequestKey(e.connection_id, e.request_id, e.piece_index)

    def _on_ready(self, e):
        if not isinstance(e.peer_id, str) or not 1 <= len(e.peer_id) <= 128:
            self._problems.append((e.connection_id, "invalid provider identity"))
            return
        if self._active(e.connection_id) is not None:
            return
        try:
            self._pipeline.register_connection(e.connection_id, e.peer_id, now=self._clock.now())
        except ValueError as exc:
            self._problems.append((e.connection_id, str(exc)))
            return
        self._neighbors[e.connection_id] = NeighborState(e.connection_id, e.peer_id)

    def _on_bitfield(self, e):
        n = self._active(e.connection_id)
        if n is None:
            return
        try:
            self._picker.validate_bitfield(e.bitfield)
        except (ValueError, TypeError):
            self._problems.append((e.connection_id, "invalid bitfield"))
            return
        bits = [bool(b) for b in e.bitfield]
        self._pipeline.set_available(e.connection_id, [i for i, has in enumerate(bits) if has],
                                     now=self._clock.now())
        n.bitfield = bits
        self._picker.update_bitfield(e.connection_id, bits)

    def _on_have(self, e):
        n = self._active(e.connection_id)
        if n is None:
            return
        if type(e.piece_index) is not int or not 0 <= e.piece_index < self._n:
            self._problems.append((e.connection_id, f"bad HAVE index {e.piece_index}"))
            return
        bits = list(n.bitfield) if n.bitfield is not None else [False] * self._n
        bits[e.piece_index] = True
        self._on_bitfield(ev.BitfieldReceived(e.connection_id, bits))

    def _on_choke(self, e):
        n = self._active(e.connection_id)
        if n is not None:
            n.peer_choking = True
            self._permissions(n, reason="choke")

    def _on_unchoke(self, e):
        n = self._active(e.connection_id)
        if n is not None:
            n.peer_choking = False
            self._permissions(n)

    def _on_peer_interest(self, e):
        n = self._active(e.connection_id)
        if n is not None:
            n.peer_interested = e.interested

    def _on_request_sent(self, e):
        self._pipeline.confirm_sent(self._key(e), sent_at=e.sent_at, now=self._clock.now())

    def _on_send_failed(self, e):
        if self._pipeline.send_failed(self._key(e), reason=e.reason or "send_failed",
                                      now=self._clock.now()):
            self._record_failure(self._key(e), "send_failed")
            self._problems.append((e.connection_id, f"send failed for piece {e.piece_index}: {e.reason}"))

    def _on_reject(self, e):
        if self._pipeline.reject(self._key(e), now=self._clock.now()):
            self._record_failure(self._key(e), "reject")

    def _on_disconnected(self, e):
        outcomes = self._pipeline.disconnect(e.connection_id, now=self._clock.now())
        for o in outcomes:
            self._record_failure(o.key, "disconnect")
        n = self._neighbors.get(e.connection_id)
        if n is not None:
            n.active = False
        self._picker.remove_connection(e.connection_id)

    def _on_piece(self, e):
        if self._active(e.connection_id) is None:
            return
        key = self._key(e)
        if not self._pipeline.start_verification(key, now=self._clock.now()):
            return
        try:
            ok = self._store.verify_and_store(e.piece_index, e.data)
        except OSError as exc:
            self._pipeline.cancel(key, reason="storage_error", now=self._clock.now())
            # Pause before any new reservation. Other copies remain accounted
            # for; local disk failure is never provider corruption.
            self._storage_error = f"{type(exc).__name__}: {exc}"
            return
        outcomes = self._pipeline.finish_verification(key, valid=ok, now=self._clock.now())
        if not outcomes:
            return  # canceled/disconnected during verification
        if not ok:
            self._record_failure(key, "invalid_piece")
            self._invalid_pieces.append((e.connection_id, e.piece_index, self._clock.now()))
            return
        self._recovery.succeeded(now=self._clock.now(), provider=self._neighbors[e.connection_id].peer_id,
                                 piece=e.piece_index)
        for o in outcomes:
            if o.kind == "canceled":
                self._cancel_wire(o.key)
        self._local[e.piece_index] = True
        for n in self._neighbors.values():
            if n.active and not self._transport.send_have(n.connection_id, e.piece_index):
                self._problems.append((n.connection_id, f"HAVE enqueue failed for piece {e.piece_index}"))
