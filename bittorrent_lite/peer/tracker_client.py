"""
Tracker Client — Anik's Module (or Debargha)

HTTP client that a peer uses to communicate with the tracker.
Sends registration announcements and retrieves peer lists.

Interface:
    announce(tracker_url, peer_id, ip, port) -> dict
    get_peers(tracker_url, peer_id) -> list[PeerInfo]

This module depends on:
    - urllib.request or http.client (stdlib HTTP client)
    - json (for serialization)

This module does NOT depend on:
    - tracker_server (it talks to the tracker over HTTP, not by import)
    - any peer module
"""

import json
import urllib.request
import urllib.error
from bittorrent_lite.types import PeerInfo
from bittorrent_lite.config import TRACKER_HOST, TRACKER_PORT


def announce(tracker_url: str, peer_id: str, ip: str, port: int) -> dict:
    """
    Announce this peer to the tracker (register or heartbeat).

    Sends a POST request to {tracker_url}/announce with JSON body.

    Args:
        tracker_url: Base URL of the tracker (e.g., "http://127.0.0.1:8000").
        peer_id: This peer's identifier.
        ip: This peer's IP address.
        port: This peer's listening port.

    Returns:
        Response dict from the tracker (e.g., {"status": "ok"}).

    Raises:
        ConnectionError: If the tracker is unreachable.
    """
    # TODO: Implement this
    raise NotImplementedError("announce not yet implemented")


def get_peers(tracker_url: str, peer_id: str) -> list[PeerInfo]:
    """
    Request the list of peers currently in the swarm.

    Sends a GET request to {tracker_url}/peers?peer_id={peer_id}.
    The tracker excludes the requesting peer from the response.

    Args:
        tracker_url: Base URL of the tracker.
        peer_id: This peer's identifier (excluded from results).

    Returns:
        List of PeerInfo for all other peers in the swarm.

    Raises:
        ConnectionError: If the tracker is unreachable.
    """
    # TODO: Implement this
    raise NotImplementedError("get_peers not yet implemented")


def build_tracker_url(host: str = TRACKER_HOST, port: int = TRACKER_PORT) -> str:
    """Build the tracker base URL from host and port."""
    return f"http://{host}:{port}"
