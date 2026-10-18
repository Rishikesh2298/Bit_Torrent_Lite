"""JSON-lines command-line interface: python -m recovery_policy"""

from __future__ import annotations

import inspect
import json
import sys
from dataclasses import fields

from .config import RecoveryConfig
from .policy import CapacityError, RecoveryPolicy

METHODS = ("rank_candidates", "allow_duplicate", "failed", "succeeded", "snapshot")
CREATE_KEYS = {"op", "num_pieces", "seed", "config"}


def _create(obj: dict) -> RecoveryPolicy:
    extra = set(obj) - CREATE_KEYS
    if extra:
        raise ValueError(f"unexpected create fields: {', '.join(sorted(extra))}")
    if "num_pieces" not in obj:
        raise ValueError("create requires num_pieces")
    raw = obj.get("config")
    config = None
    if raw is not None:
        if not isinstance(raw, dict):
            raise ValueError("config must be an object")
        known = {f.name for f in fields(RecoveryConfig)}
        unknown = set(raw) - known
        if unknown:
            raise ValueError(f"unknown config fields: {', '.join(sorted(unknown))}")
        raw = dict(raw)
        if isinstance(raw.get("retry_delays"), list):
            raw["retry_delays"] = tuple(raw["retry_delays"])
        config = RecoveryConfig(**raw)
    return RecoveryPolicy(obj["num_pieces"], config, seed=obj.get("seed", 0))


def _handle(obj, policy):
    if not isinstance(obj, dict):
        raise ValueError("each input line must be a JSON object")
    op = obj.get("op")
    if op == "create":
        if policy is not None:
            raise ValueError("policy already created; a second create is not accepted")
        return _create(obj), None
    if policy is None:
        raise ValueError("first operation must be create")
    if op not in METHODS:
        raise ValueError(f"unknown op; expected one of create, {', '.join(METHODS)}")
    args = {k: v for k, v in obj.items() if k != "op"}
    method = getattr(policy, op)
    try:
        inspect.signature(method).bind(**args)
    except TypeError as exc:
        raise ValueError(f"bad arguments for {op}: {exc}") from None
    return policy, method(**args)


def main() -> int:
    policy = None
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            policy, result = _handle(obj, policy)
            out = {"ok": True, "result": result}
        except (ValueError, CapacityError) as exc:  # JSONDecodeError is a ValueError
            out = {"ok": False, "error": type(exc).__name__, "message": str(exc)}
        sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
