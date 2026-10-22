"""Legacy Part 1 API; Coordinator uses bittorrent_lite.scheduling.request_pipeline.PipelineManager.

Retained for existing direct callers. New lifecycle integrations should use
PipelineManager, which owns permissions, connections and verified ownership.
"""
import itertools
import math
from typing import Optional

from bittorrent_lite.common.interfaces import Clock
from bittorrent_lite.scheduling.models import PendingRequest
from bittorrent_lite.scheduling.models import SchedulerConfig

Key = tuple[int, int, int]  # connection id, request id, piece index


def _key(req: PendingRequest) -> Key:
    return (req.connection_id, req.request_id, req.piece_index)


class RequestManager:
    def __init__(self, clock: Clock, config: SchedulerConfig):
        self._clock = clock
        self._config = config
        self._ids = itertools.count(1)
        self._pending: dict[Key, PendingRequest] = {}
        self._reserved: dict[int, Key] = {}
        self._outstanding: dict[int, int] = {}

    def can_request(self, connection_id: int) -> bool:
        return self.outstanding_count(connection_id) < self._config.request_window

    def outstanding_count(self, connection_id: int) -> int:
        return self._outstanding.get(connection_id, 0)

    def reserved_pieces(self) -> frozenset[int]:
        return frozenset(self._reserved)

    def reserve(self, connection_id: int, piece_index: int) -> Optional[PendingRequest]:
        if type(piece_index) is not int or piece_index < 0:
            raise ValueError("piece index must be a nonnegative integer")
        if piece_index in self._reserved or not self.can_request(connection_id):
            return None
        req = PendingRequest(
            request_id=next(self._ids),
            connection_id=connection_id,
            piece_index=piece_index,
            queued_at=self._clock.now(),
        )
        key = _key(req)
        self._pending[key] = req
        self._reserved[piece_index] = key
        self._outstanding[connection_id] = self.outstanding_count(connection_id) + 1
        return req

    def get(self, connection_id: int, request_id: int, piece_index: int) -> Optional[PendingRequest]:
        return self._pending.get((connection_id, request_id, piece_index))

    def mark_sent(self, connection_id: int, request_id: int, piece_index: int, sent_at: float) -> bool:
        req = self.get(connection_id, request_id, piece_index)
        if req is None or req.sent_at is not None:
            return False
        if (type(sent_at) not in (int, float) or not math.isfinite(sent_at)
                or sent_at < req.queued_at):
            raise ValueError("send time must be finite and no earlier than enqueue")
        req.sent_at = sent_at
        if not req.verifying:
            req.deadline = sent_at + self._config.response_timeout
        return True

    def mark_verifying(self, connection_id: int, request_id: int, piece_index: int) -> bool:
        req = self.get(connection_id, request_id, piece_index)
        if req is None:
            return False
        req.verifying = True
        req.deadline = None
        return True

    def complete(self, connection_id: int, request_id: int, piece_index: int) -> Optional[PendingRequest]:
        return self._remove((connection_id, request_id, piece_index))

    def cancel(self, connection_id: int, request_id: int, piece_index: int) -> Optional[PendingRequest]:
        return self._remove((connection_id, request_id, piece_index))

    def cancel_connection(self, connection_id: int) -> list[PendingRequest]:
        keys = [k for k in self._pending if k[0] == connection_id]
        return [r for r in (self._remove(k) for k in keys) if r is not None]

    def get_expired(self, now: float) -> list[PendingRequest]:
        return [
            r
            for r in self._pending.values()
            if r.sent_at is not None and not r.verifying and r.deadline is not None and now >= r.deadline
        ]

    def get_unsent_expired(self, now: float) -> list[PendingRequest]:
        limit = self._config.send_confirm_timeout
        return [r for r in self._pending.values()
                if r.sent_at is None and not r.verifying and now - r.queued_at >= limit]

    def all_pending(self) -> list[PendingRequest]:
        return list(self._pending.values())

    def _remove(self, key: Key) -> Optional[PendingRequest]:
        req = self._pending.pop(key, None)
        if req is None:
            return None
        self._reserved.pop(req.piece_index, None)
        left = self._outstanding.get(req.connection_id, 0) - 1
        if left > 0:
            self._outstanding[req.connection_id] = left
        else:
            self._outstanding.pop(req.connection_id, None)
        return req
