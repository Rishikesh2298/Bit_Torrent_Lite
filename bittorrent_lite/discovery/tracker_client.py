"""
Tracker Client and Discovery Worker — Debargha's Module

announce() performs one HTTP announce (contract in bittorrent_lite/docs/debargha/tracker.md).
DiscoveryWorker runs announce() on its own thread so the peer coordinator
never blocks on HTTP. It posts two kinds of events to the coordinator's
queue:

    PeersDiscovered(file_id, peers, time)   validated candidate peers
    TrackerError(category, detail, time)    one failed attempt

Candidates are not guarantees: a listed peer may already be gone, and the
connection layer must handle a failed connect.

Worker timing:
    announce at start, then every `interval` seconds (from the tracker,
    clamped to a sane range) after a success;
    after a failure wait 2, 4, then 10 seconds (config.TRACKER_RETRY_DELAYS),
    resetting after the next success.
All waits are on a threading.Event, so stop() interrupts them at once.

This module does NOT import the tracker server; it talks to it over HTTP.
"""

import ipaddress
import json
import queue
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from bittorrent_lite.common import run_log
from bittorrent_lite.common.config import ANNOUNCE_INTERVAL
from bittorrent_lite.common.config import HTTP_TIMEOUT
from bittorrent_lite.common.config import TRACKER_HOST
from bittorrent_lite.common.config import TRACKER_PORT
from bittorrent_lite.common.config import TRACKER_RETRY_DELAYS
from bittorrent_lite.common.logging import get_logger
from bittorrent_lite.common.types import PeerRecord

logger = get_logger("DISCOVERY")

MAX_RESPONSE_BYTES = 65_536
MIN_INTERVAL = 1             # never let a tracker response cause a tight loop
MAX_INTERVAL = 60
STOPPED_TIMEOUT = 1.0        # best-effort stopped announce must not delay exit
QUEUE_PUT_TIMEOUT = 1.0
ERROR_LOG_EVERY = 10         # repeat an unchanged console error every N failures

PEER_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,32}")
FILE_ID_RE = re.compile(r"[0-9a-f]{64}")


# ──────────────────────────────────────────────
# Events published to the coordinator
# ──────────────────────────────────────────────

@dataclass(frozen=True)
class PeersDiscovered:
    """Validated candidate peers for one file (self already removed)."""

    file_id: str
    peers: tuple[PeerRecord, ...]
    time: float


@dataclass(frozen=True)
class TrackerError:
    """One failed announce. category is unreachable|timeout|http_status|bad_response."""

    category: str
    detail: str
    time: float


class TrackerRequestError(Exception):
    """Raised by announce(); category matches TrackerError.category."""

    def __init__(self, category: str, detail: str):
        super().__init__(f"{category}: {detail}")
        self.category = category
        self.detail = detail


@dataclass(frozen=True)
class AnnounceResponse:
    interval: int
    peers: tuple[PeerRecord, ...]


# ──────────────────────────────────────────────
# One announce
# ──────────────────────────────────────────────

def build_tracker_url(host: str = TRACKER_HOST, port: int = TRACKER_PORT) -> str:
    """Build the tracker base URL from host and port."""
    return f"http://{host}:{port}"


def parse_response(raw: bytes, own_peer_id: str = "") -> AnnounceResponse:
    """
    Validate a tracker response body.

    Rejects the whole response if any field is malformed, since a tracker
    sending nonsense should not be half-trusted. Drops our own ID and
    duplicate peer IDs (first one wins).
    """
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise TrackerRequestError("bad_response", "body is not valid JSON")
    if not isinstance(data, dict):
        raise TrackerRequestError("bad_response", "body is not an object")

    interval = data.get("interval")
    if type(interval) is not int or interval <= 0:
        raise TrackerRequestError("bad_response", "interval must be a positive integer")

    raw_peers = data.get("peers")
    if not isinstance(raw_peers, list):
        raise TrackerRequestError("bad_response", "peers must be a list")

    peers, seen = [], set()
    for entry in raw_peers:
        if not isinstance(entry, dict):
            raise TrackerRequestError("bad_response", "peer entry is not an object")
        peer_id, ip, port = entry.get("peer_id"), entry.get("ip"), entry.get("port")
        if not isinstance(peer_id, str) or not PEER_ID_RE.fullmatch(peer_id):
            raise TrackerRequestError("bad_response", "invalid peer_id")
        try:
            address = ipaddress.IPv4Address(ip) if isinstance(ip, str) else None
        except ipaddress.AddressValueError:
            address = None
        if address is None or address.is_unspecified:
            raise TrackerRequestError("bad_response", f"invalid ip for {peer_id}")
        if type(port) is not int or not 1 <= port <= 65535:
            raise TrackerRequestError("bad_response", f"invalid port for {peer_id}")
        if peer_id == own_peer_id or peer_id in seen:
            continue
        seen.add(peer_id)
        peers.append(PeerRecord(peer_id=peer_id, ip=str(address), port=port))

    return AnnounceResponse(interval=interval, peers=tuple(peers))


