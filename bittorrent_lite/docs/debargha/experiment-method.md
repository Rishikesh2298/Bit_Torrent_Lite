# Experiment method

Owner: Debargha. Code: `bittorrent_lite/experiments/`. Tests: `bittorrent_lite/tests/discovery/test_experiments.py`.

## Pipeline

```bash
# 1. deterministic fixture (same bytes for everyone: fixed seed)
python -m bittorrent_lite.experiments.scripts.make_fixture --size-mib 32 --out bittorrent_lite/experiments/data

# 2. one run (smoke test)
python -m bittorrent_lite.experiments.scripts.launcher bittorrent_lite/experiments/configs/base.json --set L=2 --set name=smoke

# 3. the whole matrix: 9 configurations x 3 repeats, shuffled order
python -m bittorrent_lite.experiments.scripts.matrix bittorrent_lite/experiments/configs/base.json --repeats 3

# 4. tables and figures (matrix already runs collect)
python -m bittorrent_lite.experiments.scripts.collect
python -m bittorrent_lite.experiments.scripts.plot
```

Outputs: raw runs in `bittorrent_lite/experiments/data/runs/<run_id>/`, tables in
`bittorrent_lite/experiments/results/{runs,peers,availability}.csv`, figures and
`summary.csv` in `bittorrent_lite/experiments/results/figures/`. Both folders are in
`.gitignore`; add the final CSVs and figures to the submission explicitly.

Before the real peer works, the same pipeline runs end to end with
`bittorrent_lite/experiments/configs/stand_in.json`, which uses a synthetic stand-in peer.
Those runs are labelled `localhost-synthetic` and every figure built from
them says SYNTHETIC. They validate the tooling only.

## What one run does

1. Check fixture, metadata and that every port is free.
2. Start the tracker; wait for its `tracker_ready` event.
3. Start seeders, then downloaders, in fixed order with a fixed gap; wait
   for each `listening` event. Readiness is never assumed from a sleep.
4. Watch events until every expected downloader logs `complete`, or the
   timeout passes.
5. Failure scenario: when the designated downloader's `progress` reaches
   25 % while it is still incomplete and alive, kill it (no clean shutdown) and record the time. If it finishes
   before reaching 25 %, the run is `not_executed`, not a failure run.
6. Stop peers, then the tracker; only processes this run started.
7. Hash each downloader's output file independently; write `manifest.json`
   with config, git revision, Python and OS, file hash, ports, IDs, seed,
   timings, status and reason. Missing or incorrect required outputs and unsuccessful
   ordinary peer exits make the run fail. The matrix stops and returns nonzero on
   the first unsuccessful run; retained runs are still collected for diagnosis.

Every run uses fresh peer directories and a new tracker with an empty table.

## Controls

Fixed unless it is the variable under test: fixture (32 MiB, 64 KiB
pieces), machine, pipeline window, upload slots, startup method, software
revision. Run order is shuffled with a fixed seed. Completed peers keep
seeding until the run ends.

Startup method: `launch-sequence`. Everyone starts in the same order with
the same gap. The common distribution origin is the first peer launch, so peer
startup is included and tracker startup is excluded. Raw run duration still includes
tracker startup. No release barrier is used.

## Configurations (9)

| Name | L | S | Strategy | Scenario |
|---|---|---|---|---|
| swarm-L2 / L4 / L6 / L8 | 2 / 4 / 6 / 8 | 1 | rarest | baseline |
| select-random | 6 | 1 | random | baseline |
| select-sequential | 6 | 1 | sequential | baseline |
| seeders-S2 | 6 | 2 | rarest | baseline |
| free-rider | 6 | 1 | rarest | peer-06 has zero upload slots |
| failure | 6 | 1 | rarest | peer-06 killed at 25 % |

`swarm-L6` is the shared baseline for the selection, seeder, free-rider and
failure comparisons (same revision and timing method).

## Measurements

| Column | Definition |
|---|---|
| `completion_s` (peers) | peer's `complete` time minus that peer's launch time |
| `finish_s` (peers) | peer's `complete` time minus the first peer launch |
| `distribution_s` (runs) | latest expected downloader's `finish_s`; only if all expected downloaders completed |
| `throughput_Bps` (peers) | file bytes / `completion_s` |
| `aggregate_throughput_Bps` (runs) | L × file bytes / `distribution_s`; only when all L completed (never for failure runs) |
| `messages_sent`, `requests_sent` | complete sender-side `frame_sent` events; REQUEST frames are counted separately |
| `retries` | completed REQUEST sends for a piece after its first completed REQUEST send, across all connections |
| `hash_failures` | `piece_verification` events with outcome `hash_mismatch` |
| `uploaded_payload_bytes` | PIECE payload bytes sent (headers excluded) |
| `verified_download_bytes` | newly accepted, verified, stored bytes |
| availability | per-second owner counts per piece, rebuilt offline from `piece_verified` events; seeders own every piece |

Failure runs report survivors (L−1) as their own population. Figure 6
compares them with the same five peers in the baseline runs.

`metrics_scope=final_logged` identifies ordinary clean shutdowns with final counters.
A killed or unclean peer has empty final metric columns; `observed_*` columns retain
its logged prefix and `metrics_scope=observed_prefix` explicitly marks that limitation.
A forced kill can lose an unlogged suffix, so those values are not exact lifetime totals.
Complete frame records derive message/REQUEST counts and payload bytes; verified piece
records count each newly owned piece once. The synthetic tooling peer retains its
explicit synthetic counters and remains excluded from measured results.

Undefined values are empty, never zero. Failed, timed-out and not-executed
runs stay in `runs.csv`, and every figure label shows `ok/total`.

## Timing limits

All times come from `time.monotonic()`. On one machine every process
shares that clock, so values from different peers can be subtracted. Values
from different machines must not be compared, so the matrix runs on
localhost. These results describe this implementation on one machine's
shared CPU and loopback network, not internet-scale behaviour.

## Figures

1. Distribution time vs L (S=1)
2. Aggregate useful throughput vs L
3. Distribution time by selection strategy (L=6)
4. Distribution time with S=1 vs S=2 (L=6)
5. Within-run mean completion of the same five cooperative peers with and without
   a free rider, plus the free rider's own time. Each repeat contributes one value,
   so the displayed `ok/total` counts runs rather than pooling fifteen peer rows.
6. Survivor distribution time, baseline vs one failure
7. Owner count of the rarest piece over time per strategy (one run each)

Figures 1–6 show the mean over successful repeats, min–max whiskers, and
individual repeats as dots. Figure 7 is explicitly a single illustrative run per
strategy, not a mean of the three repeats. Availability is reconstructed from
observed readiness, piece-commit and kill events; a killed peer can have an
unobserved final suffix, so its pre-kill ownership reconstruction has that limitation.
