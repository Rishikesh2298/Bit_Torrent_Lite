import random
import socket

from bittorrent_lite.gui import netinfo


def test_classify_labels_tailscale_lan_and_loopback():
    assert netinfo.classify("100.101.102.103") == "tailscale"
    assert netinfo.classify("100.63.0.1") == "public"         # just outside 100.64.0.0/10
    assert netinfo.classify("192.168.1.20") == "lan"
    assert netinfo.classify("10.0.0.5") == "lan"
    assert netinfo.classify("127.0.0.1") == "loopback"


def test_local_addresses_prefers_tailscale_and_keeps_loopback(monkeypatch):
    monkeypatch.setattr(netinfo, "_tailscale_cli", lambda: ["100.90.1.2"])
    monkeypatch.setattr(netinfo, "_route_address", lambda target: "192.168.1.20")
    rows = netinfo.local_addresses()
    assert rows[0] == {"ip": "100.90.1.2", "kind": "tailscale"}
    assert {"ip": "127.0.0.1", "kind": "loopback"} in rows
    assert netinfo.default_address(rows) == "100.90.1.2"
    assert netinfo.default_address([]) == "127.0.0.1"


def test_peer_ids_are_valid_unique_and_name_the_machine(monkeypatch):
    monkeypatch.setattr(socket, "gethostname", lambda: "Debargha's MacBook Pro.local")
    assert netinfo.machine_tag() == "debargha-s-macbo"
    taken = set()
    rng = random.Random(1)
    for _ in range(200):
        peer_id = netinfo.new_peer_id(taken, rng=rng)
        assert netinfo.PEER_ID_RE.fullmatch(peer_id)
        assert peer_id not in taken
        taken.add(peer_id)
    assert netinfo.new_peer_id(set(), seeder=True).startswith("debargha-s-macbo-seed-")


def test_next_free_port_skips_taken_and_bound_ports():
    with socket.socket() as busy:
        busy.bind(("0.0.0.0", 0))
        busy.listen()
        port = busy.getsockname()[1]
        found = netinfo.next_free_port(port, taken={port + 1})
        assert found not in (port, port + 1)
        assert not netinfo.port_is_free(port)
