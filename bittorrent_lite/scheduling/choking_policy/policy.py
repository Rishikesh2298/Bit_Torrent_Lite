"""Upload-permission policy engine (standard library only)."""

from __future__ import annotations

import math
import random
from collections import deque
from typing import Callable

from bittorrent_lite.scheduling.choking_policy.models import Config
from bittorrent_lite.scheduling.choking_policy.models import Decision
from bittorrent_lite.scheduling.choking_policy.models import Diagnostic
from bittorrent_lite.scheduling.choking_policy.models import PeerInfo
from bittorrent_lite.scheduling.choking_policy.models import PeerSnapshot
from bittorrent_lite.scheduling.choking_policy.models import PermissionIntent
from bittorrent_lite.scheduling.choking_policy.models import Snapshot

MAX_PEER_ID_LENGTH = 128
MAX_EVENT_BYTES = 16_777_216


class _Peer:
    __slots__ = (
        "peer_id", "interested", "desired", "confirmed", "pending", "overdue",
        "buckets", "allowed", "last_grant", "connected_at",
    )

    def __init__(self, peer_id: str, interested: bool, connected_at: float) -> None:
        self.peer_id = peer_id
        self.interested = interested
        self.desired = False
        self.confirmed = False
        self.pending: PermissionIntent | None = None
        self.overdue = False
        self.buckets: dict[int, int] = {}
        self.allowed = 0.0
        self.last_grant: float | None = None
        self.connected_at = connected_at


def _check_peer_id(peer_id: object) -> str:
    if not isinstance(peer_id, str) or not 1 <= len(peer_id) <= MAX_PEER_ID_LENGTH:
        raise ValueError("peer_id must be a nonempty string of at most 128 characters")
    return peer_id


