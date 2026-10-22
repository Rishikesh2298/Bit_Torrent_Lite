"""
Tracker State — Debargha's Module

In-memory swarm membership. tracker_server.py handles HTTP; this module
holds the table and applies announce events. It does no I/O, so it can be
tested with a fake clock.

Data model:
    key   = (file_id, peer_id)
    value = MemberRecord(ip, port, last_seen, completed)

Rules (bittorrent_lite/docs/debargha/tracker.md):
    started / update -> insert or refresh (an update after a tracker restart
                        recreates the record)
    completed        -> insert or refresh and mark completed
    stopped          -> remove if present; repeating it is harmless
    An entry whose age is at least the expiry time is removed before any
    response is built. Expiry is a timeout heuristic, not proof of death.

Concurrency:
    The tracker uses a single-threaded HTTP server, so only one request
    touches this table at a time and no lock is needed. If the server is ever
    made threaded, add a lock around every method.
"""

import time
from dataclasses import dataclass

from bittorrent_lite.common.config import TRACKER_PEER_TIMEOUT
from bittorrent_lite.common.types import PeerRecord

EVENTS = ("started", "update", "completed", "stopped")


@dataclass
class MemberRecord:
    """One live peer in one swarm."""

    ip: str
    port: int
    last_seen: float
    completed: bool = False


class TrackerState:
    """
    Membership table for all swarms served by one tracker.

    Args:
        expiry_seconds: Age at which an entry is considered dead.
        clock: Monotonic time source; tests pass a fake.
    """

    def __init__(self, expiry_seconds: float = TRACKER_PEER_TIMEOUT,
                 clock=time.monotonic):
        self.expiry_seconds = expiry_seconds
        self._clock = clock
        self._members: dict[tuple[str, str], MemberRecord] = {}

    def announce(self, file_id: str, peer_id: str, ip: str, port: int,
                 event: str) -> list[PeerRecord]:
        """
        Apply one validated announce and return the other live peers.

        Inputs must already be validated by the server. The response for a
        stopped peer is still computed (it is usually ignored).
        """
        if event not in EVENTS:
            raise ValueError(f"unknown event {event!r}")

        now = self._clock()
        self.expire(now)
        key = (file_id, peer_id)

        if event == "stopped":
            self._members.pop(key, None)
        else:
            record = self._members.get(key)
            completed = event == "completed" or (record is not None and record.completed)
            # One peer ID has one current endpoint per file: replace the record.
            self._members[key] = MemberRecord(ip, port, now, completed)

        return self.peers_for(file_id, exclude_peer_id=peer_id, now=now)

    def expire(self, now: float | None = None) -> list[tuple[str, str]]:
        """Remove entries whose age is at least the expiry time."""
        if now is None:
            now = self._clock()
        expired = [key for key, record in self._members.items()
                   if now - record.last_seen >= self.expiry_seconds]
        for key in expired:
            del self._members[key]
        return expired

    def peers_for(self, file_id: str, exclude_peer_id: str = "",
                  now: float | None = None) -> list[PeerRecord]:
        """Live peers of one file, excluding the requester, sorted by peer ID."""
        self.expire(now)
        return [PeerRecord(peer_id=peer_id, ip=record.ip, port=record.port)
                for (fid, peer_id), record in sorted(self._members.items())
                if fid == file_id and peer_id != exclude_peer_id]

    def get(self, file_id: str, peer_id: str) -> MemberRecord | None:
        """Return a copy of one record, or None."""
        record = self._members.get((file_id, peer_id))
        if record is None:
            return None
        return MemberRecord(record.ip, record.port, record.last_seen, record.completed)

    def peer_count(self, file_id: str | None = None) -> int:
        """Number of stored entries, optionally for one file (expired ones included until next expire)."""
        if file_id is None:
            return len(self._members)
        return sum(1 for fid, _ in self._members if fid == file_id)
