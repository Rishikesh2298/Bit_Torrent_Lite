# Strict measured-campaign preparation procedure

This procedure accompanies `bittorrent_lite.acceptance_tools.measured`. It is
PREPARE implementation, not an execution record or a declaration that the
campaign is ready. All tests in `test_measured.py` are unit tests with explicitly
artificial diagnostic fixtures. They do not launch peers, transfer files over a
network, collect measurement credit, or provide independent-verifier approval.

## Current gates and scope

The complete supervisor refuses to launch any run while the independent killed
peer observer is absent. `GuardedRun(..., lane="acceptance")` and acceptance
`verify_run` also refuse direct use while OS source-denial isolation is absent.
Absence of a `--file` argument is checked but cannot prove that a downloader
running under the same OS identity cannot open the source path. These are real
BLOCKED preparation requirements, with no ignore flag or fabricated zero value.

Root must validate the new helpers through genuine recorded commands before
freezing. The process/Windows-wrapper path additionally needs a genuine owned
process diagnostic; the pure unit fixtures prove parser, arithmetic, rejection
and dispatch behavior only. External challenge provision, independent audit,
coverage participation, resource headroom, source isolation, all earlier phases,
all 27 real runs, numerical CSV/plot production and visual inspection remain
separate prerequisites or campaign work. This module does not mark them complete.

The original `matrix.main` and permissive `collect` remain preserved. The strict
supervisor calls `matrix.plan_runs` to generate the original schedule and uses
`Run` planning, preflight, readiness and monitoring APIs through `GuardedRun`.
It does not call the original matrix execution loop or use collector output as
an authority. `GuardedRun` owns execute/spawn/cleanup wrappers so all application
children are registered and no unregistered `git_revision()` subprocess runs.

## Frozen matrix and configuration

The versioned base is `fixtures/measured-base.json`. Before the final freeze,
declare the attempt-specific fixture and metadata paths via the plan command's
two `--set` overrides, using JSON string values. Every primary run must use the
same fresh 64 MiB source, independent 64 KiB piece hashes, and metadata; the
post-freeze challenge sidecar is `<source>.oracle.json`. Do not overwrite or
reuse a historical fixture or attempt directory.

The exact ordered population is the original nine configurations, each with
repeats 1, 2 and 3: `swarm-L2`, `swarm-L4`, `swarm-L6`, `swarm-L8`,
`select-random`, `select-sequential`, `seeders-S2`, `free-rider`, `failure`.
The literal independent validator checks L/S/strategy/scenario for each name;
the same order seed shuffles the 27 entries. The L6/S1 rarest baseline is reused
only by analysis and occurs once per repetition in this inventory. Window 4,
64 KiB pieces, two upload slots, localhost, fixed launch schedule, commands and
all other nonvarying settings must agree. The base seed 11 yields run seeds
11001, 11002, 11003 with the original generator. Fixed method text and the entire
plan have a digest; changing and resealing a semantic violation still fails.

Supported entry points, to be wrapped by the command recorder and its guardian:

```text
python -m bittorrent_lite.acceptance_tools.measured plan BASE --set fixture=JSON_PATH --set metadata=JSON_PATH --order-seed 2026 --source-freeze SHA256 --revision COMMIT_OR_COMMIT-dirty --lane acceptance --out NEW_PLAN_JSON
python -m bittorrent_lite.acceptance_tools.measured execute --plan PLAN_JSON --snapshot SOURCE_SNAPSHOT_JSON --root NEW_MEASURED_ROOT
```

These are argument templates, not executed commands. Use the pinned interpreter
and a shell-free recorded argument vector. The current complete execute command
returns exit 3 / BLOCKED before starting peers because the observer gate is
unresolved. A newly allocated root retains its plan and campaign-outcome record.
The helper will not silently select a smaller matrix. Once prerequisite helpers
are implemented and validated, their gates require a reviewed source change and
new freeze; the existing source cannot provide acceptance credit by changing a
runtime flag. Diagnostic `GuardedRun` API calls may validate selected mechanics,
but diagnostic evidence is never promoted to acceptance.