def _check_bool(name: str, value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


class Policy:
    """Deterministic choking policy; see README.md for the full contract."""

    def __init__(self, config: Config = Config()) -> None:
        if not isinstance(config, Config):
            raise ValueError("config must be a Config")
        self._cfg = config
        self._now = 0.0
        self._epoch = 1
        self._peers: dict[str, _Peer] = {}
        self._init_state()

    # ------------------------------------------------------------ internals

    def _init_state(self) -> None:
        self._peers = {}
        self._counter = 0
        self._tokens: dict[str, str] = {}
        self._diag: deque[Diagnostic] = deque(maxlen=self._cfg.diagnostic_capacity)
        self._rng = random.Random(self._cfg.random_seed)
        self._upload = True
        self._seeder = False
        self._closing = False
        self._closed = False
        self._regular: list[str] = []
        self._optimistic: str | None = None
        self._next_sel: float | None = None
        self._next_opt: float | None = None
        self._dirty = True

    def _check_now(self, now: object) -> float:
        if isinstance(now, bool) or not isinstance(now, (int, float)):
            raise ValueError("now must be a number")
        try:
            value = float(now)
        except OverflowError:
            raise ValueError("now must be finite") from None
        if not math.isfinite(value) or value < 0:
            raise ValueError("now must be finite and nonnegative")
        if value < self._now:
            raise ValueError("now must not decrease")
        return value

    def _begin(self, value: float) -> None:
        """Commit the clock: accrue service time, then report overdue intents."""
        dt = value - self._now
        if dt > 0:
            for peer in self._peers.values():
                if peer.confirmed:
                    peer.allowed += dt
            self._now = value
        for pid in sorted(self._peers):
            peer = self._peers[pid]
            pending = peer.pending
            if (
                pending is not None
                and not peer.overdue
                and value - pending.issued_at > self._cfg.confirmation_timeout
            ):
                peer.overdue = True
                self._diag.append(Diagnostic("confirmation_overdue", pid, value))

    def _score(self, peer: _Peer, value: float) -> int:
        low = math.floor(value) - self._cfg.contribution_window + 1
        for key in [k for k in peer.buckets if k < low]:
            del peer.buckets[key]
        return sum(peer.buckets.values())

    def _update_closed(self) -> None:
        if self._closing and not self._closed:
            if all(not p.confirmed and p.pending is None for p in self._peers.values()):
                self._closed = True

    def _clear_selection(self) -> None:
        for peer in self._peers.values():
            peer.desired = False
        self._regular = []
        self._optimistic = None
        self._next_sel = None
        self._next_opt = None
        self._dirty = True

    def _pick(self, candidates: list[str], count: int, key: Callable[[_Peer], tuple]) -> list[str]:
        keys = {pid: key(self._peers[pid]) for pid in candidates}
        remaining = list(candidates)
        chosen: list[str] = []
        while remaining and len(chosen) < count:
            best = min(keys[pid] for pid in remaining)
            tied = sorted(pid for pid in remaining if keys[pid] == best)
            choice = tied[0] if len(tied) == 1 else self._rng.choice(tied)
            chosen.append(choice)
            remaining.remove(choice)
        return chosen

    def _recompute(self, value: float) -> None:
        eligible = [pid for pid, p in self._peers.items() if p.interested]
        eligible_set = set(eligible)
        incumbent = self._optimistic if self._optimistic in eligible_set else None
        opt_due = (
            self._next_opt is None or value >= self._next_opt or incumbent is None
        )
        reserved_opt = incumbent if not opt_due else None
        candidates = [pid for pid in eligible if pid != reserved_opt]

        if self._seeder:
            def regular_key(p: _Peer) -> tuple:
                return (p.allowed,)
        else:
            def regular_key(p: _Peer) -> tuple:
                return (-self._score(p, value), p.allowed)

        regular = self._pick(candidates, self._cfg.max_slots - 1, regular_key)

        if opt_due:
            regular_set = set(regular)
            rest = [pid for pid in eligible if pid not in regular_set]
            previous = self._optimistic
            if previous in rest and len(rest) > 1:
                rest.remove(previous)

            def opt_key(p: _Peer) -> tuple:
                if p.last_grant is None:
                    return (0, p.connected_at)
                return (1, p.last_grant)

            picked = self._pick(rest, 1, opt_key)
            optimistic = picked[0] if picked else None
            self._next_opt = value + self._cfg.optimistic_interval
        else:
            optimistic = incumbent

        self._regular = regular
        self._optimistic = optimistic
        self._next_sel = value + self._cfg.selection_interval
        self._dirty = False
        selected = set(regular)
        if optimistic is not None:
            selected.add(optimistic)
        for pid, peer in self._peers.items():
            peer.desired = pid in selected

    def _new_intent(self, peer: _Peer, allow: bool, value: float) -> PermissionIntent:
        self._counter += 1
        token = f"{self._epoch}:{self._counter}"
        intent = PermissionIntent(token, peer.peer_id, allow, value)
        peer.pending = intent
        peer.overdue = False
        self._tokens[token] = peer.peer_id
        return intent

    def _issue(self, value: float) -> list[PermissionIntent]:
        intents: list[PermissionIntent] = []
        order = sorted(self._peers)
        for pid in order:
            peer = self._peers[pid]
            if peer.confirmed and not peer.desired and peer.pending is None:
                intents.append(self._new_intent(peer, False, value))
        reserved = sum(
            1 for p in self._peers.values()
            if p.confirmed or (p.pending is not None and p.pending.allow)
        )
        for pid in order:
            if reserved >= self._cfg.max_slots:
                break
            peer = self._peers[pid]
            if peer.desired and not peer.confirmed and peer.pending is None:
                intents.append(self._new_intent(peer, True, value))
                reserved += 1
        return intents

    def _snapshot(self, value: float) -> Snapshot:
        peers = []
        for pid in sorted(self._peers):
            p = self._peers[pid]
            peers.append(PeerSnapshot(
                peer_id=pid,
                interested=p.interested,
                desired=p.desired,
                confirmed=p.confirmed,
                reserved=p.confirmed or (p.pending is not None and p.pending.allow),
                recent_bytes=self._score(p, value),
                allowed_seconds=p.allowed,
                pending=p.pending,
            ))
        regular = tuple(sorted(pid for pid in self._regular if pid in self._peers))
        return Snapshot(
            now=value,
            upload_enabled=self._upload,
            seeder=self._seeder,
            closing=self._closing,
            closed=self._closed,
            peers=tuple(peers),
            regular=regular,
            optimistic=self._optimistic if self._optimistic in self._peers else None,
            diagnostics=tuple(self._diag),
        )

    def _require_open(self) -> None:
        if self._closing:
            raise RuntimeError("policy is shutting down")

    # ----------------------------------------------------------- public API

    def connect(self, peer: PeerInfo, now: float) -> None:
        value = self._check_now(now)
        if not isinstance(peer, PeerInfo):
            raise ValueError("peer must be a PeerInfo")
        pid = _check_peer_id(peer.peer_id)
        interested = _check_bool("interested", peer.interested)
        self._require_open()
        if pid in self._peers:
            raise ValueError(f"peer {pid!r} is already connected")
        if len(self._peers) >= self._cfg.max_peers:
            raise OverflowError("max_peers reached")
        self._begin(value)
        self._peers[pid] = _Peer(pid, interested, value)
        self._dirty = True

    def disconnect(self, peer_id: str, now: float) -> None:
        value = self._check_now(now)
        pid = _check_peer_id(peer_id)
        self._begin(value)
        peer = self._peers.pop(pid, None)
        if peer is None:
            return
        if peer.pending is not None:
            self._tokens.pop(peer.pending.token, None)
        if pid in self._regular:
            self._regular.remove(pid)
        if self._optimistic == pid:
            self._optimistic = None
        self._dirty = True
        self._update_closed()

    def set_interested(self, peer_id: str, interested: bool, now: float) -> None:
        value = self._check_now(now)
        pid = _check_peer_id(peer_id)
        _check_bool("interested", interested)
        self._require_open()
        if pid not in self._peers:
            raise KeyError(pid)
        self._begin(value)
        peer = self._peers[pid]
        if peer.interested != interested:
            peer.interested = interested
            self._dirty = True

    def record_contribution(self, peer_id: str, verified_bytes: int, now: float) -> None:
        value = self._check_now(now)
        pid = _check_peer_id(peer_id)
        if (
            isinstance(verified_bytes, bool)
            or not isinstance(verified_bytes, int)
            or not 1 <= verified_bytes <= MAX_EVENT_BYTES
        ):
            raise ValueError("verified_bytes must be an integer from 1 through 16777216")
        self._require_open()
        if pid not in self._peers:
            raise KeyError(pid)
        self._begin(value)
        peer = self._peers[pid]
        key = math.floor(value)
        peer.buckets[key] = peer.buckets.get(key, 0) + verified_bytes
        self._score(peer, value)  # prune expired buckets

    def set_seeder(self, seeder: bool, now: float) -> None:
        value = self._check_now(now)
        _check_bool("seeder", seeder)
        self._require_open()
        self._begin(value)
        if seeder != self._seeder:
            self._seeder = seeder
            self._dirty = True

    def set_upload_enabled(self, enabled: bool, now: float) -> None:
        value = self._check_now(now)
        _check_bool("enabled", enabled)
        self._require_open()
        self._begin(value)
        if enabled != self._upload:
            self._upload = enabled
            self._clear_selection()

    def tick(self, now: float) -> Decision:
        value = self._check_now(now)
        self._begin(value)
        if self._closing or not self._upload:
            pass  # desired selection is already empty
        else:
            due = (
                self._dirty
                or self._next_sel is None
                or value >= self._next_sel
                or (self._next_opt is not None and value >= self._next_opt)
            )
            if due:
                self._recompute(value)
        intents = self._issue(value)
        self._update_closed()
        return Decision(tuple(intents), self._snapshot(value))

    def acknowledge(self, token: str, applied: bool, now: float) -> bool:
        value = self._check_now(now)
        if not isinstance(token, str):
            raise ValueError("token must be a string")
        _check_bool("applied", applied)
        self._begin(value)
        pid = self._tokens.get(token)
        peer = self._peers.get(pid) if pid is not None else None
        if peer is None or peer.pending is None or peer.pending.token != token:
            self._diag.append(Diagnostic("unknown_ack", None, value))
            return False
        intent = peer.pending
        del self._tokens[token]
        peer.pending = None
        peer.overdue = False
        if applied:
            peer.confirmed = intent.allow
            if intent.allow:
                peer.last_grant = value
        else:
            self._diag.append(Diagnostic("command_not_applied", peer.peer_id, value))
        self._update_closed()
        return True

    def snapshot(self, now: float) -> Snapshot:
        value = self._check_now(now)
        self._begin(value)
        return self._snapshot(value)

    def shutdown(self, now: float) -> None:
        value = self._check_now(now)
        self._begin(value)
        self._closing = True
        self._clear_selection()
        self._update_closed()

    def reset(self, now: float) -> None:
        value = self._check_now(now)
        if not self._closed:
            raise RuntimeError("reset is allowed only when closed")
        self._begin(value)
        self._epoch += 1
        self._init_state()
