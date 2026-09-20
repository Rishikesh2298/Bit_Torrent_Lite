"""
Tracker Server — Debargha's Module

HTTP server that peers contact for registration and discovery.
Uses Python's built-in http.server module.

Endpoints:
    POST /announce
        Body (JSON): {"peer_id": "...", "ip": "...", "port": 9001}
        Response: {"status": "ok"}

    GET /peers?peer_id=peer-001
        Response (JSON): {"peers": [{"peer_id": "...", "ip": "...", "port": ...}, ...]}

    DELETE /announce?peer_id=peer-001   (optional: explicit departure)
        Response: {"status": "ok"}

Usage:
    python -m bittorrent_lite.tracker.tracker_server --host 127.0.0.1 --port 8000

Architecture:
    tracker_server.py → HTTP handling, request parsing, response formatting
    tracker_state.py  → actual swarm data storage (injected dependency)

Background cleanup:
    A daemon thread runs every TRACKER_PEER_TIMEOUT/2 seconds and calls
    tracker_state.remove_stale_peers() to prune dead peers.
"""

from bittorrent_lite.tracker.tracker_state import TrackerState
from bittorrent_lite.config import TRACKER_HOST, TRACKER_PORT


def run_tracker(host: str = TRACKER_HOST, port: int = TRACKER_PORT) -> None:
    """
    Start the tracker HTTP server.

    This function blocks and runs the server until interrupted (Ctrl+C).

    Args:
        host: IP address to bind to.
        port: Port to listen on.
    """
    # TODO: Debargha — implement this
    # Hint: subclass http.server.BaseHTTPRequestHandler
    # Override do_POST and do_GET to handle /announce and /peers
    raise NotImplementedError("run_tracker not yet implemented")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="BitTorrent-Lite Tracker")
    parser.add_argument("--host", default=TRACKER_HOST, help="Host to bind to")
    parser.add_argument("--port", type=int, default=TRACKER_PORT, help="Port to listen on")
    args = parser.parse_args()

    run_tracker(args.host, args.port)
