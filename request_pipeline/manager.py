"""PipelineManager: admission, fair filling, deadlines, ownership accounting.

All calls belong to one owner thread. No threads, callbacks, sleeps or
wall-clock reads are used; callers supply monotonic ``now`` values.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .models import (Outcome, PieceState, PipelineConfig, RequestKey,
                     RequestView, is_int, is_time)


class _Conn:
    __slots__ = ("provider_id", "available", "interested", "unchoked")

    def __init__(self, provider_id: str):
        self.provider_id = provider_id
        self.available: Set[int] = set()
        self.interested = False
        self.unchoked = False


class _Req:
    __slots__ = ("key", "provider_id", "queued_at", "sent_at", "deadline",
                 "verifying")

    def __init__(self, key, provider_id, queued_at):
        self.key = key
        self.provider_id = provider_id
        self.queued_at = queued_at
        self.sent_at: Optional[float] = None
        self.deadline: Optional[float] = None
        self.verifying = False

    def view(self) -> RequestView:
        return RequestView(self.key, self.provider_id, self.queued_at,
                           self.sent_at, self.deadline, self.verifying)


class PipelineManager:
    def __init__(self, num_pieces, *, initially_owned=(), config=None):
        if not is_int(num_pieces) or num_pieces <= 0:
            raise ValueError("num_pieces must be a positive integer")
        if config is None:
            config = PipelineConfig()
        elif not isinstance(config, PipelineConfig):
            raise ValueError("config must be a PipelineConfig")
        if isinstance(initially_owned, (str, bytes)):
            raise ValueError("initially_owned must be an iterable of ints")
        try:
            items = list(initially_owned)
        except TypeError:
            raise ValueError("initially_owned must be an iterable of ints")
        for i in items:
            if not is_int(i) or not 0 <= i < num_pieces:
                raise ValueError(f"invalid initially owned piece {i!r}")
        self._n = num_pieces
        self._cfg = config
        self._owned: Set[int] = set(items)
        self._pending: Dict[RequestKey, _Req] = {}
        self._by_piece: Dict[int, Set[RequestKey]] = {}
        self._counts: Dict[int, int] = {}
        self._conns: Dict[int, _Conn] = {}
        self._providers: Dict[str, int] = {}
        self._ever: Set[int] = set()  # session-lifetime retired + active IDs
        self._next_request_id = 1
        self._last_now: Optional[float] = None
        self._cursor: Optional[int] = None
        self._stats = {"issued": 0, "completed": 0, "invalid": 0,
                       "expired": 0, "canceled": 0}

    # ---------------------------------------------------------- helpers
    def _check_now(self, now) -> None:
        if not is_time(now):
            raise ValueError("now must be a finite nonnegative number")
        if self._last_now is not None and now < self._last_now:
            raise ValueError("time went backward")

    def _tick(self, now) -> None:
        self._last_now = now

    def _conn(self, connection_id) -> _Conn:
        if not is_int(connection_id) or connection_id not in self._conns:
            raise ValueError(f"unknown or inactive connection {connection_id!r}")
        return self._conns[connection_id]

    def _check_piece(self, piece_index) -> None:
        if not is_int(piece_index) or not 0 <= piece_index < self._n:
            raise ValueError(f"piece index out of range: {piece_index!r}")

    @staticmethod
    def _check_key(key) -> None:
        if not isinstance(key, RequestKey):
            raise ValueError("key must be a RequestKey")

    @staticmethod
    def _check_reason(reason) -> None:
        if not isinstance(reason, str) or not reason:
            raise ValueError("reason must be a nonempty string")

    def _piece_state(self, piece: int) -> PieceState:
        if piece in self._owned:
            return PieceState.HAVE
        keys = self._by_piece.get(piece)
        if keys:
            if any(self._pending[k].verifying for k in keys):
                return PieceState.VERIFYING
            return PieceState.REQUESTED
        return PieceState.MISSING

    def _eligible(self, cid: int, conn: _Conn, piece: int,
                  allow_duplicate: bool) -> bool:
        if not (conn.interested and conn.unchoked):
            return False
        if piece in self._owned or piece not in conn.available:
            return False
        if self._counts[cid] >= self._cfg.window:
            return False
        keys = self._by_piece.get(piece)
        if not keys:
            return True
        if not allow_duplicate:
            return False
        if len(keys) >= self._cfg.max_copies or len(keys) >= 2:
            return False
        for k in keys:
            r = self._pending[k]
            if (r.verifying or k.connection_id == cid
                    or r.provider_id == conn.provider_id):
                return False
        return True

    def _create(self, cid: int, conn: _Conn, piece: int, now) -> RequestView:
        key = RequestKey(cid, self._next_request_id, piece)
        self._next_request_id += 1
        req = _Req(key, conn.provider_id, now)
        self._pending[key] = req
        self._by_piece.setdefault(piece, set()).add(key)
        self._counts[cid] += 1
        self._stats["issued"] += 1
        return req.view()

    def _remove(self, key: RequestKey) -> _Req:
        req = self._pending.pop(key)
        if key.connection_id in self._counts:
            self._counts[key.connection_id] -= 1
        keys = self._by_piece.get(key.piece_index)
        if keys is not None:
            keys.discard(key)
            if not keys:
                del self._by_piece[key.piece_index]
        return req

    def _finish(self, kind: str, key: RequestKey, reason: str, now) -> Outcome:
        self._remove(key)
        self._stats[kind] += 1
        return Outcome(kind, key, reason, now)

    def _sorted_keys(self, keys: Iterable[RequestKey]) -> List[RequestKey]:
        return sorted(keys, key=lambda k: k.request_id)

    # ------------------------------------------------------ connections
    def register_connection(self, connection_id, provider_id, *, now) -> None:
        self._check_now(now)
        if not is_int(connection_id) or connection_id <= 0:
            raise ValueError("connection_id must be a positive integer")
        if not isinstance(provider_id, str) or not provider_id:
            raise ValueError("provider_id must be a nonempty string")
        if connection_id in self._ever:
            raise ValueError(f"connection id {connection_id} already used")
        if provider_id in self._providers:
            raise ValueError(f"provider {provider_id!r} already connected")
        if len(self._conns) >= self._cfg.max_connections:
            raise ValueError("connection cap reached")
        self._tick(now)
        self._conns[connection_id] = _Conn(provider_id)
        self._counts[connection_id] = 0
        self._providers[provider_id] = connection_id
        self._ever.add(connection_id)

    def set_available(self, connection_id, piece_indices, *, now) -> None:
        self._check_now(now)
        conn = self._conn(connection_id)
        if isinstance(piece_indices, (str, bytes)):
            raise ValueError("piece_indices must be an iterable of ints")
        try:
            items = list(piece_indices)
        except TypeError:
            raise ValueError("piece_indices must be an iterable of ints")
        for i in items:
            self._check_piece(i)
        self._tick(now)
        conn.available = set(items)

    def set_permissions(self, connection_id, *, interested, unchoked,
                        now) -> Tuple[Outcome, ...]:
        self._check_now(now)
        conn = self._conn(connection_id)
        if not isinstance(interested, bool) or not isinstance(unchoked, bool):
            raise ValueError("interested and unchoked must be booleans")
        self._tick(now)
        revoked = ((conn.interested and not interested)
                   or (conn.unchoked and not unchoked))
        conn.interested = interested
        conn.unchoked = unchoked
        out: List[Outcome] = []
        if revoked:
            keys = [k for k, r in self._pending.items()
                    if k.connection_id == connection_id and not r.verifying]
            for k in self._sorted_keys(keys):
                out.append(self._finish("canceled", k, "permission_revoked",
                                        now))
        return tuple(out)

    def disconnect(self, connection_id, *, now) -> Tuple[Outcome, ...]:
        self._check_now(now)
        if not is_int(connection_id):
            raise ValueError("connection_id must be an integer")
        self._tick(now)
        conn = self._conns.get(connection_id)
        if conn is None:
            return ()
        keys = [k for k in self._pending if k.connection_id == connection_id]
        out = [self._finish("canceled", k, "disconnected", now)
               for k in self._sorted_keys(keys)]
        del self._conns[connection_id]
        del self._counts[connection_id]
        del self._providers[conn.provider_id]
        return tuple(out)

    # ------------------------------------------------------ reservation
    def reserve(self, connection_id, piece_index, *, now,
                allow_duplicate=False) -> Optional[RequestView]:
        self._check_now(now)
        conn = self._conn(connection_id)
        self._check_piece(piece_index)
        if not isinstance(allow_duplicate, bool):
            raise ValueError("allow_duplicate must be a boolean")
        self._tick(now)
        if not self._eligible(connection_id, conn, piece_index,
                              allow_duplicate):
            return None
        return self._create(connection_id, conn, piece_index, now)

    def fill(self, candidate_orders, *, now) -> Tuple[RequestView, ...]:
        self._check_now(now)
        if not isinstance(candidate_orders, Mapping):
            raise ValueError("candidate_orders must be a mapping")
        orders: Dict[int, List[int]] = {}
        for cid, cands in candidate_orders.items():
            self._conn(cid)
            if isinstance(cands, (str, bytes)):
                raise ValueError("candidates must be a sequence of ints")
            try:
                lst = list(cands)
            except TypeError:
                raise ValueError("candidates must be a sequence of ints")
            for p in lst:
                self._check_piece(p)
            if len(set(lst)) != len(lst):
                raise ValueError("candidate pieces must be distinct")
            orders[cid] = lst
        self._tick(now)

        ids = sorted(self._conns)
        if not ids:
            return ()
        start = 0
        if self._cursor is not None:
            for n, i in enumerate(ids):
                if i > self._cursor:
                    start = n
                    break
        ids = ids[start:] + ids[:start]
        self._cursor = ids[0]

        pos = {c: 0 for c in ids if c in orders}
        active = [c for c in ids if c in orders]
        created: List[RequestView] = []
        window = self._cfg.window
        while active:
            nxt = []
            for c in active:
                conn = self._conns[c]
                lst = orders[c]
                made = False
                while pos[c] < len(lst) and self._counts[c] < window:
                    p = lst[pos[c]]
                    pos[c] += 1
                    if self._eligible(c, conn, p, False):
                        created.append(self._create(c, conn, p, now))
                        made = True
                        break
                if made and pos[c] < len(lst) and self._counts[c] < window:
                    nxt.append(c)
            active = nxt
        return tuple(created)

    # ----------------------------------------------- deadlines / events
    def confirm_sent(self, key, *, sent_at, now) -> bool:
        self._check_now(now)
        self._check_key(key)
        if not is_time(sent_at) or sent_at > now:
            raise ValueError("sent_at must be finite, nonnegative, <= now")
        req = self._pending.get(key)
        if req is not None and sent_at < req.queued_at:
            raise ValueError("sent_at precedes request enqueue time")
        self._tick(now)
        if req is None:
            return False
        if req.sent_at is None:
            req.sent_at = sent_at
            if not req.verifying:
                req.deadline = sent_at + self._cfg.response_timeout
        return True

    def expire(self, *, now) -> Tuple[Outcome, ...]:
        self._check_now(now)
        self._tick(now)
        due = []
        for k, r in self._pending.items():
            if r.verifying:
                continue
            if r.sent_at is None:
                if now - r.queued_at >= self._cfg.send_confirm_timeout:
                    due.append((k, "send_unconfirmed"))
            elif r.deadline is not None and now >= r.deadline:
                due.append((k, "response_timeout"))
        due.sort(key=lambda t: t[0].request_id)
        return tuple(self._finish("expired", k, why, now) for k, why in due)

    # ------------------------------------------------------ verification
    def start_verification(self, key, *, now) -> bool:
        self._check_now(now)
        self._check_key(key)
        self._tick(now)
        req = self._pending.get(key)
        if req is None or req.verifying:
            return False
        for k in self._by_piece.get(key.piece_index, ()):
            if self._pending[k].verifying:
                return False
        req.verifying = True
        req.deadline = None
        return True

    def finish_verification(self, key, *, valid, now) -> Tuple[Outcome, ...]:
        self._check_now(now)
        self._check_key(key)
        if not isinstance(valid, bool):
            raise ValueError("valid must be a boolean")
        self._tick(now)
        req = self._pending.get(key)
        if req is None or not req.verifying:
            return ()
        if not valid:
            return (self._finish("invalid", key, "verification_failed", now),)
        piece = key.piece_index
        out = [self._finish("completed", key, "verified", now)]
        self._owned.add(piece)
        others = self._sorted_keys(self._by_piece.get(piece, ()))
        for k in others:
            out.append(self._finish("canceled", k, "another_request_completed",
                                    now))
        return tuple(out)

    # ----------------------------------------------------------- cleanup
    def reject(self, key, *, now) -> Tuple[Outcome, ...]:
        return self._drop_unanswered(key, "rejected", now)

    def send_failed(self, key, *, reason, now) -> Tuple[Outcome, ...]:
        self._check_reason(reason)
        return self._drop_unanswered(key, reason, now)

    def _drop_unanswered(self, key, reason, now) -> Tuple[Outcome, ...]:
        self._check_now(now)
        self._check_key(key)
        self._tick(now)
        req = self._pending.get(key)
        if req is None or req.verifying:
            return ()
        return (self._finish("canceled", key, reason, now),)

    def cancel(self, key, *, reason, now) -> Tuple[Outcome, ...]:
        self._check_now(now)
        self._check_key(key)
        self._check_reason(reason)
        self._tick(now)
        if key not in self._pending:
            return ()
        return (self._finish("canceled", key, reason, now),)

    # ---------------------------------------------------------- snapshot
    def snapshot(self) -> dict:
        counts = {s.value: 0 for s in PieceState}
        for p in range(self._n):
            counts[self._piece_state(p).value] += 1
        conns = []
        for cid in sorted(self._conns):
            c = self._conns[cid]
            conns.append({"connection_id": cid, "provider_id": c.provider_id,
                          "available": sorted(c.available),
                          "interested": c.interested,
                          "unchoked": c.unchoked})
        pending = [self._pending[k].view().to_dict()
                   for k in self._sorted_keys(self._pending)]
        return {
            "num_pieces": self._n,
            "owned": sorted(self._owned),
            "piece_state_counts": counts,
            "connections": conns,
            "pending": pending,
            "outstanding": [{"connection_id": c, "count": self._counts[c]}
                            for c in sorted(self._counts)],
            "counters": dict(self._stats),
            "retired_connection_ids": len(self._ever) - len(self._conns),
        }
