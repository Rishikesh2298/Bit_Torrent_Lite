"""Resource helper diagnostics use actual OS counters and explicit errors."""
import math
import os
import socket

import psutil
import pytest

from bittorrent_lite.acceptance_tools.resources import host_inventory, process_sample


def test_process_observer_sees_owned_tcp_listener():
    before = process_sample()
    with socket.socket() as owned:
        owned.bind(('127.0.0.1', 0))
        owned.listen()
        after = process_sample()
        assert after['tcp_socket_count'] >= before['tcp_socket_count'] + 1
        assert after['rss_bytes'] > 0 and after['thread_count'] >= 1
        assert all(not isinstance(value, bool) and math.isfinite(value) and value >= 0
                   for value in after.values())
        assert ('handle_count' if os.name == 'nt' else 'file_descriptor_count') in after


def test_access_failure_never_produces_zero_metrics(monkeypatch):
    def unavailable():
        raise psutil.AccessDenied(os.getpid())
    monkeypatch.setattr(psutil, 'Process', unavailable)
    with pytest.raises(psutil.AccessDenied):
        process_sample()


def test_host_inventory_has_actual_capacity_and_explicit_scope(tmp_path):
    observed = host_inventory(tmp_path)
    assert observed['ram_total_bytes'] >= observed['ram_available_bytes'] > 0
    assert observed['disk_total_bytes'] >= observed['disk_free_bytes'] > 0
    assert observed['executable'] and observed['python'] and observed['platform']
    assert observed['limitations']
