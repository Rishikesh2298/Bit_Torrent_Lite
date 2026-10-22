# PREPARE stress workload and supervisor

This is preparation documentation. Authoring the helper or passing its unit tests
does not run Phase 08 or make the acceptance prerequisites ready. Every emitted
pilot or local stress result has `acceptance_eligible: false`. The acceptance
lane blocks before launching children because no validated OS/remote source
isolation adapter and independent final stress verification are implemented.
The graceful churn workload does not require killed-peer transfer totals. The
measured failure experiment's killed-peer observer is a separate prerequisite.

## Contracts

`bittorrent_lite.acceptance_tools.stress` supplies:

- `make_plan(...)` / `validate_plan(...)`: all 16 ordered configurations from
  seeders `{1,2}`, downloaders `{6,8}`, upload workers `{0,2}`, windows `{1,4}`.
  Duration is at least 1800 seconds and at least 100 deterministic declared
  churn cycles per configuration. The seed, source fingerprint, limits, every
  churn slot, and transition deadline are included in the plan hash.
- `make_pilot_plan(...)`: a distinct fixed PREPARE pilot, one seeder and six
  downloaders, two upload workers, window four, a 60-second hold and one churn
  cycle. Startup is at most 45 seconds and normal cleanup at most 15 seconds.
  This is never accepted by `validate_plan` and cannot supply a grid case.
  Recorder emergency cleanup has its own bounded period after a timeout.
- `diagnostic_workload(...)`: actual tracker/peer subprocesses, genuine TCP
  transfer, independent output bytes/hash checks, finite resource assertions,
  cooperative stops and fresh peer generations. No arbitrary command or shell
  input is accepted; the helper uses the project's `Swarm` support and fixed
  module CLI.
- `supervise(...)`: fresh output directory, source snapshots before/after,
  recording/guardian for every worker command, sequential execution and stop
  after the first failed command or semantic oracle. Previous cases are retained
  as diagnostics; they cannot be combined with a later acceptance attempt.
- `verify_case(...)`: re-read raw events/artifact hashes, exact process/lifecycle
  inventory, event-to-process identities, deterministic schedule, real socket
  send/receive/commit references, retained piece bytes, complete output hashes,
  observed resource maxima/settling and expected graceful exit codes. This is
  diagnostic semantic verification, not a separate final acceptance authority.

## Run the preparation pilot

Use the pinned preparation interpreter and an existing `RecordingSession` so the
outer command has a guardian. Do not execute the following from an unrecorded
interactive shell. Pass the current source snapshot's exact `sha256`; any edit
after that snapshot blocks launch. Choose a fresh output directory under the
retained preparation evidence root.

```text
<pinned-python> -m bittorrent_lite.acceptance_tools.stress pilot
  --limits bittorrent_lite/docs/integration/STRESS-PILOT-LIMITS.example.json
  --source-freeze <current-source-snapshot-sha256>
  --repo <absolute-BitTorrent-root>
  --out <fresh-absolute-preparation-directory>
```

The example limit file contains provisional pilot safety ceilings, not measured
or approved acceptance baselines: 512 MiB RSS / 128 threads / 64 TCP sockets /
1024 descriptors per peer; a 10 GiB free disk floor, 1 GiB retained raw-log
budget and 1 GiB available RAM headroom. Its bounded growth allowances likewise
are provisional. A pilot PASS only says observations stayed within those stated
ceilings. Review the genuine retained samples and justify tighter/full-campaign
ceilings separately; never change a bound merely to turn a failing case green.
The full grid rejects `pilot_evidence: null`.

No host-wide firewall/traffic control changes, global disk filling, source
deletion, or broad process killing occur. Every source/partial piece/assembled
output and raw log remains retained. Paths in persisted configuration are
portable; absolute paths occur only in command/process/evidence records.

## What the real workload does

