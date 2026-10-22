"""JSON-lines interface: ``python -m bittorrent_lite.scheduling.choking_policy``."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, fields
from typing import Any

from bittorrent_lite.scheduling.choking_policy.models import Config
from bittorrent_lite.scheduling.choking_policy.models import PeerInfo
from bittorrent_lite.scheduling.choking_policy.policy import Policy

_CONFIG_FIELDS = {f.name for f in fields(Config)}

_ARGS: dict[str, tuple[str, ...]] = {
    "connect": ("peer",),
    "disconnect": ("peer_id",),
    "set_interested": ("peer_id", "interested"),
    "record_contribution": ("peer_id", "verified_bytes"),
    "set_seeder": ("seeder",),
    "set_upload_enabled": ("enabled",),
    "tick": (),
    "acknowledge": ("token", "applied"),
    "snapshot": (),
    "shutdown": (),
    "reset": (),
}


def _error(exc: BaseException) -> dict[str, Any]:
    message = exc.args[0] if isinstance(exc, KeyError) and exc.args else str(exc)
    return {"ok": False, "error": {"type": type(exc).__name__, "message": str(message)}}


class _Session:
    def __init__(self) -> None:
        self.policy: Policy | None = None
        self.first = True

    def handle(self, obj: Any) -> dict[str, Any]:
        first, self.first = self.first, False
        if not isinstance(obj, dict):
            raise ValueError("each line must be a JSON object")
        op = obj.get("op")
        if not isinstance(op, str):
            raise ValueError("'op' must be a string")
        if op == "config":
            extra = set(obj) - _CONFIG_FIELDS - {"op"}
            if extra:
                raise ValueError(f"unexpected keys: {sorted(extra)}")
            if not first:
                raise ValueError("config must be the first operation")
            self.policy = Policy(Config(**{k: v for k, v in obj.items() if k != "op"}))
            return {"ok": True}
        if op not in _ARGS:
            raise ValueError(f"unknown operation: {op!r}")
        expected = {"op", "now", *_ARGS[op]}
        missing = expected - set(obj)
        if missing:
            raise ValueError(f"missing keys: {sorted(missing)}")
        extra = set(obj) - expected
        if extra:
            raise ValueError(f"unexpected keys: {sorted(extra)}")
        if self.policy is None:
            self.policy = Policy()
        policy, now = self.policy, obj["now"]

        if op == "connect":
            peer = obj["peer"]
            if not isinstance(peer, dict):
                raise ValueError("peer must be an object")
            bad = set(peer) - {"peer_id", "interested"}
            if bad or "peer_id" not in peer:
                raise ValueError("peer must contain peer_id and optionally interested")
            policy.connect(PeerInfo(peer["peer_id"], peer.get("interested", False)), now)
        elif op == "disconnect":
            policy.disconnect(obj["peer_id"], now)
        elif op == "set_interested":
            policy.set_interested(obj["peer_id"], obj["interested"], now)
        elif op == "record_contribution":
            policy.record_contribution(obj["peer_id"], obj["verified_bytes"], now)
        elif op == "set_seeder":
            policy.set_seeder(obj["seeder"], now)
        elif op == "set_upload_enabled":
            policy.set_upload_enabled(obj["enabled"], now)
        elif op == "tick":
            return asdict(policy.tick(now))
        elif op == "acknowledge":
            return {"accepted": policy.acknowledge(obj["token"], obj["applied"], now)}
        elif op == "snapshot":
            return {"state": asdict(policy.snapshot(now))}
        elif op == "shutdown":
            policy.shutdown(now)
        elif op == "reset":
            policy.reset(now)
        return {"ok": True}


def main() -> None:
    session = _Session()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            response = session.handle(json.loads(line))
        except Exception as exc:  # noqa: BLE001 - report every failure, keep reading
            session.first = False
            response = _error(exc)
        sys.stdout.write(json.dumps(response, separators=(",", ":"), allow_nan=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
