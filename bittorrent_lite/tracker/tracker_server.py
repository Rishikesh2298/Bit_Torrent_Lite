"""
Tracker Server — Debargha's Module

HTTP front end for the membership table in tracker_state.py.
The full contract, with examples, is in docs/tracker.md.

Endpoint:
    POST /announce   Content-Type: application/json
    {"file_id": "<64 hex>", "peer_id": "peer-01", "listen_port": 7002,
     "event": "started" | "update" | "completed" | "stopped"}

    200 {"interval": 5, "peers": [{"peer_id": "...", "ip": "...", "port": 7003}]}

Errors (JSON body {"error": "<message>"}):
    400 malformed JSON or invalid field     404 unknown path
    405 wrong method on /announce           411 missing Content-Length
    413 body larger than 4 KiB              415 not JSON, or Transfer-Encoding used

The peer's IP is the source address of the HTTP connection; the request
cannot choose it. The tracker never sees file contents or bitfields.

A single-threaded server is enough: each request is a tiny dictionary
operation. A per-connection socket timeout stops a stalled client from
holding the server forever.

Usage:
    python -m bittorrent_lite.tracker.tracker_server --host 127.0.0.1 --port 8000
"""

import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer

from bittorrent_lite import run_log
from bittorrent_lite.config import (
    ANNOUNCE_INTERVAL, MAX_ANNOUNCE_BODY, TRACKER_HOST, TRACKER_PEER_TIMEOUT, TRACKER_PORT,
)
from bittorrent_lite.logger import get_logger
from bittorrent_lite.tracker.tracker_state import EVENTS, TrackerState

logger = get_logger("TRACKER")

FILE_ID_RE = re.compile(r"[0-9a-f]{64}")
PEER_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,32}")
REQUIRED_FIELDS = ("file_id", "peer_id", "listen_port", "event")
REQUEST_READ_TIMEOUT = 2.0      # seconds a client may take to send its request