Each source is 64 MiB (1024 pieces) and each initial downloader must complete
with independent byte/hash verification before the hold clock begins. The
tracker and all continuing peers remain alive for the entire declared hold,
even after download completion. Every cycle selects its predeclared logical
downloader slot, gracefully stops that generation, joins a fresh probe, then
requires matching raw `frame_sent` / `frame_received` / `piece_verified` facts.
Endpoint pairs, peer/process identities, request IDs, piece indices, sizes and
committed bytes must agree. The probe is stopped while recent observations
show pending download requests, active source upload jobs and occupied source
writer queues. No such evidence before the deadline means FAIL, not a synthetic
or idle-cycle substitute. A fresh keeper then joins, completes, and replaces the
slot. This supplies at least two actual join/stop transitions per cycle.

All live peers supply actual process RSS, threads, TCP sockets, CPU times and
OS handle/file-descriptor counts. The resource sample gap is bounded to at most
three seconds. Per-connection request windows, event/writer queue capacities,
active uploads and retained neighbor counts are asserted against explicit
limits. Each cycle must show a continuous settling interval (at least two
seconds and at least two genuine resource samples per surviving peer), no
pending/active upload work, and resources within reviewed baseline growth.
After shutdown all owned wrapper/interpreter processes must be gone and the
supervisor must return within its declared baseline allowance. Strict event
sequence and OS-observed interpreter identity checks detect missing/reordered
records and Windows virtual-environment launcher mismatches.

Resource maxima are sampled maxima; the helper makes no claim to capture peaks
between samples. Busy-work facts are observations within the configured maximum
age (at most one second), not an atomic promise that another thread cannot finish
immediately afterward. Full acceptance must review that concurrency limitation.

## Full local diagnostic grid and resource planning

Copy/review limits into a new portable JSON file. `pilot_evidence` must identify
the genuine retained pilot report with a repository-relative path and SHA-256.
That hash proves a binding to bytes, not approval or suitability of the limits.
Freeze a new source/dependency/configuration snapshot after all edits, then:

```text
<pinned-python> -m bittorrent_lite.acceptance_tools.stress plan
  --limits <reviewed-limits.json> --source-freeze <sha256>
  --duration-s 1800 --cycles 100 --seed 2026 --lane diagnostic
  --out <fresh-plan.json>

<pinned-python> -m bittorrent_lite.acceptance_tools.stress run
  --plan <fresh-plan.json> --repo <absolute-BitTorrent-root>
  --out <fresh-recorded-grid-directory>
```

`run` must itself run under the recorder. It does not have a subset/resume flag.
An `acceptance` plan is allowed to be prepared but its preflight always reports
BLOCKED before launching. There is no acceptance override switch.

The disk preflight currently uses the conservative mathematical estimate
`cases * 64MiB * (1 + 2*(10 + 2*cycles)) + log_budget + free_disk_headroom`.
It assumes every initial/probe/keeper could retain both all pieces and a complete
assembled output; it is not a measured reservation. At 16 configurations and
100 cycles the data term alone exceeds 400 GiB, so hosts below that estimate
remain blocked. The pilot records actual retained file/log sizes and per-peer
resource sample counts/maxima for a reviewed sizing refinement. A single
pilot's observed partial-probe size is not a guaranteed future upper bound.
Any refined budget must justify worst-case retention and failed-attempt headroom
and preserve existing evidence. Available RAM is measured and checked against
12 simultaneous process RSS ceilings plus explicit headroom.

## Validation and remaining acceptance gaps

Run `tests/acceptance/test_stress.py` as a recorded PREPARE unit phase. These are
pure helper tests and explicit artificial row fixtures, with no subprocess or
socket execution. Then run the separate genuine pilot command. Preserve every
failed pilot and repair the helper/product with regression coverage before a
new source freeze and fresh pilot. Do not reclassify pilot evidence as Phase 08.

The following remain separate required work: real source-denial isolation; the
fresh challenge/independent final verification procedure; reviewed resource
limits and all 16 full runs; SC03 intermediate windows two/three; original
SY11 slower links/latency and other required fault cases; the 27 measured runs;
two-owner laptop/LAN portability; coverage and exact requirement/test ledgers.
This helper does not claim any of those completed.
