"""
Tests for Tracker module (Debargha's module).

These tests validate:
    - Peer registration
    - Peer list retrieval (with exclusion)
    - Stale peer cleanup
    - Thread-safety of tracker state
"""

import pytest
import time
import threading


class TestTrackerState:
    """Tests for the in-memory tracker state."""

    def test_register_peer(self):
        """Registering a peer should make it appear in the peer list."""
        pytest.skip("Not yet implemented")

    def test_get_peers_excludes_self(self):
        """get_peer_list(exclude='peer-001') should not include peer-001."""
        pytest.skip("Not yet implemented")

    def test_remove_stale_peers(self):
        """Peers not seen for > timeout should be removed."""
        pytest.skip("Not yet implemented")

    def test_update_refreshes_timestamp(self):
        """Updating a peer should refresh its last_seen time."""
        pytest.skip("Not yet implemented")

    def test_remove_peer_explicit(self):
        """Explicitly removing a peer should remove it from the list."""
        pytest.skip("Not yet implemented")

    def test_peer_count(self):
        """peer_count should return the correct number."""
        pytest.skip("Not yet implemented")

    def test_concurrent_registration(self):
        """Multiple threads registering peers simultaneously should not crash."""
        pytest.skip("Not yet implemented")
