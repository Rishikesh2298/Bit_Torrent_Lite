"""
Plot experiment results — Debargha's harness.

    python -m experiments.plot --results experiments/results

Reads runs.csv / peers.csv / availability.csv written by experiments.collect
and writes PNG figures plus summary.csv into <results>/figures/. Every
figure is regenerated from those CSVs; nothing is typed in by hand.

Each point/bar is the mean over successful repeats; whiskers show min-max;
individual repeats are drawn as small dots. Every label carries "ok/total"
so failed runs stay visible. If any plotted run is synthetic, the figure
title says SYNTHETIC.
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent

# Reference categorical palette (light surface), fixed order.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
INK, INK_2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
MIB = 1024 * 1024


def _num(value):
    if value in ("", None):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def style(ax, title: str, ylabel: str, xlabel: str = "") -> None:
    ax.set_facecolor(SURFACE)
    ax.figure.set_facecolor(SURFACE)
    ax.set_title(title, color=INK, fontsize=12, loc="left")
    ax.set_ylabel(ylabel, color=INK_2)
    if xlabel:
        ax.set_xlabel(xlabel, color=INK_2)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_2)


def summarize(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "mean": None, "sd": None, "min": None, "max": None}
    return {"n": len(values), "mean": statistics.fmean(values),
            "sd": statistics.stdev(values) if len(values) > 1 else 0.0,
            "min": min(values), "max": max(values)}


def select(runs, **match):
    return [r for r in runs if all(str(r[k]) == str(v) for k, v in match.items())]


def ok_values(runs, column):
    return [v for v in (_num(r[column]) for r in runs if r["status"] == "ok") if v is not None]


def is_synthetic(runs) -> bool:
    return any(r["environment"].endswith("synthetic") for r in runs)


def title_for(text, runs):
    return f"{text}\nSYNTHETIC DATA: tooling check only, not results" if is_synthetic(runs) else text


def draw_bars(ax, groups: list[tuple[str, list[dict], list[float]]]) -> None:
    """groups: (label, runs in group, values to plot)."""
    xs = range(len(groups))
    for x, (label, runs, values) in zip(xs, groups):
        s = summarize(values)
        color = SERIES[x % len(SERIES)]
        if s["n"]:
            ax.bar(x, s["mean"], width=0.55, color=color, zorder=2)
            ax.errorbar(x, s["mean"], yerr=[[s["mean"] - s["min"]], [s["max"] - s["mean"]]],
                        color=INK_2, capsize=4, linewidth=1.2, zorder=3)
            ax.scatter([x] * len(values), values, s=12, color=INK, zorder=4)
            ax.annotate(f"{s['mean']:.1f}", (x, s["max"]), textcoords="offset points",
                        xytext=(0, 6), ha="center", color=INK, fontsize=9)
    ax.set_xticks(list(xs))
    ax.set_xticklabels([f"{label}\n{len(values)}/{len(runs)} ok"
                        for label, runs, values in groups])


def fig_swarm_size(runs, out: Path, summary: list) -> None:
    group = select(runs, S=1, strategy="rarest", scenario="baseline")
    sizes = sorted({int(r["L"]) for r in group})
    if not sizes:
        return
    for column, ylabel, fname, scale, title in (
            ("distribution_s", "Distribution time (s)", "fig1_swarm_size_distribution.png", 1,
             "Distribution time vs swarm size (S=1, rarest-first)"),
            ("aggregate_throughput_Bps", "Aggregate useful throughput (MiB/s)",
             "fig2_swarm_size_throughput.png", MIB,
             "Aggregate useful throughput vs swarm size (S=1)")):
        fig, ax = plt.subplots(figsize=(7, 4.2))
        means, lows, highs, labels = [], [], [], []
        for L in sizes:
            these = select(group, L=L)
            values = [v / scale for v in ok_values(these, column)]
            s = summarize(values)
            summary.append({"figure": fname, "group": f"L={L}", "ok": s["n"], "total": len(these),
                            **{k: s[k] for k in ("mean", "sd", "min", "max")}})
            labels.append(f"{L}\n{s['n']}/{len(these)} ok")
            if s["n"]:
                means.append((L, s["mean"]))
                lows.append(s["mean"] - s["min"])
                highs.append(s["max"] - s["mean"])
                ax.scatter([L] * len(values), values, s=12, color=INK, zorder=4)
        if means:
            xs, ys = zip(*means)
            ax.errorbar(xs, ys, yerr=[lows, highs], color=SERIES[0], linewidth=2,
                        marker="o", markersize=8, capsize=4, zorder=3)
        ax.set_xticks(sizes)
        ax.set_xticklabels(labels)
        ax.set_ylim(bottom=0)
        style(ax, title_for(title, group), ylabel, "Downloaders L")
        fig.tight_layout()
        fig.savefig(out / fname, dpi=150)
        plt.close(fig)


def fig_groups(runs, out: Path, summary: list, fname: str, title: str,
               groups_spec: list[tuple[str, dict]], column="distribution_s",
               ylabel="Distribution time (s)") -> None:
    groups = []
    for label, match in groups_spec:
        these = select(runs, **match)
        values = ok_values(these, column)
        groups.append((label, these, values))
        s = summarize(values)
        summary.append({"figure": fname, "group": label, "ok": s["n"], "total": len(these),
                        **{k: s[k] for k in ("mean", "sd", "min", "max")}})
    if not any(g[1] for g in groups):
        return
    fig, ax = plt.subplots(figsize=(7, 4.2))
    draw_bars(ax, groups)
    ax.set_ylim(bottom=0)
    style(ax, title_for(title, [r for g in groups for r in g[1]]), ylabel)
    fig.tight_layout()
    fig.savefig(out / fname, dpi=150)
    plt.close(fig)


def survivor_finish(peers_by_run, run, exclude: str) -> float | None:
    """Latest finish_s among downloaders other than `exclude`."""
    rows = [p for p in peers_by_run.get(run["run_id"], [])
            if p["role_at_start"] == "downloader" and p["peer_id"] != exclude]
    values = [_num(p["finish_s"]) for p in rows]
    if not rows or any(v is None for v in values):
        return None
    return max(values)


def fig_free_rider(runs, peers_by_run, out: Path, summary: list) -> None:
    base = select(runs, L=6, S=1, strategy="rarest", scenario="baseline")
    fr = select(runs, L=6, S=1, strategy="rarest", scenario="free_rider")
    if not fr:
        return
    target = fr[0]["failure_target"]

    def completions(group, want_target):
        values = []
        for run in group:
            if run["status"] != "ok":
                continue
            for p in peers_by_run.get(run["run_id"], []):
                if p["role_at_start"] == "downloader" and (p["peer_id"] == target) == want_target:
                    v = _num(p["completion_s"])
                    if v is not None:
                        values.append(v)
        return values

    groups = [("Cooperative peers\n(no free rider)", base, completions(base, False)),
              ("Cooperative peers\n(with free rider)", fr, completions(fr, False)),
              ("Free rider", fr, completions(fr, True))]
    fig, ax = plt.subplots(figsize=(7.5, 4.4))
    for x, (label, group, values) in enumerate(groups):
        s = summarize(values)
        summary.append({"figure": "fig5_free_rider.png", "group": label.replace("\n", " "),
                        "ok": s["n"], "total": len(group),
                        **{k: s[k] for k in ("mean", "sd", "min", "max")}})
        if values:
            ax.boxplot([values], positions=[x], widths=0.5, patch_artist=True,
                       boxprops={"facecolor": SERIES[x], "edgecolor": INK_2},
                       medianprops={"color": INK}, whiskerprops={"color": INK_2},
                       capprops={"color": INK_2}, flierprops={"markeredgecolor": INK_2})
    ax.set_xticks(range(len(groups)))
    ax.set_xticklabels([f"{g[0]}\n{len(g[2])} peer-runs" for g in groups])
    ax.set_ylim(bottom=0)
    style(ax, title_for("Per-peer completion time with one free rider (L=6, S=1)", base + fr),
          "Per-peer completion (s)")
    fig.tight_layout()
    fig.savefig(out / "fig5_free_rider.png", dpi=150)
    plt.close(fig)

    uploaded = []
    for run in fr:
        for p in peers_by_run.get(run["run_id"], []):
            if p["peer_id"] == target:
                uploaded.append(_num(p["uploaded_payload_bytes"]))
    summary.append({"figure": "fig5_free_rider.png", "group": "free rider uploaded bytes",
                    "ok": len([u for u in uploaded if u is not None]), "total": len(fr),
                    "mean": None if not [u for u in uploaded if u is not None]
                    else statistics.fmean([u for u in uploaded if u is not None]),
                    "sd": None, "min": None, "max": None})


def fig_failure(runs, peers_by_run, out: Path, summary: list) -> None:
    fail = select(runs, L=6, S=1, strategy="rarest", scenario="failure")
    base = select(runs, L=6, S=1, strategy="rarest", scenario="baseline")
    if not fail:
        return
    target = fail[0]["failure_target"]
    # Same survivor subset in both: every downloader except the designated target.
    base_vals = [v for v in (survivor_finish(peers_by_run, r, target)
                             for r in base if r["status"] == "ok") if v is not None]
    fail_vals = [v for v in (survivor_finish(peers_by_run, r, target)
                             for r in fail if r["status"] == "ok") if v is not None]
    groups = [("Baseline\n(same survivors)", base, base_vals),
              (f"{target} killed\nat trigger", fail, fail_vals)]
    for label, group, values in groups:
        s = summarize(values)
        summary.append({"figure": "fig6_failure.png", "group": label.replace("\n", " "),
                        "ok": s["n"], "total": len(group),
                        **{k: s[k] for k in ("mean", "sd", "min", "max")}})
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    draw_bars(ax, groups)
    ax.set_ylim(bottom=0)
    style(ax, title_for("Survivor distribution time with one downloader failure", base + fail),
          "Time for the 5 survivors (s)")
    fig.tight_layout()
    fig.savefig(out / "fig6_failure.png", dpi=150)
    plt.close(fig)


def fig_availability(avail, runs, out: Path) -> None:
    by_strategy = {}
    for run in select(runs, L=6, S=1, scenario="baseline"):
        if run["status"] == "ok":
            by_strategy.setdefault(run["strategy"], []).append(run["run_id"])
    if not by_strategy or not avail:
        return
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    for index, strategy in enumerate(("rarest", "random", "sequential")):
        ids = set(by_strategy.get(strategy, []))
        if not ids:
            continue
        # one representative run (first repeat) per strategy, to keep lines readable
        first = sorted(ids)[0]
        rows = [a for a in avail if a["run_id"] == first]
        ax.plot([_num(a["t_s"]) for a in rows], [_num(a["min_owners"]) for a in rows],
                color=SERIES[index], linewidth=2, label=f"{strategy} (min owners)")
    ax.legend(frameon=False, labelcolor=INK_2)
    style(ax, title_for("Rarest piece's owner count over time (L=6, S=1, one run each)", runs),
          "Owners of the rarest piece", "Time since run start (s)")
    fig.tight_layout()
    fig.savefig(out / "fig7_availability.png", dpi=150)
    plt.close(fig)


def make_all(results: Path) -> list[Path]:
    runs = read_csv(results / "runs.csv")
    peers = read_csv(results / "peers.csv")
    avail = read_csv(results / "availability.csv")
    out = results / "figures"
    out.mkdir(parents=True, exist_ok=True)
    peers_by_run = {}
    for p in peers:
        peers_by_run.setdefault(p["run_id"], []).append(p)
    summary: list[dict] = []

    fig_swarm_size(runs, out, summary)
    fig_groups(runs, out, summary, "fig3_selection.png",
               "Distribution time by piece selection (L=6, S=1)",
               [("Rarest-first", {"L": 6, "S": 1, "strategy": "rarest", "scenario": "baseline"}),
                ("Random", {"L": 6, "S": 1, "strategy": "random", "scenario": "baseline"}),
                ("Sequential", {"L": 6, "S": 1, "strategy": "sequential", "scenario": "baseline"})])
    fig_groups(runs, out, summary, "fig4_seeders.png",
               "Distribution time by seeder count (L=6, rarest-first)",
               [("S=1", {"L": 6, "S": 1, "strategy": "rarest", "scenario": "baseline"}),
                ("S=2", {"L": 6, "S": 2, "strategy": "rarest", "scenario": "baseline"})])
    fig_free_rider(runs, peers_by_run, out, summary)
    fig_failure(runs, peers_by_run, out, summary)
    fig_availability(avail, runs, out)

    with open(out / "summary.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["figure", "group", "ok", "total",
                                                    "mean", "sd", "min", "max"])
        writer.writeheader()
        for row in summary:
            writer.writerow({k: (round(v, 3) if isinstance(v, float) else v)
                             for k, v in row.items()})
    return sorted(out.glob("*.png"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Plot experiment results")
    parser.add_argument("--results", default=str(REPO_ROOT / "experiments" / "results"))
    args = parser.parse_args(argv)
    written = make_all(Path(args.results))
    for path in written:
        print(path)
    if not written:
        print("no figures: runs.csv is empty or missing", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
