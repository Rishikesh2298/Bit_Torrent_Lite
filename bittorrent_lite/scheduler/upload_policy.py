"""Original project policy using the standalone policy's acknowledged slot engine.

Selection uses interval totals and a stable rotating order, not the standalone
library's rolling-window/random selection. Permission tokens and reservations
still use the same tested acknowledgement lifecycle.
"""
from choking_policy import Config, Policy


class ProjectUploadPolicy(Policy):
    def __init__(self, config=None):
        config = config or Config(optimistic_interval=5)
        if config.max_slots != 2 or config.selection_interval != 5:
            raise ValueError("project policy requires two slots and five-second intervals")
        super().__init__(config)
        self._cursor = None
        self._interval_end = None

    def _score(self, peer, value):
        # Contributions are reset only at policy interval boundaries.
        total = sum(peer.buckets.values())
        peer.buckets.clear()
        if total:
            peer.buckets[0] = total
        return total

    def _recompute(self, value):
        due = self._interval_end is None or value >= self._interval_end
        eligible = sorted(pid for pid, p in self._peers.items() if p.interested)
        order = eligible
        if self._cursor is not None:
            order = [p for p in eligible if p > self._cursor] + [
                p for p in eligible if p <= self._cursor]
        if self._seeder:
            chosen = order[:2]
        elif order:
            best = max(self._score(self._peers[p], value) for p in order)
            regular = next(p for p in order if self._score(self._peers[p], value) == best)
            chosen = [regular] + [p for p in order if p != regular][:1]
        else:
            chosen = []
        if not due:
            # Membership changes fill vacancies without rotating full healthy slots.
            incumbents = [pid for pid in self._regular + [self._optimistic]
                          if pid in eligible]
            chosen = incumbents + [pid for pid in chosen if pid not in incumbents]
            chosen = chosen[:2]
        if chosen:
            self._cursor = chosen[-1]
        self._regular = chosen[:1]
        self._optimistic = chosen[1] if len(chosen) > 1 else None
        for pid, peer in self._peers.items():
            peer.desired = pid in chosen
        if due:
            for peer in self._peers.values():
                peer.buckets.clear()
            self._interval_end = value + 5
        self._next_sel = self._interval_end
        self._next_opt = self._interval_end
        self._dirty = False

    def reset(self, now):
        super().reset(now)
        self._cursor = None
        self._interval_end = None
