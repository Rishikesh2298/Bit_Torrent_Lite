"""Failure ledger, candidate ranking, and additional-request eligibility."""

from __future__ import annotations

import random
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

from .config import (RecoveryConfig, check_bool, check_int, is_finite_number,
                     is_int)
from .selection import order_pieces

RETRY_KINDS = ("response_timeout", "reject")
LOCAL_KINDS = ("enqueue_failed", "send_failed", "send_unconfirmed")
COUNTER_ONLY_KINDS = ("choke", "disconnect")
ALL_KINDS = RETRY_KINDS + ("invalid_piece",) + LOCAL_KINDS + COUNTER_ONLY_KINDS
PENDING_KEYS = {"request_id", "provider", "piece", "queued_at", "sent_at",
                "verifying"}
MAX_PROVIDER_LEN = 128


class CapacityError(RuntimeError):
    """Raised when retaining a new penalty would exceed a configured limit."""


class RecoveryPolicy:
    def __init__(self, num_pieces: int, config: Optional[RecoveryConfig] = None,
                 *, seed: int = 0) -> None:
        check_int("num_pieces", num_pieces, lo=1, hi=65536)
        if config is None:
            config = RecoveryConfig()
        elif not isinstance(config, RecoveryConfig):
            raise ValueError("config must be a RecoveryConfig or None")
        check_int("seed", seed)
        self._n = num_pieces
        self._cfg = config
        self._rng = random.Random(seed)
        self._last_now = 0.0
        self._owned: set = set()
        self._records: Dict[Tuple[str, int], Dict[str, Any]] = {}
        self._provider_counts: Dict[str, int] = {}
        self._counters = {k: 0 for k in ALL_KINDS}
        self._successes = 0
        self._events: deque = deque(maxlen=config.recent_event_limit or None)
        self._event_total = 0

    # ---- validation helpers -------------------------------------------
    def _check_now(self, now: Any) -> None:
        if not is_finite_number(now) or now < 0:
            raise ValueError("now must be a finite nonnegative number")
        if now < self._last_now:
            raise ValueError("now must not be earlier than the last accepted time")

    @staticmethod
    def _check_provider(provider: Any) -> None:
        if (not isinstance(provider, str) or not provider
                or len(provider) > MAX_PROVIDER_LEN):
            raise ValueError("provider must be a nonempty string of at most "
                             f"{MAX_PROVIDER_LEN} characters")

    def _check_piece(self, piece: Any, name: str = "piece") -> None:
        check_int(name, piece, lo=0, hi=self._n - 1)

    def _blocked(self, provider: str, piece: int, now: float) -> bool:
        rec = self._records.get((provider, piece))
        return rec is not None and (rec["excluded"] or now < rec["deadline"])

    # ---- ledger -------------------------------------------------------
    def _check_capacity(self, provider: str) -> None:
        if len(self._records) + 1 > self._cfg.max_penalty_entries:
            raise CapacityError("max_penalty_entries reached")
        if (provider not in self._provider_counts
                and len(self._provider_counts) + 1 > self._cfg.max_penalty_providers):
            raise CapacityError("max_penalty_providers reached")

    def _log(self, now: float, event: str, provider: str, piece: int,
             kind: Optional[str] = None) -> None:
        entry: Dict[str, Any] = {"seq": self._event_total, "at": now,
                                 "event": event, "provider": provider,
                                 "piece": piece}
        if kind is not None:
            entry["kind"] = kind
        self._event_total += 1
        if self._cfg.recent_event_limit > 0:
            self._events.append(entry)

    def failed(self, *, now: float, provider: str, piece: int, kind: str) -> None:
        self._check_now(now)
        self._check_provider(provider)
        self._check_piece(piece)
        if not isinstance(kind, str) or kind not in ALL_KINDS:
            raise ValueError(f"unknown failure kind; expected one of {', '.join(ALL_KINDS)}")
        if piece in self._owned:
            self._last_now = now
            return
        key = (provider, piece)
        rec = self._records.get(key)
        creates = kind not in COUNTER_ONLY_KINDS and rec is None
        if creates:
            self._check_capacity(provider)
        # ---- mutation begins ----
        if creates:
            rec = {"streak": 0, "deadline": 0.0, "excluded": False,
                   "reason": kind, "at": now}
            self._records[key] = rec
            self._provider_counts[provider] = self._provider_counts.get(provider, 0) + 1
        if kind in RETRY_KINDS:
            delays = self._cfg.retry_delays
            rec["streak"] += 1
            delay = delays[min(rec["streak"], len(delays)) - 1]
            rec["deadline"] = max(rec["deadline"], float(now) + delay)
        elif kind in LOCAL_KINDS:
            rec["deadline"] = max(rec["deadline"],
                                  float(now) + self._cfg.local_send_cooldown)
        elif kind == "invalid_piece":
            rec["excluded"] = True
        if rec is not None and kind not in COUNTER_ONLY_KINDS:
            rec["reason"] = kind
            rec["at"] = now
        self._counters[kind] += 1
        self._log(now, "failed", provider, piece, kind)
        self._last_now = now

    def succeeded(self, *, now: float, provider: str, piece: int) -> None:
        self._check_now(now)
        self._check_provider(provider)
        self._check_piece(piece)
        if piece in self._owned:
            self._last_now = now
            return
        self._owned.add(piece)
        for key in [k for k in self._records if k[1] == piece]:
            del self._records[key]
            remaining = self._provider_counts[key[0]] - 1
            if remaining:
                self._provider_counts[key[0]] = remaining
            else:
                del self._provider_counts[key[0]]
        self._successes += 1
        self._log(now, "succeeded", provider, piece)
        self._last_now = now

    # ---- selection ----------------------------------------------------
    def rank_candidates(self, *, now: float, provider: str,
                        candidates: List[int], availability: List[int]) -> List[int]:
        self._check_now(now)
        self._check_provider(provider)
        if not isinstance(candidates, list):
            raise ValueError("candidates must be a list")
        for c in candidates:
            self._check_piece(c, "candidate")
        if len(set(candidates)) != len(candidates):
            raise ValueError("candidates must be distinct")
        if not isinstance(availability, list) or len(availability) != self._n:
            raise ValueError(f"availability must be a list of exactly {self._n} integers")
        for a in availability:
            check_int("availability entry", a, lo=0)
        eligible = [c for c in candidates
                    if c not in self._owned and availability[c] > 0
                    and not self._blocked(provider, c, now)]
        result = order_pieces(self._cfg.strategy, eligible, availability, self._rng)
        self._last_now = now
        return result

    # ---- additional request -------------------------------------------
    def allow_duplicate(self, *, now: float, piece: int, provider: str,
                        pending: List[dict], missing_count: int,
                        no_unreserved_candidates: bool) -> bool:
        self._check_now(now)
        self._check_piece(piece)
        self._check_provider(provider)
        if not isinstance(pending, list):
            raise ValueError("pending must be a list")
        if len(pending) > 2:
            raise ValueError("pending may contain at most two entries")
        identities = set()
        for entry in pending:
            if not isinstance(entry, dict) or set(entry) != PENDING_KEYS:
                raise ValueError("each pending entry must be a dict with exactly "
                                 + ", ".join(sorted(PENDING_KEYS)))
            check_int("request_id", entry["request_id"], lo=1)
            self._check_provider(entry["provider"])
            self._check_piece(entry["piece"], "pending piece")
            if entry["piece"] != piece:
                raise ValueError("every pending entry must describe the requested piece")
            check_bool("verifying", entry["verifying"])
            q, s = entry["queued_at"], entry["sent_at"]
            if not is_finite_number(q) or not 0 <= q <= now:
                raise ValueError("queued_at must satisfy 0 <= queued_at <= now")
            if s is not None and (not is_finite_number(s) or not q <= s <= now):
                raise ValueError("sent_at must be None or satisfy queued_at <= sent_at <= now")
            ident = (entry["provider"], entry["request_id"])
            if ident in identities:
                raise ValueError("pending (provider, request_id) identities must be distinct")
            identities.add(ident)
        check_int("missing_count", missing_count, lo=0, hi=self._n)
        check_bool("no_unreserved_candidates", no_unreserved_candidates)

        cfg = self._cfg
        self._last_now = now
        if not cfg.endgame_enabled or cfg.max_copies != 2 or piece in self._owned:
            return False
        if not 1 <= missing_count <= cfg.endgame_remaining or not no_unreserved_candidates:
            return False
        if len(pending) != 1:
            return False
        req = pending[0]
        if req["sent_at"] is None or req["verifying"]:
            return False
        if now - req["sent_at"] < cfg.endgame_min_age:
            return False
        if provider == req["provider"] or self._blocked(provider, piece, now):
            return False
        return True

    # ---- diagnostics --------------------------------------------------
    def snapshot(self, *, now: float) -> Dict[str, Any]:
        self._check_now(now)
        penalties = []
        for (prov, piece) in sorted(self._records):
            rec = self._records[(prov, piece)]
            penalties.append({
                "provider": prov, "piece": piece, "streak": rec["streak"],
                "cooldown_deadline": rec["deadline"],
                "cooldown_remaining": max(0.0, rec["deadline"] - now),
                "excluded": rec["excluded"], "reason": rec["reason"],
                "last_at": rec["at"],
            })
        snap = {
            "config": self._cfg.to_dict(),
            "num_pieces": self._n,
            "owned": sorted(self._owned),
            "counters": dict(self._counters),
            "successes": self._successes,
            "penalty_entry_count": len(self._records),
            "penalty_provider_count": len(self._provider_counts),
            "penalties": penalties,
            "recent_events": [dict(e) for e in self._events],
            "omitted_events": self._event_total - len(self._events),
        }
        self._last_now = now
        return snap