## Process and raw-evidence contract

Each run has fresh `events`, `logs`, peer stores and output paths. Every peer and
tracker receives separate `BTL_EVENT_LOG`, `BTL_PROC_ID`, `BTL_RUN_ID` and
`BTL_LOG_STRICT=1`. Raw stdout/stderr remain opaque bytes. The supervisor records
argument vectors, actual OS PID/birth/executable identity, executable hashes,
relevant actual environment, launch/readiness/exit times and observed exits.

The returned Popen process is registered as the first action after spawning.
At readiness, independent OS process-tree, argument and environment observation
finds a unique interpreter. This handles a Windows venv redirector whose PID
differs from the executing interpreter. Every discovered ancestry identity is
registered and retained; this is explicitly a readiness-time observation and
does not claim interception of Python's internal spawn. Structured log PID is
compared to that independently observed interpreter, never used as its own
identity oracle. Exact per-process sequences start at zero and cannot have gaps,
duplicates or reordered rows. Strict logger write failures must fail the run.

Git provenance is obtained by directly reading and hashing HEAD and its loose
or packed reference files, including a worktree gitdir pointer when present.
The resolved commit must match the declared revision. An optional `-dirty` suffix
is a preserved label, not a new Git status claim; the source snapshot digest
identifies exact working file contents. This path creates no Git child process.

The real tracker must emit readiness and answer an actual bounded `POST
/announce` with JSON `file_id`, `peer_id`, `listen_port` and `event: "stopped"`.
The exact request body/hash, method/path, supplied content headers and actual
response body/status/headers/hash are retained. Request and response audit
records must agree. The fresh tracker's response must be exactly interval 5 and
an empty peer list with correct content type and length. A stopped probe avoids
adding a fake peer to the swarm. Seeder source bytes are independently rehashed
for each seeder, and the source is compared before and after the run.

Peers receive one owned stop file and a bounded clean-stop interval. Forced
ordinary-peer cleanup is a failure. Tracker termination is predeclared with the
independently observed interpreter identity and OS mechanism. On Windows the
pinned psutil path is explicitly `psutil-TerminateProcess-SIGTERM`, whose exact
exit code is 15; it is distinct from `subprocess.Popen.terminate()` exit 1.
POSIX SIGTERM termination requires the signal return code -15. Only owned,
birth/executable-matching processes are signaled. Interpreter and wrapper
ancestry must be gone. The killed target must be alive, independently identified,
at least 25% verified, and not complete before termination; that requirement is
not waived by a fast localhost transfer. A run with no actual trigger fails.

Audit JSONL, process registry files, raw outputs, metadata/source and resulting
files are hashed. Verifier checks exact child/event/output inventories, actual
exit codes, cleanup records and raw hashes. Successful launcher status is only
one condition: false or missing output hashes, nonzero ordinary exits, missing
completions, duplicate identities, synthetic runs and changed revision fail.

## Exact metrics and clock origins

Every counted message is a complete actual `frame_sent`; counts belong to its
sender. `requests_sent` counts complete REQUEST frames, and duplicate connection
plus request identities fail. Retries are defined per downloader and piece:
each complete REQUEST after that piece's first complete REQUEST, across all
connections. Queued-only and partial writes receive no request/message credit.

Uploaded bytes sum complete PIECE payload writes, excluding headers. Each write
must agree with one upload-ack event. Useful verified bytes sum each distinct
`piece_verified` ownership commit once, with exact independent piece size and a
matching prior stored-verification result. Each commit must also match one actual
PIECE receive and a remote peer's complete PIECE send using peer identity,
request/piece/length and reversed actual endpoint tuples. Hash failures count
`piece_verification` results labeled `hash_mismatch`; they are not local I/O or
length errors. The normal matrix rejects unexpected verification/storage faults.

