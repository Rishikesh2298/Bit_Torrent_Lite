"""Command line: python -m bittorrent_lite.scheduling.request_pipeline --input FILE.json"""
from __future__ import annotations

import argparse
import json
import re
import sys

from bittorrent_lite.scheduling.request_pipeline.manager import PipelineManager
from bittorrent_lite.scheduling.request_pipeline.models import PipelineConfig
from bittorrent_lite.scheduling.request_pipeline.models import RequestKey
from bittorrent_lite.scheduling.request_pipeline.models import RequestView
from bittorrent_lite.scheduling.request_pipeline.models import Outcome
from bittorrent_lite.scheduling.request_pipeline.models import is_int

CONFIG_FIELDS = {"window", "response_timeout", "send_confirm_timeout",
                 "max_connections", "max_copies"}
TOP_FIELDS = {"num_pieces", "initially_owned", "actions"} | CONFIG_FIELDS

# op -> (required fields, optional fields); every op except snapshot needs now
OPS = {
    "register_connection": ({"connection_id", "provider_id", "now"}, set()),
    "set_available": ({"connection_id", "piece_indices", "now"}, set()),
    "set_permissions": ({"connection_id", "interested", "unchoked", "now"},
                        set()),
    "reserve": ({"connection_id", "piece_index", "now"}, {"allow_duplicate"}),
    "fill": ({"candidate_orders", "now"}, set()),
    "confirm_sent": ({"key", "sent_at", "now"}, set()),
    "start_verification": ({"key", "now"}, set()),
    "finish_verification": ({"key", "valid", "now"}, set()),
    "reject": ({"key", "now"}, set()),
    "send_failed": ({"key", "reason", "now"}, set()),
    "cancel": ({"key", "reason", "now"}, set()),
    "disconnect": ({"connection_id", "now"}, set()),
    "expire": ({"now"}, set()),
    "snapshot": (set(), set()),
}
_DEC = re.compile(r"[1-9][0-9]*")


class ActionError(Exception):
    pass


def parse_key(obj) -> RequestKey:
    if (not isinstance(obj, dict)
            or set(obj) != {"connection_id", "request_id", "piece_index"}):
        raise ActionError("key must be an object with connection_id, "
                          "request_id and piece_index")
    return RequestKey(obj["connection_id"], obj["request_id"],
                      obj["piece_index"])


def parse_orders(obj) -> dict:
    if not isinstance(obj, dict):
        raise ActionError("candidate_orders must be an object")
    out = {}
    for k, v in obj.items():
        if not (k.isascii() and _DEC.fullmatch(k)):
            raise ActionError(f"source key {k!r} is not a positive decimal")
        out[int(k)] = v
    return out


def jsonable(x):
    if isinstance(x, (RequestView, Outcome)):
        return x.to_dict()
    if isinstance(x, tuple):
        return [jsonable(i) for i in x]
    return x


def run(doc: dict) -> dict:
    if not isinstance(doc, dict):
        raise ActionError("input must be a JSON object")
    unknown = set(doc) - TOP_FIELDS
    if unknown:
        raise ActionError(f"unknown input fields: {sorted(unknown)}")
    if "num_pieces" not in doc or "actions" not in doc:
        raise ActionError("num_pieces and actions are required")
    if not isinstance(doc["actions"], list):
        raise ActionError("actions must be a list")
    try:
        cfg = PipelineConfig(**{k: doc[k] for k in CONFIG_FIELDS if k in doc})
        mgr = PipelineManager(doc["num_pieces"],
                              initially_owned=doc.get("initially_owned", ()),
                              config=cfg)
    except ValueError as e:
        raise ActionError(f"setup: {e}")
    results = []
    for n, act in enumerate(doc["actions"], 1):
        try:
            if not isinstance(act, dict) or "op" not in act:
                raise ActionError("action must be an object with 'op'")
            op = act["op"]
            if not isinstance(op, str) or op not in OPS:
                raise ActionError(f"unknown operation {op!r}")
            req, opt = OPS[op]
            args = {k: v for k, v in act.items() if k != "op"}
            extra = set(args) - req - opt
            missing = req - set(args)
            if extra:
                raise ActionError(f"unknown fields: {sorted(extra)}")
            if missing:
                raise ActionError(f"missing fields: {sorted(missing)}")
            if "key" in args:
                args["key"] = parse_key(args["key"])
            if "candidate_orders" in args:
                args["candidate_orders"] = parse_orders(args["candidate_orders"])
            res = mgr.snapshot() if op == "snapshot" else getattr(mgr, op)(**args)
        except (ActionError, ValueError) as e:
            raise ActionError(f"action {n}: {e}")
        results.append({"action": n, "op": op, "result": jsonable(res)})
    return {"results": results, "snapshot": mgr.snapshot()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bittorrent_lite.scheduling.request_pipeline")
    ap.add_argument("--input", required=True, help="path to JSON input")
    ns = ap.parse_args(argv)
    try:
        with open(ns.input, encoding="utf-8") as f:
            doc = json.load(f)
        out = run(doc)
    except (OSError, ValueError, RecursionError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except ActionError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    json.dump(out, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
