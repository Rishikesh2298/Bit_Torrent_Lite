"""
This computer's addresses, free ports and peer IDs for the GUI.

The Tailscale test on 23 Oct 2026 showed three ways a manual launch goes
wrong: a --host address the machine does not own (Errno 49), two peers with
the same --peer-id (the second one stalls without an error) and a tracker
URL that makes the tracker record 127.0.0.1 for a peer other laptops must
reach. The helpers here pick values that avoid all three.
"""

import ipaddress
import os
import random
import re
import socket
import subprocess

TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")
PEER_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,32}")


def classify(ip: str) -> str:
    address = ipaddress.ip_address(ip)
    if address.is_loopback:
        return "loopback"
    if address in TAILSCALE_NET:
        return "tailscale"
    if address.is_private:
        return "lan"
    if address.is_link_local:
        return "link-local"
    return "public"


# Lower sorts first: the address other laptops are most likely to reach.
_PREFERENCE = {"tailscale": 0, "lan": 1, "public": 2, "link-local": 3, "loopback": 4}


def _route_address(target: str) -> str | None:
    """The source address the OS would use for target. UDP connect sends nothing."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect((target, 9))
            return sock.getsockname()[0]
    except OSError:
        return None


def _tailscale_cli() -> list[str]:
    for exe in ("tailscale", "/Applications/Tailscale.app/Contents/MacOS/Tailscale"):
        try:
            result = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=2)
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode == 0:
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return []


def local_addresses() -> list[dict]:
    """IPv4 addresses of this computer, best guess for 'reachable by others' first."""
    found = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    # 100.100.100.100 is Tailscale's own resolver: routed through the tailnet if it is up.
    for target in ("100.100.100.100", "8.8.8.8", "192.168.0.1", "10.0.0.1"):
        ip = _route_address(target)
        if ip:
            found.add(ip)
    found.update(_tailscale_cli())
    found.add("127.0.0.1")
    rows = []
    for ip in found:
        try:
            kind = classify(ip)
        except ValueError:
            continue
        if ip.startswith("0.") or (kind == "loopback" and ip != "127.0.0.1"):
            continue
        rows.append({"ip": ip, "kind": kind})
    rows.sort(key=lambda r: (_PREFERENCE[r["kind"]], ipaddress.ip_address(r["ip"])))
    return rows


def default_address(addresses: list[dict]) -> str:
    return addresses[0]["ip"] if addresses else "127.0.0.1"


def port_is_free(port: int, host: str = "0.0.0.0") -> bool:
    """True when a server could listen on port now. Bound like the tracker and peers bind,
    so connections left in TIME_WAIT by a stopped peer do not count as busy (except on Windows)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if os.name != "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def next_free_port(start: int, taken: set[int] = frozenset(), limit: int = 500) -> int:
    for port in range(start, min(start + limit, 65536)):
        if port not in taken and port_is_free(port):
            return port
    raise OSError(f"no free TCP port between {start} and {start + limit}")


def machine_tag() -> str:
    """Short, ID-safe form of the computer name, e.g. 'macbook' or 'desktop-a1'."""
    name = socket.gethostname().split(".")[0].lower()
    name = re.sub(r"[^a-z0-9-]+", "-", name).strip("-")
    return (name or "peer")[:16].rstrip("-") or "peer"


def new_peer_id(taken: set[str], seeder: bool = False, rng: random.Random | None = None) -> str:
    """A peer ID unique among taken, with the machine name so laptops never collide."""
    rng = rng or random.Random()
    prefix = machine_tag() + ("-seed" if seeder else "")
    for _ in range(1000):
        candidate = f"{prefix}-{rng.getrandbits(16):04x}"
        if candidate not in taken:
            return candidate
    raise ValueError("could not generate a unique peer ID")