An initial seeder's CLI also emits `complete(final_hash_ok=true)` after verified
assembly of its already-owned source. Diagnostic 065 exposed an incorrect
verifier rejection of this existing behavior. The original master guide defines
S as initially complete seeders (line 561); Debargha's plan defines newly stored
download bytes (lines 202, 212), and the controlling plan excludes already-owned
bytes (lines 706–707). The verifier now requires exactly one true source-ready
event, source validation before launch bound to the seed's `--file` argument,
full ownership in the first pre-completion and all subsequent scheduler snapshots,
consistent SEEDING/ownership status and zero downloaded bytes, requests, retries,
hash failures or received/committed pieces. It independently compares the seed's
assembled output size, hashes and every byte against the source. This source-ready
event never enters downloader completion times, expected completers, distribution
finish or useful-byte numerators. Artificial negative controls reject duplicate,
missing or false ready events, invented download credit/commits/requests, incomplete
initial ownership, late source validation and corrupt assembled seed output. The
separate actual localhost lifecycle test asserts this real CLI behavior; unit
fixtures provide no real-network or acceptance credit.

A normal peer requires one listening record, final counters, final clean exit,
strict complete event sequence, writer queue telemetry, scheduler queue telemetry
and resource samples. Counter fields that exist must match independent event
arithmetic. Unknown fields, absent samples or incomplete lifetime evidence are
errors/BLOCKED, not zeroes. Resource schema includes RSS, threads, TCP sockets,
user/system CPU and either Windows handle or file-descriptor count. Queue depth
may not exceed its declared capacity. Maxima are observed sample maxima, not a
claim of continuous OS sampling.

Distribution time starts at the **first peer launch**, excluding tracker setup,
and ends at the last expected downloader's verified completion. Per-peer
completion starts at that peer's own process launch. The legacy launcher's raw
tracker-origin duration is retained under an explicit distinct name; its actual
end precedes cleanup, so the new supervisor separately records total duration
including cleanup. Unit controls exercise the numerical difference. The derived
useful aggregate B/s is surviving completed downloader count times independent
source size divided by distribution time; a killed target contributes no
completed file. Availability derives from valid initial seeder ownership,
verified commits and actual peer lifetimes, excluding departed peers.

For a deliberate kill, a final partial JSONL record is retained uncounted only
with a corroborated supervisor kill. A complete last line is not proof of exact
final counters: a process can be killed between actual write/commit and logging.
No callback supplying scalar values is accepted. A separately validated observer
must establish complete transport and verified-storage intervals with identity,
sequence/gap/termination proof and raw evidence from which all metrics can be
recomputed. Pre-kill samples alone cannot do this. Until that observer exists,
all 27 primary runs remain NOT RUN, including otherwise executable baselines.

## Validation partition and first-failure behavior

`test_measured.py` belongs to Phase 03 unit testing. It covers original matrix
generation, independently checked population/order/fixed settings, fail-first
dispatch, complete identity reconciliation, metric arithmetic, stream schemas,
strict sequence/PID, endpoint provenance, availability, independent file oracles,
direct Git reference reading, and semantic artifact negative controls. Its
artificial artifact tree stubs OS-process lookup deliberately and has lane
`diagnostic` plus a unit-only configuration; it must never be counted as a real
network run. Do not use its expected unit outcomes as human verification.

The exact selectors and deliberately limited requirement domains are in
`measured-mapping.json`. Function parameterizations must be expanded into exact
collected IDs by the root recorder/ledger; no authored count substitutes for
collection. The parent performs all diagnostic execution sequentially. No test
or helper execution was performed while authoring these files.

The supervisor verifies one run before starting another. An exception, semantic
failure, inconsistent result or duplicate ID propagates immediately. Preserved
outcomes identify already verified diagnostics and remaining NOT RUN/NOT VERIFIED
items; partial results have no campaign acceptance credit. An unexpected campaign
failure requires owned cleanup, diagnosis/regression repair, fresh source and
dependency/configuration freeze, a new attempt and the complete restart from
Phase 00. Focused diagnostic success cannot resume or complete a prior attempt.

CSV grouping/joins, final original-plan comparisons and all five plot families
still require their own reviewed numeric/visual procedures; this file does not
claim EV05/EV06 completion or delegate authority to the permissive collector.