def announce(tracker_url: str, file_id: str, peer_id: str, listen_port: int,
             event: str, timeout: float = HTTP_TIMEOUT) -> AnnounceResponse:
    """
    Send one announce and return the validated response.

    Raises:
        TrackerRequestError: on any network, HTTP or response problem.
    """
    body = json.dumps({
        "file_id": file_id, "peer_id": peer_id,
        "listen_port": listen_port, "event": event,
    }).encode("utf-8")
    request = urllib.request.Request(
        tracker_url.rstrip("/") + "/announce", data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        detail = f"HTTP {error.code}"
        try:
            detail += f" {json.loads(error.read(4096)).get('error', '')}".rstrip()
        except (ValueError, AttributeError, OSError):
            pass
        raise TrackerRequestError("http_status", detail)
    except (socket.timeout, TimeoutError):
        raise TrackerRequestError("timeout", f"no response within {timeout}s")
    except urllib.error.URLError as error:
        reason = error.reason
        if isinstance(reason, (socket.timeout, TimeoutError)):
            raise TrackerRequestError("timeout", f"no response within {timeout}s")
        raise TrackerRequestError("unreachable", str(reason))
    except (OSError, ValueError) as error:
        # ConnectionResetError, http.client errors, malformed URL ...
        raise TrackerRequestError("unreachable", str(error))

    if len(raw) > MAX_RESPONSE_BYTES:
        raise TrackerRequestError("bad_response", f"response exceeds {MAX_RESPONSE_BYTES} bytes")
    return parse_response(raw, own_peer_id=peer_id)


# ──────────────────────────────────────────────
# Background worker
# ──────────────────────────────────────────────

class DiscoveryWorker:
    """
    Periodic announcer for one peer and one file.

    Start it only after the peer's listening socket is bound, and pass the
    port that was actually bound.

    Args:
        tracker_url: e.g. "http://127.0.0.1:8000".
        file_id: SHA-256 of the metadata file bytes.
        peer_id: this peer's ID.
        listen_port: the bound listening port.
        event_queue: the coordinator's queue.Queue; receives PeersDiscovered
            and TrackerError objects.
        announce_fn: injectable for tests; same signature as announce().
        retry_delays: waits after consecutive failures; last value repeats.
        clock: monotonic time for event timestamps.
    """

    def __init__(self, tracker_url: str, file_id: str, peer_id: str, listen_port: int,
                 event_queue: queue.Queue, announce_fn=announce,
                 retry_delays=TRACKER_RETRY_DELAYS, http_timeout: float = HTTP_TIMEOUT,
                 clock=time.monotonic):
        if not FILE_ID_RE.fullmatch(file_id):
            raise ValueError("file_id must be 64 lowercase hex characters")
        if not PEER_ID_RE.fullmatch(peer_id):
            raise ValueError("invalid peer_id")
        if type(listen_port) is not int or not 1 <= listen_port <= 65535:
            raise ValueError("listen_port must be the bound port, 1-65535")
        self.tracker_url = tracker_url
        self.file_id = file_id
        self.peer_id = peer_id
        self.listen_port = listen_port
        self.event_queue = event_queue
        self._announce = announce_fn
        self._retry_delays = list(retry_delays) or [ANNOUNCE_INTERVAL]
        self._http_timeout = http_timeout
        self._clock = clock

        self._stop = threading.Event()
        self._wake = threading.Event()
        self._completed_pending = threading.Event()
        self._thread: threading.Thread | None = None
        self._send_stopped = True

        # Read-only status for logs/tests (written only by the worker thread).
        self.successes = 0
        self.failures = 0
        self.consecutive_failures = 0
        self.dropped_events = 0
        self.last_delay: float | None = None

    # ---- control (called from other threads) ----

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("worker already started")
        self._thread = threading.Thread(target=self._run, name=f"discovery-{self.peer_id}",
                                        daemon=True)
        self._thread.start()

    def mark_completed(self) -> None:
        """Announce 'completed' now. Call after final verified completion."""
        self._completed_pending.set()
        self._wake.set()

    def announce_now(self) -> None:
        """Skip the current wait, e.g. when the coordinator needs more peers."""
        self._wake.set()

    def stop(self, send_stopped: bool = True, join_timeout: float = 5.0) -> bool:
        """
        Stop the worker; optionally send a best-effort 'stopped'.
        Returns True if the thread has exited.
        """
        self._send_stopped = send_stopped
        self._stop.set()
        self._wake.set()
        if self._thread is None:
            return True
        self._thread.join(join_timeout)
        return not self._thread.is_alive()

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ---- worker thread ----

    def _publish(self, item) -> None:
        try:
            self.event_queue.put(item, timeout=QUEUE_PUT_TIMEOUT)
        except queue.Full:
            # Never block discovery forever on a busy coordinator; the next
            # successful announce carries a fresh list anyway.
            self.dropped_events += 1

    def _next_event(self, announced_started: bool) -> str:
        if self._completed_pending.is_set():
            return "completed"
        return "update" if announced_started else "started"

    def _run(self) -> None:
        announced_started = False
        last_logged_category = None

        while not self._stop.is_set():
            event = self._next_event(announced_started)
            try:
                response = self._announce(self.tracker_url, self.file_id, self.peer_id,
                                          self.listen_port, event, timeout=self._http_timeout)
            except TrackerRequestError as error:
                self.failures += 1
                index = min(self.consecutive_failures, len(self._retry_delays) - 1)
                delay = self._retry_delays[index]
                self.consecutive_failures += 1
                if (error.category != last_logged_category
                        or self.consecutive_failures % ERROR_LOG_EVERY == 1):
                    logger.warning("[%s] tracker %s (%s); retry in %ss (failure %d)",
                                   self.peer_id, error.category, error.detail, delay,
                                   self.consecutive_failures)
                    last_logged_category = error.category
                run_log.emit("tracker_error", category=error.category, detail=error.detail,
                             retry_in=delay)
                self._publish(TrackerError(error.category, error.detail, self._clock()))
            except Exception as error:   # a bug in a fake/injected function, etc.
                self.failures += 1
                delay = self._retry_delays[-1]
                self.consecutive_failures += 1
                logger.exception("[%s] unexpected discovery error", self.peer_id)
                self._publish(TrackerError("internal", repr(error), self._clock()))
            else:
                self.successes += 1
                if self.consecutive_failures:
                    logger.info("[%s] tracker reachable again after %d failure(s)",
                                self.peer_id, self.consecutive_failures)
                self.consecutive_failures = 0
                last_logged_category = None
                announced_started = True
                if event == "completed":
                    self._completed_pending.clear()
                delay = min(max(response.interval, MIN_INTERVAL), MAX_INTERVAL)
                run_log.emit("peers_discovered", count=len(response.peers),
                             announce_event=event)
                self._publish(PeersDiscovered(self.file_id, response.peers, self._clock()))

            self.last_delay = delay
            self._wake.wait(delay)
            self._wake.clear()

        if self._send_stopped and announced_started:
            try:
                self._announce(self.tracker_url, self.file_id, self.peer_id,
                               self.listen_port, "stopped",
                               timeout=min(self._http_timeout, STOPPED_TIMEOUT))
            except Exception:
                pass   # best effort: shutdown must not depend on the tracker