class AnnounceError(Exception):
    """A request that must be answered with an HTTP error."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def validate_announce(body: object) -> tuple[str, str, int, str]:
    """
    Check a decoded announce body. Returns (file_id, peer_id, port, event).

    Raises AnnounceError(400) on any problem. Extra fields are rejected so a
    client cannot believe an unsupported field (such as "ip") had an effect.
    """
    if not isinstance(body, dict):
        raise AnnounceError(400, "body must be a JSON object")
    missing = [name for name in REQUIRED_FIELDS if name not in body]
    if missing:
        raise AnnounceError(400, f"missing field(s): {', '.join(missing)}")
    extra = sorted(set(body) - set(REQUIRED_FIELDS))
    if extra:
        raise AnnounceError(400, f"unknown field(s): {', '.join(extra)}")

    file_id, peer_id = body["file_id"], body["peer_id"]
    port, event = body["listen_port"], body["event"]

    if not isinstance(file_id, str) or not FILE_ID_RE.fullmatch(file_id):
        raise AnnounceError(400, "file_id must be 64 lowercase hex characters")
    if not isinstance(peer_id, str) or not PEER_ID_RE.fullmatch(peer_id):
        raise AnnounceError(400, "peer_id must be 1-32 letters, digits, '_' or '-'")
    # bool is a subclass of int in Python; reject true/false explicitly.
    if type(port) is not int or not 1 <= port <= 65535:
        raise AnnounceError(400, "listen_port must be an integer 1-65535")
    if event not in EVENTS:
        raise AnnounceError(400, f"event must be one of {', '.join(EVENTS)}")
    return file_id, peer_id, port, event


class TrackerHandler(BaseHTTPRequestHandler):
    """Handles one HTTP request, then closes the connection."""

    server_version = "BitTorrentLiteTracker/1"
    protocol_version = "HTTP/1.1"
    timeout = REQUEST_READ_TIMEOUT          # applied to the socket by StreamRequestHandler

    # ---- responses ----

    def _send_json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)
        self.close_connection = True

    def _send_error(self, status: int, message: str) -> None:
        logger.info("Rejected %s %s from %s: %d %s",
                    self.command, self.path, self.client_address[0], status, message)
        run_log.emit("tracker_rejected", status=status, reason=message)
        self._send_json(status, {"error": message})

    # ---- request body ----

    def _read_body(self) -> bytes:
        if "Transfer-Encoding" in self.headers:
            raise AnnounceError(415, "Transfer-Encoding is not supported")
        content_type = self.headers.get("Content-Type", "")
        if content_type.split(";")[0].strip().lower() != "application/json":
            raise AnnounceError(415, "Content-Type must be application/json")
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise AnnounceError(411, "Content-Length is required")
        if not raw_length.isdigit():
            raise AnnounceError(400, "invalid Content-Length")
        length = int(raw_length)
        if length > MAX_ANNOUNCE_BODY:
            raise AnnounceError(413, f"body exceeds {MAX_ANNOUNCE_BODY} bytes")
        # A short read means the client stalled past the socket timeout
        # (TimeoutError is raised) or closed early.
        body = self.rfile.read(length)
        if len(body) != length:
            raise AnnounceError(400, "incomplete request body")
        return body

    # ---- methods ----

    def do_POST(self):
        if self.path != "/announce":
            self._send_error(404, "unknown path")
            return
        try:
            body = self._read_body()
            try:
                decoded = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise AnnounceError(400, "body is not valid UTF-8 JSON")
            file_id, peer_id, port, event = validate_announce(decoded)
        except AnnounceError as error:
            self._send_error(error.status, error.message)
            return

        ip = self.client_address[0]
        peers = self.server.state.announce(file_id, peer_id, ip, port, event)
        logger.info("%s %s %s:%d file=%s… -> %d peer(s)",
                    event, peer_id, ip, port, file_id[:8], len(peers))
        run_log.emit("tracker_announce", peer=peer_id, ip=ip, port=port,
                     announce_event=event, returned=len(peers),
                     members=self.server.state.peer_count(file_id))
        self._send_json(200, {
            "interval": self.server.interval,
            "peers": [{"peer_id": p.peer_id, "ip": p.ip, "port": p.port} for p in peers],
        })

    def _method_not_allowed(self):
        if self.path == "/announce":
            self._send_error(405, "use POST")
        else:
            self._send_error(404, "unknown path")

    do_GET = do_PUT = do_DELETE = do_PATCH = _method_not_allowed

    def log_message(self, format, *args):
        # Replace http.server's stderr access log; our logger records outcomes.
        pass


class TrackerServer(HTTPServer):
    """HTTPServer that carries the membership table and announce interval."""

    def __init__(self, address, state: TrackerState | None = None,
                 interval: int = ANNOUNCE_INTERVAL):
        super().__init__(address, TrackerHandler)
        self.state = state if state is not None else TrackerState(TRACKER_PEER_TIMEOUT)
        self.interval = interval

    def handle_error(self, request, client_address):
        # A client that times out or disconnects must not stop the server.
        logger.warning("Request from %s failed and was dropped", client_address[0])
        run_log.emit("tracker_request_failed", ip=client_address[0])


def make_server(host: str = TRACKER_HOST, port: int = TRACKER_PORT,
                state: TrackerState | None = None) -> TrackerServer:
    """Bind the tracker. Port 0 picks a free port (see server.server_address)."""
    return TrackerServer((host, port), state)


def run_tracker(host: str = TRACKER_HOST, port: int = TRACKER_PORT) -> None:
    """Start the tracker and serve until interrupted (Ctrl+C)."""
    server = make_server(host, port)
    bound_port = server.server_address[1]
    logger.info("Tracker listening on %s:%d", host, bound_port)
    run_log.emit("tracker_ready", port=bound_port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        run_log.emit("exit", reason="stopped")
        logger.info("Tracker stopped")


if __name__ == "__main__":
    import argparse
    import signal
    import sys

    parser = argparse.ArgumentParser(description="BitTorrent-Lite Tracker")
    parser.add_argument("--host", default=TRACKER_HOST, help="Host to bind to")
    parser.add_argument("--port", type=int, default=TRACKER_PORT, help="Port to listen on")
    args = parser.parse_args()

    def _on_sigterm(signum, frame):
        # Let the launcher's terminate() shut down like Ctrl+C.
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _on_sigterm)
    try:
        run_tracker(args.host, args.port)
    except OSError as error:
        print(f"Tracker failed to start: {error}", file=sys.stderr)
        sys.exit(2)
