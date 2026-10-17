"""
Run the experiment matrix — Debargha's harness.

    python -m experiments.matrix experiments/configs/base.json --repeats 3
    python -m experiments.matrix experiments/configs/base.json --only swarm-L2 --repeats 1
    python -m experiments.matrix experiments/configs/base.json --dry-run

Nine distinct configurations (plan D10). The L=6, S=1, rarest-first
baseline is shared by the selection, seeder, free-rider and failure
comparisons; it is run once per repeat, not four times.

Run order is shuffled with a fixed seed so slow drift (thermal, background
load) does not line up with one configuration. Each run gets fresh peer
directories and a fresh tracker. Failed runs are kept and reported.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from experiments.collect import collect  # noqa: E402
from experiments.launcher import Run, load_config  # noqa: E402

CONFIGURATIONS = [
    ("swarm-L2", {"L": 2}),
    ("swarm-L4", {"L": 4}),
    ("swarm-L6", {"L": 6}),            # shared baseline: L=6, S=1, rarest, cooperative
    ("swarm-L8", {"L": 8}),
    ("select-random", {"L": 6, "strategy": "random"}),
    ("select-sequential", {"L": 6, "strategy": "sequential"}),
    ("seeders-S2", {"L": 6, "S": 2}),
    ("free-rider", {"L": 6, "scenario": "free_rider"}),
    ("failure", {"L": 6, "scenario": "failure"}),
]


def plan_runs(base_path: str | None, overrides: list[str], repeats: int,
              only: list[str] | None, order_seed: int) -> list[dict]:
    configs = []
    for name, changes in CONFIGURATIONS:
        if only and name not in only:
            continue
        for repeat in range(1, repeats + 1):
            config = load_config(base_path, overrides)
            config.update(changes)
            config["name"] = name
            config["repeat"] = repeat
            # vary the seed per repeat; record it so a run can be reproduced
            config["seed"] = config["seed"] * 1000 + repeat
            configs.append(config)
    random.Random(order_seed).shuffle(configs)
    return configs


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the experiment matrix")
    parser.add_argument("config", nargs="?", help="base JSON config")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--only", action="append", help="configuration name (repeatable)")
    parser.add_argument("--order-seed", type=int, default=2026)
    parser.add_argument("--pause-s", type=float, default=1.0, help="gap between runs")
    parser.add_argument("--runs-dir", default=str(REPO_ROOT / "experiments" / "data" / "runs"))
    parser.add_argument("--out", default=str(REPO_ROOT / "experiments" / "results"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    unknown = set(args.only or []) - {name for name, _ in CONFIGURATIONS}
    if unknown:
        parser.error(f"unknown configuration(s): {', '.join(sorted(unknown))}")

    runs = plan_runs(args.config, args.set, args.repeats, args.only, args.order_seed)
    print(f"{len(runs)} run(s) planned")
    if args.dry_run:
        for config in runs:
            print(f"  {config['name']} r{config['repeat']}: L={config['L']} S={config['S']} "
                  f"{config['strategy']} {config['scenario']} seed={config['seed']}")
        return 0

    statuses = {}
    for index, config in enumerate(runs, 1):
        started = time.monotonic()
        manifest = Run(config, Path(args.runs_dir)).execute()
        statuses[manifest["status"]] = statuses.get(manifest["status"], 0) + 1
        print(f"[{index}/{len(runs)}] {manifest['run_id']}: {manifest['status']} "
              f"in {time.monotonic() - started:.1f}s"
              + (f" ({manifest['failure_reason']})" if manifest["failure_reason"] else ""),
              flush=True)
        time.sleep(args.pause_s)

    _, _, problems = collect(Path(args.runs_dir), Path(args.out))
    print("status counts: " + ", ".join(f"{k}={v}" for k, v in sorted(statuses.items())))
    for problem in problems:
        print(f"PROBLEM: {problem}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
