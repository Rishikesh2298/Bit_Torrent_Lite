# Final acceptance test plan and Astra execution handoff

**Prepared: 22 October 2026 · Timezone: Asia/Calcutta · Status: PLAN ONLY — NOT EXECUTED.**

This is the single controlling plan for a new, beginning-to-end acceptance
campaign, followed by a comparison against all five original project plans.
Astra is the intended executor in a separately authorized session. Preparing
this document does not authorize running it in the current session.

**Readiness:** this is an acceptance specification and runbook, not a claim
that all specified tests/helpers already exist. The existing suite is runnable;
complete acceptance is blocked until the PREPARE gate in §4 has executable,
reviewed methods for every case. The independent static review and comparison
record is in Appendix D. No test result is asserted by that review.

The purpose is to leave no project area silently unexamined. No finite test
plan can guarantee the absence of every error. Accordingly, missing evidence,
unimplemented test tooling, untested platforms and uncovered requirements
produce an explicit incomplete/blocked result, never an assumed pass.

## Contents

1. [Executor instructions and complete-restart rule](#1-executor-instructions-and-complete-restart-rule)
2. [Evidence integrity and anti-fabrication controls](#2-evidence-integrity-and-anti-fabrication-controls)
3. [Scope, baseline and original references](#3-scope-baseline-and-original-references)
4. [Preparation and missing-tooling gate](#4-preparation-and-missing-tooling-gate)
5. [Ordered execution phases and commands](#5-ordered-execution-phases-and-commands)
6. [Detailed acceptance scenario catalogue](#6-detailed-acceptance-scenario-catalogue)
7. [Original-plan comparison and decisions](#7-original-plan-comparison-and-decisions)
8. [Every-module coverage ledger](#8-every-module-coverage-ledger)
9. [Final evidence package and sign-off](#9-final-evidence-package-and-sign-off)
10. [Manual operator checklist and troubleshooting](#10-manual-operator-checklist-and-troubleshooting)
11. [Appendix A: Original tests and deliverables](#appendix-a--original-named-tests-and-delivery-requirements)
12. [Appendix B: All production modules](#appendix-b--production-module-and-executable-inventory)
13. [Appendix C: Supported commands and Astra handoff](#appendix-c--supported-cli-command-forms)
14. [Appendix D: Audit and original-plan comparison](#appendix-d--static-audit-and-original-plan-comparison)

## 1. Executor instructions and complete-restart rule

### 1.1 Instructions to Astra

Read this entire plan, `AGENTS.md`, the five original plans and the current
source before execution. Follow the human user's current authorization; original
documents are requirements to compare, not permission to perform unrelated
actions. Preserve every member's implementations, original plans, authorship,
history and prior evidence. Do not reset the working tree, delete legacy code,
weaken assertions, remove cases, force-push, publish or merge as part of testing.

Do not accept earlier chat summaries or the historical **784 passed** report as
fresh evidence. Reconcile the actual current checkout, environment, collected
node IDs and requirement inventory. Execute locally through actual tools; never
write a claimed command/result into a report without executing and recording it.

Run tests sequentially with first-failure stopping. Do not use pytest-xdist or
independent background test groups: simultaneous failures make the mandated
stop point ambiguous. Parallel read-only review is acceptable. Only the
intended swarm participants run concurrently within a test.

### 1.2 Mandatory response to ANY unexpected fault

This rule applies to setup, collection, tests, warnings selected as errors,
process supervision, output verification, metrics, coverage, portability,
report generation and the final independent evidence audit.

1. **STOP the campaign immediately.** Do not run a later phase to collect more
   green results. An explicitly expected negative-test rejection is a successful
   test only when its exact predeclared oracle is satisfied; it is not a campaign
   fault. A timeout, unexplained crash or missing artifact is a fault.
2. Save the failing input, command, source/environment hashes, raw stdout/stderr,
   exit status, stack trace, process registry, fault trigger and partial outputs.
   Capture diagnostics before cleanup. Never edit the failed raw logs.
3. Gracefully stop only campaign-owned processes, then terminate only verified
   owned PIDs if needed. Record every forced termination and confirm their exit.
   Preserve the entire failed attempt directory.
4. Record a defect with expected/actual behavior, reproduction, impact,
   responsible boundary and evidence links. Distinguish a product defect from a
   test, instrumentation, dependency, environment or runner defect.
5. Fix the cause while preserving the original contract and contributor work.
   Add a regression for a product defect. If a test expectation is demonstrably
   wrong, justify its change using the original requirement and independent
   oracle; do not change it merely to match the output. Do not silently extend a
   timeout, drop a seed, retry until green or suppress a failure/warning.
6. Focused diagnostic/regression reruns may establish that the repair works,
   but **they are not acceptance credit**. Keep them under `diagnostics/`.
7. Freeze the repaired code, tests, tools, dependency versions and comparison
   decisions. Allocate a **new attempt ID, environment/output directories and
   result files**. Replay the original campaign challenge for regression, and
   obtain an additional fresh human/verifier token after the repaired freeze.
   Include that fresh challenge in integrity/redistribution checks; never drop
   an earlier failing input or substitute only favorable seeds. Keep the fixed
   matrix fixture identical across all 27 runs of the new attempt.
8. **RESTART THE ENTIRE TESTING FROM PHASE 00.** Repeat environment/provenance,
   collection, all unit/component/integration/system/end-to-end tests, all
   portability and stress cases, all 27 measured runs, analysis, and the final
   audit. Do not resume at the failed case, failed module or last checkpoint.
9. Only the final uninterrupted successful attempt on one frozen revision and
   configuration can support complete acceptance. Earlier attempts remain in
   the failure history and must not be pooled into its performance results.

Any source, test, runner, instrumentation, dependency or acceptance-criterion
change after the freeze invalidates current acceptance progress and triggers
the same full restart. Changing explanatory prose does not alter results, but
changing what constitutes a pass does. User-requested pauses are safe only after
owned processes stop and evidence is sealed; after resumption, recheck hashes.
If anything relevant changed during the pause, restart Phase 00.

Predeclared negative inputs, controlled fault injection and live-change viva
exercises are not repairs to the frozen acceptance source. Perform live source
changes only in a separately identified disposable teaching copy, record its
derived source hash and tests, and never count its results as frozen-release
results. This avoids an endless restart caused by the required live-change demo.
Any actual fix to the acceptance code/tests/tools still triggers the full restart.

### 1.3 Outcome vocabulary

Use `PLANNED`, `PASS`, `FAIL`, `BLOCKED`, `NOT RUN`, and `DEVIATION—REVIEW REQUIRED`.
Never turn BLOCKED/NOT RUN into PASS. A condition outside the original scope
may be `OUT OF ORIGINAL SCOPE`, but any shipped implementation of it still needs
tests. Human-approved scope exclusions must remain visible in the report;
they do not become evidence that the excluded behavior works.

## 2. Evidence integrity and anti-fabrication controls

### 2.1 Evidence required for every claim

Each execution record must contain: campaign/attempt/case IDs; actual executable
and argument array; working directory; relevant environment variables; UTC and
local timestamps; elapsed monotonic time; real PID and creation time; exit code
or terminating signal; timeout status; raw stdout/stderr paths and SHA-256 hashes;
source/test/tool/config/environment snapshot hashes; and the expected oracle.
Record actual command completion, not a shell's later `$LASTEXITCODE` after an
unrelated command. Both stdout and stderr must be retained without truncation.

Results must link to raw evidence. Summaries, screenshots, copied terminal text,
assistant statements, or a hand-written JSON/XML file alone are not sufficient.
JUnit XML must be generated by the invoked pytest process. Manifests/CSV/plots
must be generated from the recorded runs, not filled manually with plausible
numbers. Never paste old `.validation/` evidence into the new attempt.

### 2.2 Freeze and chain of evidence

- Snapshot every production `.py`, test `.py`, CLI/configuration, original plan,
  acceptance tool, coverage configuration and dependency lock. Store relative
  paths, SHA-256, size and a sorted manifest. Git HEAD alone is insufficient:
  the repository currently contains uncommitted work.
- Save `git status --porcelain=v1`, HEAD, branch, tracked diff and an explicit
  untracked-file inventory. Include moved files' contents through the file
  manifest, since a diff alone omits untracked replacement directories.
- Hash before and after every phase. Unexpected additions/removals/changes
  invalidate the attempt. Exclude only enumerated generated evidence, caches,
  environments and downloads; do not use broad exclusions that hide source.
- Seal each finished phase with a manifest hashing its raw artifacts and the
  previous phase seal. Give the initial and final digest to the human/reviewer
  outside the executor's writable result directory. A local hash chain detects
  later edits only when its digest is independently retained; it is not an
  unforgeable proof against the same agent rewriting everything.
- Keep the original inputs and failed attempts. No log editing, timestamp
  rewriting, evidence replacement, selective outlier removal or combining
  artifacts from different source snapshots.

### 2.3 Fresh challenges and independent oracles

Have the human or independent verifier provide a fresh challenge token after
the test/source freeze. Record it in the external review record, fixture
manifest and attempt metadata. Build reproducible, distinct-per-piece binary
fixtures from it; additionally use independently generated random fixtures.
Do not rely solely on the old helper's repeated 64 KiB block pattern: identical
pieces can hide ordering/index errors. Include different first/last bytes and
unique content in every full piece, plus zero bytes and non-UTF-8 bytes.

An independent verifier computes expected whole-file and per-piece SHA-256
directly from fixture bytes using standard-library hashing, without importing
the project's storage or metadata code. Compare these to project metadata and
completed files. Check exact byte count and byte-for-byte equality as well as
hashes. Hashes must be recomputed from files, not trusted from a manifest flag.

For proof of real P2P, give receivers metadata but **no source-file access**:
use separate laptops, containers/accounts with verified read denial, or another
documented isolation boundary. A filename rename on a shared machine is useful
evidence but not as strong as inaccessible source storage. Verify that neither
the supervisor nor a stand-in copies source bytes into download directories.
Capture actual connection endpoints and request/PIECE provenance. Test transfer
from a completed downloader after the original source and seeder are unavailable.

### 2.4 Detect weak or fabricated tests

- Reconcile collected node IDs with executed terminal outcomes and JUnit cases:
  exact sets, no duplicate IDs, missing cases, deselections, skips, xfails or
  unexpected xpasses. Parameterized cases count individually. Count agreement
  alone does not prove identity agreement.
- Scan `pytest.ini`, `pyproject.toml`, conftest/plugins, marker expressions,
  environment variables, ignore lists and test diffs for hidden filtering.
  Do not use the older stage selector files: they predate the new modules.
- Review assertions, fixtures and mocks. No mock backend, copied file,
  synthetic event source, hard-coded success, catch-all swallowing or fallback
  to a stand-in is permitted in a case labelled REAL.
- Test the verifier with negative controls: alter one downloaded byte, truncate
  a result, delete a required case/result, change one source hash, insert a
  synthetic manifest into the real corpus, and supply a failed/empty manifest.
  Each must be rejected in isolated verifier fixtures. Predeclare these expected
  rejections; do not corrupt the authoritative evidence files.
- Missing request/retry/hash-failure metrics must stay missing. Add validated
  instrumentation before acceptance; never insert zero, infer an exact partial
  `sendall` byte count, or derive upload success from enqueue operations.
- Review excluded coverage lines and subprocess configuration. Import coverage
  alone does not establish function behavior; a high aggregate percentage must
  not conceal an unused module or unasserted failure path.

### 2.5 Independent final verification

A separate reviewer/session or the human must receive the frozen source/test
bundle and sealed artifacts. It must independently parse logs/XML/manifests,
recompute hashes/counts/formulas, inspect assertion changes and run fresh
checks selected after Astra's report: at least one full suite invocation,
one challenged file transfer, source-isolated redistribution, and one fault
scenario. Prefer a different environment/account. Do not give it write access
to the executor's evidence. Record what it actually reran.

Astra may finish execution without this reviewer being available, but the final
label must then be **EXECUTION COMPLETE; INDEPENDENT VERIFICATION PENDING**.
No same-agent checklist or self-authored signature substitutes for independent
attestation. These controls make fabrication detectable; they cannot make
self-reported evidence mathematically impossible to falsify.

## 3. Scope, baseline and original references

Active repository at preparation time:
`C:\Users\KIIT\Documents\ChatGPT\cn project\BitTorrent`.
On another laptop, choose its actual repository directory; never copy this
machine's absolute paths into product code. All commands below start at the
repository root unless an explicit external working directory is stated.

Historical baseline only: 784 passed on Windows/Python 3.12.14, comprising the
737 earlier cases plus 33 real E2E, 12 adapter and two import cases. Read
[the prior report](end-to-end-validation-2026-10-22.md) and
[its node-ID inventory](end-to-end-validation-inventory.json) as an inventory
reference, not current evidence. Add tests wherever this plan identifies gaps;
the final count is expected to increase. Never reduce it to force agreement.

Original references, preserved verbatim:

- **G** — [Revised project guide](../plans/original/BitTorrent-Lite-Revised-Project-Guide.md).
- **R** — [Rishikesh's original plan](../plans/original/01-Rishikesh-Individual-Plan.md).
- **D** — [Debargha's original plan](../plans/original/02-Debargha-Individual-Plan.md).
- **A** — [Anik's original plan](../plans/original/03-Anik-Individual-Plan.md).
- **P** — [Prabhat's original plan](../plans/original/04-Prabhat-Individual-Plan.md).

Also review the four preserved `docs/plans/follow-up/` plans, current protocol,
backend guide, ownership map and source. When the implementation, original plan
and follow-up contract differ, record the conflict; do not silently pick the
easiest oracle. The user's approved `BitTorrent/bittorrent_lite/` layout takes
precedence over the original guide's suggested `src/` layout.

Scope includes all production modules, alternate/legacy implementations,
standalone CLIs, examples, packaging, config/logging utilities, tests, fixtures,
real/synthetic experiment tooling, documentation and original deliverables.
Generated environments/caches and archived historical checkouts are inventory
items, not code to execute as the current product. Preserve and label them.

Original exclusions remain explicit: DHT, magnet links, NAT traversal, internet
deployment, encryption, multifile torrents, compression, databases, web dashboards,
super-seeding and commercial-client compatibility. Automatic crash-resume and
endgame were also originally excluded, but preserved implementations/extensions
now exist and need their own tests. Do not add excluded features to satisfy an
unqualified interpretation of "everything". Compare scope and test shipped work.

## 4. Preparation and missing-tooling gate

### 4.1 No invented commands or silent untested cases

Labels used in this plan:

- **EXISTING**: an executable test/CLI already present; verify its interface
  in the current checkout before running it.
- **MANUAL**: an operator action with explicit evidence and pass/fail oracle.
- **PREPARE**: additional helper, instrumentation or test must be authored and
  independently reviewed before the freeze. It is **not already implemented**
  merely because it is specified here.

Every detailed case must be assigned to an actual pytest node ID or a versioned
manual procedure. If the association cannot be made, stop at this preparation
gate with that case BLOCKED. Do not proceed with an allegedly exhaustive
campaign while mandatory cases have no executable method.

### 4.2 Required acceptance tooling to prepare before freezing

These tools may be created in the separately authorized execution session.
This plan does not create them now.

| Helper | Required behavior and its own negative controls |
|---|---|
| Command recorder | Shell-free argument arrays; explicit cwd/environment; separate untruncated stdout/stderr; real PID/start/end/exit; timeout; command/config/input/log hashes; exception records; reject reused output paths |
| Process guardian | Register every child with PID + creation time + executable + args + owner run; observe readiness; bounded waits; graceful stop then verified-PID cleanup; report orphans even if pytest dies; never kill all Python processes |
| Collection ledger plugin | Capture exact node ID, markers and source for each case; reject skips/deselection/xfail; emit each call/setup/teardown outcome; compare final collected and executed sets |
| Snapshot/seal tool | Include source, tests, scripts, configuration, original plans and untracked files; stable relative paths; before/after comparison; external digest retention |
| Fixture/oracle tool | Unique-per-piece challenge-derived and random bytes; independent size/hash/byte comparisons; no import of project verification code |
| Socket fault peer/proxy | Valid framing plus controlled bad fields/content, fragmentation, coalescing, delays, drop/close and bandwidth constraints; log actual bytes/triggers; affect only test sockets |
| Storage fault adapter | Deterministic permission/write/replace/read/final-assembly faults in campaign-owned paths; prove no source/data destruction; do not fill the user's system disk |
| State/metrics instrumentation | Time-stamped request ID/connection ID/piece transitions, queue/window/slot bounds, full-write acknowledgements, retries/hash failures, thread/socket/job counts; preserve behavior and original ownership |
| Matrix supervisor | Exactly 27 frozen primary configs; one run at a time; stop after first unexpected status/hash/cleanup anomaly; audit manifest contents, not just shell exit |
| Evidence verifier | Exact inventory/row reconciliation, file hash checks, formulas, synthetic/real separation, timestamp/config consistency and tamper/negative controls |
| Subprocess coverage setup | Measures tracker and peer child interpreters as well as pytest; distinct data files; graceful flush; combines only this attempt and checks child participation |

Use controlled fake clocks/providers for deterministic boundary tests; use real
sockets/processes for cases labelled real. A fake socket proves a writer's local
acknowledgement rules, not real network throughput. Add necessary new tests
without discarding existing tests or flattening member-owned packages.

### 4.3 Safe PowerShell setup template

Run only in the future authorized session. These commands create a new attempt,
not a reusable result directory. Do not paste Bash line continuations into
PowerShell. Use argument arrays and quote paths containing spaces.

```powershell
# Open this terminal in the BitTorrent checkout on this machine before starting.
$SavedTestErrorActionPreference = $ErrorActionPreference
$SavedTestEnvironment = @{}
foreach ($EnvName in @('TEMP','TMP','MPLCONFIGDIR')) {
    $SavedTestEnvironment[$EnvName] = [Environment]::GetEnvironmentVariable($EnvName, 'Process')
}
$ErrorActionPreference = 'Stop'
$Repo = (Get-Location).ProviderPath
if (-not (Test-Path -LiteralPath (Join-Path $Repo 'pyproject.toml'))) { throw 'Wrong repository root' }
if (-not (Test-Path -LiteralPath (Join-Path $Repo 'bittorrent_lite'))) { throw 'Missing package' }
$CampaignId = (Get-Date).ToString('yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8)
$AttemptRoot = Join-Path $Repo ('.validation\final-acceptance\' + $CampaignId + '-attempt-01')
if (Test-Path -LiteralPath $AttemptRoot) { throw 'Never reuse an attempt directory' }
New-Item -ItemType Directory -Path $AttemptRoot | Out-Null
$AttemptRoot = (Resolve-Path -LiteralPath $AttemptRoot -ErrorAction Stop).ProviderPath
if (-not (Test-Path -LiteralPath $AttemptRoot -PathType Container)) { throw 'Attempt directory was not created' }
'environment','inventory','commands','logs','junit','fixtures','runs','coverage','defects','seals','report','temp' | ForEach-Object {
    $StagePath = Join-Path $AttemptRoot $_
    New-Item -ItemType Directory -Path $StagePath | Out-Null
    if (-not (Test-Path -LiteralPath $StagePath -PathType Container)) { throw 'Missing attempt subdirectory' }
}
$env:TEMP = Join-Path $AttemptRoot 'temp'
$env:TMP = $env:TEMP
$env:MPLCONFIGDIR = Join-Path $AttemptRoot 'environment\matplotlib'
New-Item -ItemType Directory -Path $env:MPLCONFIGDIR | Out-Null
```

The reviewed supervisor must execute setup/work inside `try/finally`, perform
owned-process cleanup on every exit path, then restore the saved process-local
settings below. A nonterminating PowerShell directory error must not allow later
steps to continue. Confirm the resolved attempt path remains under the intended
campaign root; reject unexpected symlink/junction redirection before writing.

```powershell
# Supervisor finally block, after bounded owned-process cleanup:
foreach ($Entry in $SavedTestEnvironment.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($Entry.Key, $Entry.Value, 'Process')
}
$ErrorActionPreference = $SavedTestErrorActionPreference
```

On another machine start in that machine's actual BitTorrent checkout.
Do not copy `.venv` between laptops. Select and record an installed interpreter,
create a fresh attempt-owned environment, and install the project:

```powershell
$BootstrapPython = (Get-Command python -ErrorAction Stop).Source
& $BootstrapPython --version
if ($LASTEXITCODE -ne 0) { throw 'Python unavailable' }
& $BootstrapPython -m venv (Join-Path $AttemptRoot 'environment\venv')
if ($LASTEXITCODE -ne 0) { throw 'Environment creation failed' }
$Py = Join-Path $AttemptRoot 'environment\venv\Scripts\python.exe'
& $Py -m pip install -e '.[test,experiments]'
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& $Py -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Broken dependencies' }
```

Run these through the prepared recorder when establishing the real campaign.
After the first preparation environment is proven, freeze package versions and
wheel hashes. Recreate later attempts from that lock; do not resolve a different
latest version after each failure. Coverage tooling is not included in the
project extras: install and pin it explicitly during preparation if used.
Retain the Python build, OS, hardware/RAM/disk, locale, timezone and dependency
versions. Verify actual interpreter paths; reject a Microsoft Store alias or
unexpected globally installed interpreter. Restore caller environment variables
after the campaign instead of modifying system-wide settings.

The historical environment used Python 3.12.14, pytest 9.1.1, pytest-timeout
2.4.0, matplotlib 3.10.3, NumPy 2.2.6 and pandas 2.2.3. These are a comparison
point, not a guarantee that arbitrary updated versions behave identically.

### 4.4 Resource, warning and execution-readiness gate

Before starting acceptance, record available hosts/OS/Python versions, reachable
test interfaces, free disk, RAM, process limits and a realistic time budget.
The added stress grid alone takes at least eight hours, excluding setup, churn
completion, all other phases and any full restarts. Estimate disk for retained
pieces **and** assembled outputs, per-attempt environments, raw logs, fixtures,
27 matrix runs and failed attempts. Reserve explicit headroom using measured
pilot usage; never solve low space by silently deleting evidence or reusing
downloads. A missing resource blocks execution before the affected workload.

Freeze a warning policy and configure it in the recorded pytest arguments or
reviewed configuration. At minimum, make
`pytest.PytestUnhandledThreadExceptionWarning` and
`pytest.PytestUnraisableExceptionWarning` fatal, so first-failure stopping works
when a worker fails. Treat other unexpected warnings as failures; any allowed
third-party deprecation needs its exact category/message/source, justification
and frozen allowlist. Do not blanket-ignore warnings. The old matplotlib
deprecation report is context, not an automatic exemption for new warnings.

The preparation sign-off needs: complete case-to-method ledger; tested recorder,
guardian, verifier and child coverage; reviewed fixture/oracle; agreed finite
boundary/permutation/property-test domains and seeds; frozen warning policy;
available resources; independent reviewer/challenge arrangements; and resolved
required contract decisions. "Test everything" does not mean enumerating an
infinite input domain: publish the exact exercised partitions and uncovered
limitations. Do not start acceptance with a mandatory row lacking a procedure.

## 5. Ordered execution phases and commands

No phase begins until the preceding phase's evidence is verified and sealed.
The command recorder must run each command, save its real exit status and stop
on failure. Never run this entire section as an unchecked shell paste. Phase 01
uses installation/static checks and non-networking help/configuration smoke;
functional standalone examples run in Phase 05, after unit and integration gates.

### Phase 00 — provenance, preparation and freeze

1. Read applicable instructions; inventory current branch, HEAD, dirty and
   untracked files. Preserve the current reorganization; do not switch to stale
   main or an archived review checkout.
2. Compare the five original plan hashes and all mapped original files against
   `path-migration.json`; inspect intended changes without overwriting originals.
3. Build the requirement, module/function and test ledgers described below.
4. Complete/review all PREPARE items, dependency setup, recorder/guardian/verifier
   negative controls and the fixture generator. Preparation diagnostics
   have no acceptance credit.
5. Freeze source/tests/tools/configs/environment/criteria, then get the challenge
   token. Generate the actual fixtures only after receiving it; hash the token,
   generated inputs and independently computed oracles into the input seal.
   A discovered gap after this point requires a repair and full restart.

**Exit oracle:** all required cases have a method; manifest hashes verified;
external seal stored; no planned test labelled PASS.

### Phase 01 — environment, installation, portability smoke and static checks

Verify installation and import origin in the selected interpreter; check all
source syntax, JSON/TOML, local documentation links and member file preservation.
Do not equate successful compilation with runtime correctness. Check console
scripts, `python -m bittorrent_lite`, metadata CLI, tracker CLI and standalone
CLIs from both the repository and an unrelated directory with spaces/Unicode.
Run with PYTHONPATH removed. Do not rely on old `tools/anik-review-deps`.

Check wrong/missing arguments, safe peer ID, port limits, invalid source or
metadata, path traversal/absolute metadata filename, source/output collision,
working-directory independence, invalid tracker URL and occupied listener port.
`--check-config` validates its supported argument/metadata inputs without opening
sockets or creating download output. It currently returns before source/output
collision checks and FileStore seeder-content verification: test those through
the real startup path; do not infer them from a successful config check. Capture
expected nonzero usage/rejection codes distinctly.

Build a wheel and source distribution, install each into separate fresh
environments, and test runtime imports, entry points and packaged resources
there. Pin the build frontend before freezing. The experiment workspace intentionally requires a source
checkout/editable installation; document that limit rather than marking wheel
experiment operation passed. Test the declared minimum Python 3.10 and the
shared primary version on supported platforms; unavailable environments block
their claims.

The checkout's `pytest.ini` injects `pythonpath = .`. Therefore a passing checkout
suite does not prove installed-package imports. Wheel/sdist probes must use an
unrelated cwd, no inherited PYTHONPATH, a controlled pytest configuration or
standalone probes, and recorded module `__file__` origins inside the intended
installation. Reject a probe that silently imports this source checkout.

### Phase 02 — collection, omission and coverage controls

Existing collection command (through the recorder):

```powershell
& $Py -m pytest --collect-only -q --strict-markers -W error::pytest.PytestUnhandledThreadExceptionWarning -W error::pytest.PytestUnraisableExceptionWarning bittorrent_lite/tests
```

The prepared ledger plugin must capture the complete node IDs. Collection must
exit zero and contain every historical node from
`end-to-end-validation-inventory.json`, plus all new mandatory cases. Require
explicit justified review for renames; a smaller count is a failure. Preserve
the empty `networking/test_handshake_connection.py` but mark it **EMPTY, NO
TEST COVERAGE**. Test files are not assumed to be pure unit tests by folder name.

Establish branch/function coverage collection for parent and child processes.
Confirm a child-only known function is recorded after a controlled child smoke;
otherwise coverage setup fails. Do not claim subprocess coverage from an ordinary
`coverage run -m pytest` alone. Exclude tests/generated files, never entire hard
production modules. Coverage itself does not replace assertions.

Freeze a reviewed partition of all collected nodes by actual execution behavior:
isolated unit/component, in-process/live-socket integration, synthetic harness,
real end-to-end, and acceptance extensions. Sets must be disjoint and their
union must equal the full collection. The runner rejects blank selector entries
and validates exact collected sets before bodies execute. Never reuse the old
537/200 selector files for this enlarged campaign.

### Phase 03 — all isolated unit and component contracts

Run the freshly partitioned unit/component set with `-x`, verbose node reporting,
strict markers, bounded per-test timeouts and JUnit output. Exercise all storage,
tracker state/validation, wire message validation, pure selection/request/policy,
common contracts, CLI validation, legacy and standalone implementations. Include
all boundary and invalid-input rows in §6, even if new tests are required.

**Exit oracle:** exact set completed; no skips/xfails; all positive/negative
assertions pass; no state mutation on invalid input; original implementations
retained and independently exercised.

### Phase 04 — integration, workers, real sockets and fault boundaries

Run the integration partition, including real HTTP tracker/client, socketpair
framing, network connections, scheduler/storage bridge, upload workers, runtime
admission and shutdown. Test all event-order permutations and queue/worker
failure paths in §6. Exercise both synchronous and two-worker uploads.

Reconcile first-write/response/verification/advertisement sequence using request
and connection identities. Require exact timeout, retry, cancellation, permission
and byte-accounting behavior. A thread warning, orphan, swallowed failure or
empty event stream fails the phase even if pytest printed passed.

### Phase 05 — preserved standalone CLIs, examples and alternate implementations

Run every module listed in §8 by its relevant behavior, not only import. The
request pipeline, recovery, upload service and choking-policy packages each
retain standalone APIs/CLIs; validate their response/state schemas and errors.
Run `examples.scheduler_demo` and its real dependency helpers. Exercise both
`storage.file_store` and the distinct `storage.transfer_store`; never swap them
silently. Exercise the legacy scheduler, picker, request manager and choking
manager separately from the production coordinator. Do not force both policies
into one live connection simply to make them appear used.

For JSON-lines CLIs, parse **every** response: an exit code zero may accompany
`{"ok": false}`. Normal cases require each operation's documented success schema;
some successful choking-policy responses have no `ok` field. Declared
invalid-input cases require the specified error and unchanged state. CLI syntax
is listed in Appendix C.

### Phase 06 — synthetic experiment-harness self-tests

Run the existing synthetic harness tests and extended negative cases for occupied
ports, never-ready children, unexpected exits, timeout, failed output hashes,
malformed/missing manifests and plotting/collector inputs. Check process cleanup
and retention of failed runs. All these artifacts carry `synthetic: true` or an
explicit synthetic label and live outside the real measurement corpus.

Successful synthetic copy operations are never evidence of P2P transfer.
Malformed-manifest unit fixtures must not be confused with genuine run manifests
by a recursive evidence scanner; require an explicit experiment manifest index.

### Phase 07 — real CLI end-to-end correctness and redistribution

Run the existing 33 real E2E cases, plus the missing cases in §6. Existing files:

```powershell
& $Py -m pytest -x -vv --strict-markers --timeout=30 -W error::pytest.PytestUnhandledThreadExceptionWarning -W error::pytest.PytestUnraisableExceptionWarning bittorrent_lite/tests/end_to_end
```

Use the recorder/guardian, unique basetemp, JUnit and fresh scenario roots.
The modules' explicit 120/180-second limits override the default where needed.
Do not infer a performance regression solely from these historical durations;
freeze justified deadlines before execution and never increase them mid-attempt.

Required proofs: correct distinct-piece bytes, exact hashes/sizes, one COMPLETE
after assembly, ongoing seeding, six downloaders with one/two seeders, actual
redistribution while original source is inaccessible, free-rider invariance,
real tracker recovery, reconnect with new connection IDs, and no process leaks.

### Phase 08 — extended real fault, timing, concurrency and storage campaign

Run all PREPARE fault cases: corrupt payload provider, wrong peer/swarm/version,
oversized/truncated/malformed frames, slow/trickling peer, mid-write failures,
queued and in-progress cancellation, delayed acknowledgements, queue pressure,
last-source loss, provider kill/replacement, and storage/final-assembly faults.
Use deterministic isolated injection instead of modifying global machine/network
settings or filling the real disk. Observe a healthy peer continuing when one
connection fails. Check error classification and invariants, not only exit codes.

Run repeated concurrent churn and shutdown with occupied queues/workers. Freeze
stress duration/limits in Phase 00. The added acceptance stress grid is the full
cross-product of seeders `{1,2}`, downloaders `{6,8}`, upload workers `{0,2}` and
windows `{1,4}`: **16 configurations, at least 30 minutes and 100 planned
connect/disconnect cycles each**. Exercise intermediate windows `{2,3}` in
SC03 boundary tests. This is separate from the original 27 measured runs and
adds at least eight hours of stress execution. Resource use must settle
after each cycle and return to baseline after shutdown; a permitted bounded
cache must be documented, not mistaken for an unbounded leak. Retain samples.

### Phase 09 — another laptop, OS and path portability

On at least two separately owned test laptops, create independent fresh Python
environments from the frozen dependencies and the exact frozen source bundle.
Transfer only metadata to downloaders. Use reachable IPv4 addresses, explicit
ports and `--host 0.0.0.0`; record the chosen interfaces and source-IP behavior.
Confirm actual reachability rather than assuming localhost results generalize.

Repeat small/boundary/64 MiB transfers, redistribution, six-downloader topology
distributed over machines, two seeders, tracker interruption and graceful stop.
Verify each remote output locally and include host identity in every event.
Use wall-clock UTC only with recorded clock synchronization/uncertainty; never
subtract `time.monotonic()` readings across machines. Use a central observer's
timing origin or per-host durations. Keep LAN results separate from localhost.

Test paths with spaces, Unicode names, relative/absolute CLI arguments, a moved
checkout, unrelated cwd, and a fresh output root. Review the current metadata
filename restrictions and platform-reserved names. Run on Windows plus a
supported Linux/macOS environment for platform claims; a missing device or
permission is BLOCKED, not a passed portability case. Do not change firewalls
or machine-wide policies without explicit authorization.

### Phase 10 — pilots and all original measured experiment comparisons

Use a distinct-piece 32 MiB pilot fixture, then the same immutable 64 MiB
fixture for the primary controlled comparisons unless a documented original-plan
decision specifies otherwise. Keep file hash, code/environment, piece size,
startup method, upload policy and network constraints fixed across comparisons.
Pilot behavior is not substituted for measured results.

Freeze one original-guide timing method: (a) a proven common release barrier
after readiness, or (b) the launch-sequence fallback whose distribution origin
is **the first peer launch**, with identical recorded launch order/delays and
startup overhead included. Do not label a sleep as a barrier. The existing
launcher currently timestamps `run_start_mono` **before the tracker starts**,
which differs from that fallback. Preserve its raw timestamps and prepare a
reviewed derivation from actual peer launches for the original comparison, or
record an explicitly reviewed timing deviation before freeze. Keep launcher
duration (including setup/cleanup), distribution time and per-peer completion
separate; never mix origins across runs or silently relabel an existing column.

Required original minimum: **nine distinct configurations × three independent
repetitions = 27 measured runs**, with the L=6/S=1/rarest/window=4/cooperative
baseline shared only when all fixed settings are identical:

| Configuration | Downloaders L | Seeders S | Selection | Other condition |
|---|---:|---:|---|---|
| swarm-L2 | 2 | 1 | rarest-first | baseline policy |
| swarm-L4 | 4 | 1 | rarest-first | baseline policy |
| swarm-L6 | 6 | 1 | rarest-first | shared baseline |
| swarm-L8 | 8 | 1 | rarest-first | baseline policy |
| select-random | 6 | 1 | random | same fixed settings |
| select-sequential | 6 | 1 | sequential | same fixed settings |
| seeders-S2 | 6 | 2 | rarest-first | both sources independently validated |
| free-rider | 6 | 1 | rarest-first | designated downloader uploads zero |
| failure | 6 | 1 | rarest-first | kill designated downloader at ≥25% verified progress |

Record shuffled run order, order seed and three run seeds before execution.
Use comparable seed/startup schedules for strategy comparisons without claiming
identical thread interleavings. Fresh tracker, stores, outputs and logs per run.
Preserve all failures; any unexpected failure invokes §1.2 and restarts the
**entire campaign**, including all 27 measurements, on the repaired revision.

**Important existing-tool trap:** `matrix.main()` currently continues after
failed runs and returns zero. Use it only with `--dry-run` to inspect the schedule.
Execute the 27 configs one at a time through a reviewed supervisor calling the
existing launcher/Run API and immediately checking manifest status, expected
completion set, independent hashes, actual exits and cleanup. Do not run the
current matrix command unattended and interpret exit zero as 27 passes.

```powershell
& $Py -m bittorrent_lite.experiments.scripts.matrix bittorrent_lite/experiments/configs/base.json --repeats 3 --order-seed 2026 --dry-run
```

The current launcher alone is insufficient evidence: validate its output flags
and child exit codes independently even when `status` is `ok`. For the failure
scenario, confirm the target was alive and the trigger actually occurred before
completion; only the predeclared surviving downloaders are expected to finish.
`not_executed`, timeout, missing trigger or a false hash is not PASS.

### Phase 11 — measurements, CSVs, graphs and numerical audit

Parse every indexed manifest and each **dedicated structured event stream**
independently before collection; reject missing, invalid, duplicate or
mixed-revision entries. Retain raw stdout/stderr as opaque bytes: existing E2E
support names mixed console output `*.jsonl`, but a filename does not make it a
strict event stream. PREPARE distinct `BTL_EVENT_LOG`/`BTL_PROC_ID` values for
every E2E/CLI child, with the artifact registry declaring stream type/schema.
Do not inherit one shared event path across children.

The collector can omit unreadable runs and event readers can skip malformed
lines, so exit zero or an empty CSV is not acceptance. Validate every completed
event record, required fields, order, identity and mandatory event counts; report
invalid records by file and line. For a **predeclared deliberately killed** child
only, at most one incomplete trailing record may be classified as interrupted
by termination: preserve its exact bytes, never parse/count it as an event,
and corroborate the kill with the independent supervisor. Any required metric
lost with that record/final counters must come from a separately validated
observer or remain BLOCKED. Earlier malformed records, unexplained truncation
or a truncated gracefully stopped stream fail. Never synthesize missing events
or silently discard lines. Require all 27 run IDs and the
correct number of peer rows, including killed/failed cases. Keep failed earlier
attempts in a separate failure corpus, not silently excluded from the history.

Recompute independently:

- Per-peer completion = verified assembly completion minus the declared start
  origin. State whether process launch is included; keep it identical between runs.
- Distribution time = last expected verified completion minus common run start.
- Useful aggregate throughput = expected successfully distributed source bytes
  divided by distribution time, using the original scenario definition. Do not
  apply the normal all-peer formula to a killed-target run without declaring it.
- Verified bytes count new accepted pieces once, excluding duplicates/corruption
  and already-owned resume data. Uploaded bytes count complete PIECE payload
  writes, excluding headers and unacknowledged/partial writes.
- Requests/retries/hash failures/messages/queue maxima derive from instrumented
  events with exact definitions; unknown values remain undefined and block a
  required metric. Do not fabricate zeros to make plots render.
- Reconstruct availability from genuine piece-verification events and peer
  lifetimes. Distinguish missing telemetry from zero ownership.

Generate all required plots from the frozen raw CSVs/scripts. Verify axes,
seconds/MiB/MiB per second, populations, repetitions, spread/error bars, baseline
reuse and captions. Open every image and inspect legibility and labels. Missing
groups, misleading zero values or stale output images fail. Report medians/means
and variation according to the frozen method; retain outliers and explain them.
Do not claim rarest-first must outperform alternatives on localhost.

### Phase 12 — complete regression, coverage closure and final original-plan comparison

After all preceding scenarios pass on the same frozen source, run the entire
collected suite again, with no filters/deselections and a fresh output directory:

```powershell
$FullTemp = Join-Path $AttemptRoot 'temp\full-regression'
if (Test-Path -LiteralPath $FullTemp) { throw 'pytest basetemp must be fresh' }
$FullXml = Join-Path $AttemptRoot 'junit\full-regression.xml'
if (Test-Path -LiteralPath $FullXml) { throw 'Do not overwrite JUnit evidence' }
$TestArgs = @('-m','pytest','-x','-vv','--strict-markers','--timeout=30',
              '-W','error::pytest.PytestUnhandledThreadExceptionWarning',
              '-W','error::pytest.PytestUnraisableExceptionWarning',
              'bittorrent_lite/tests',('--basetemp=' + $FullTemp),('--junitxml=' + $FullXml))
& $Py @TestArgs
if ($LASTEXITCODE -ne 0) { throw 'Full campaign FAILED; follow complete-restart rule' }
```

Run the above through the recorder rather than relying on the terminal buffer.
Use the frozen coverage/ledger plugins as configured in preparation. Every
collected node must have an actual successful setup/call/teardown outcome and
no test may be omitted. A pytest exit without its required XML or truncated
recorder capture is failure. The narrowly predeclared deliberately killed
child's interrupted final event record remains governed by Phase 11; it is not
a blanket exemption for truncated pytest output or missing evidence.

Combine coverage only from this attempt. Account for every production file,
function/method and reachable decision/error path. Exercise missing paths with
meaningful assertions; adding such tests requires a new freeze/full restart.
Any unreachable/platform-specific branch needs a reviewed reason and relevant
platform evidence, not a blanket `pragma: no cover`. Empty/export-only modules
get import/identity checks; do not invent a function-coverage percentage for them.
There is no aggregate percentage that excuses an untested core module. Publish
actual line/branch/function counts and every remaining gap. If a mandatory
reachable path is untested, complete acceptance remains BLOCKED.

Complete the per-requirement original-plan matrix in §7, plus implementation
differences, ownership, reports, AI disclosure, demonstration and viva evidence.
Every claim must link to this attempt's raw artifacts and exact tests.

### Phase 13 — cleanup, sealing and independent verification

Check every registered child has exited; no campaign listeners, queues, upload
jobs or worker threads remain. Preserve stdout/stderr, source fixtures, partial
downloads, completed outputs, fault triggers and metrics. Do not remove failed
attempts or wipe `.validation/`. Confirm source/test/config hashes unchanged.
Seal the final artifact index and deliver it to the independent reviewer under
§2.5. Produce the final comparison report only from verified data. A failed
review/verifier check is a campaign fault and follows §1.2.

## 6. Detailed acceptance scenario catalogue

For each row, the executor must record test/procedure ID, positive/negative
oracle, artifact paths and status. Enumerated subcases are separate ledger rows,
not one checkbox hiding an unrun combination. Existing tests may satisfy a row
only when their assertions actually cover it. All additional rows are PREPARE
until linked to a reviewed executable test or operator procedure.

### 6.1 Storage, metadata and integrity — Rishikesh

| ID | Required cases | Expected result/evidence |
|---|---|---|
| ST01 | 0, 1, 65,535, 65,536, 65,537 bytes; 2 pieces; short final; 32 MiB; 64 MiB; 64 MiB+1 | Zero/oversize rejected as contracted; exact boundary count and length; no padding |
| ST02 | Unique-piece binary, all-zero, non-UTF-8, randomized and Unicode filename inputs | Independent bytes/size/hash match; hashes cannot hide wrong ordering |
| ST03 | Missing/extra metadata fields, wrong types, booleans in integer fields, negative/float counts, inconsistent piece count/length, invalid SHA-256, version mismatch; metadata length below/at/above 256 KiB | Deterministic rejection before unsafe I/O or advertisement; exact contract for extra fields and the original metadata size cap recorded |
| ST04 | Exact metadata bytes vs whitespace/reordered/reformatted JSON | Same bytes produce same file ID; byte changes change file ID; no reserialization shortcut |
| ST05 | First/middle/last/index -1/out-of-range/bool/noninteger reads and writes | Exact bytes or explicit error; no unrelated file mutation |
| ST06 | Corrupted/truncated/oversized piece, wrong index, wrong request identity, duplicate valid piece | Never advertise corrupt/unmatched data; duplicate does not inflate verified bytes |
| ST07 | Fresh seeder and second seeder with correct, wrong, modified, missing and truncated source | Source validated before full bitfield; invalid source never becomes a valid source |
| ST08 | Missing/corrupt/replaced stored piece before read/upload/assembly; corrupt resume cache | Revalidate appropriately; no corrupted upload/HAVE/COMPLETE; recover valid pieces |
| ST09 | Read/write/rename/permission failure and simulated disk-full; failed final assembly; concurrent cancellation | Local storage error distinct from remote corruption; no false COMPLETE or repeated uncontrolled writes |
| ST10 | Output filename traversal/absolute/drive/UNC/reserved-name paths; source collision; piece-path collision | Safe rejection or explicitly documented platform handling; no write outside owned output root |
| ST11 | Concurrent worker reads, atomic piece replace, assembly with missing piece; private per-peer directories | No half-written shared piece, cross-peer contamination or accidental overwrite |
| ST12 | Real FileStore and alternate transfer_store APIs; metadata CLI and console entry point | Both implementations exercised against their own contracts; current paths work from external cwd |
| ST13 | At least 12 distinct pieces with misleading lexicographic filenames (for example indices 1, 2, 10, 11) | Assemble by numeric metadata index, never directory iteration or lexicographic filename order; independent byte-for-byte comparison |

### 6.2 Tracker, HTTP and discovery — Debargha

| ID | Required cases | Expected result/evidence |
|---|---|---|
| TR01 | started/update/completed/stopped; repeated event; self exclusion; multiple swarms; duplicate ID with changed endpoint | Correct membership only; exact behavior documented; no bitfields or file bytes in tracker |
| TR02 | Expiry just before, exactly at and after 20 seconds; refresh at boundary; stopped then restarted | Fake-clock exact oracle plus live observation; monotonic time; original boundary comparison |
| TR03 | Invalid IDs/IPv4/port/type/body, malformed JSON, body below/at/above 4 KiB, response below/at/above 64 KiB, wrong method/path/content length, transfer encoding | Correct HTTP/error category; no invalid membership mutation; healthy later requests work |
| TR04 | Source IP spoof in JSON; requester IP; stale endpoints; duplicate/self peers in response | Source connection IP used; response validation/filtering correct; stale candidate not considered guaranteed reachable |
| TR05 | Tracker absent, unreachable, slow, stalled body, reset, invalid JSON/oversized response, non-200 | Bounded waits and specific errors; no scheduler blocking or thread crash |
| TR06 | Retry delays 2/4/10 capped, success reset, announce interval clamp; completed and stopped while retry pending | Timings and event ordering correct; worker wakes/stops promptly |
| TR07 | Existing transfer during tracker loss; restart repopulates membership; late arrival after restart | TCP transfer continues; real discovery recovers without resetting verified data |
| TR08 | Queue full, dropped discovery snapshot, repeated updates, shutdown in HTTP, stop timeout | Bounded queues; fresh snapshot retried; no deadlock or orphan; best-effort stopped visible |

### 6.3 Protocol, connection and transport — Anik

| ID | Required cases | Expected result/evidence |
|---|---|---|
| NW01 | Every message type: HANDSHAKE, BITFIELD, HAVE, INTERESTED, NOT_INTERESTED, CHOKE, UNCHOKE, REQUEST, PIECE, CANCEL, REJECT | Encode/decode fields, header length, payload length and content; valid ordered exchange |
| NW02 | Every byte boundary in 4-byte prefix; split UTF-8/header/payload; multiple frames coalesced; socket poll between fragments | Exactly the original ordered frames, no lost bytes or interleaved writes |
| NW03 | Zero/over-16-KiB header; negative/bool/string/oversized payload; unknown message; missing required fields; extra fields per contract | Reject before unsafe allocation; affected connection closes; receiver remains healthy |
| NW04 | Invalid version/file ID/peer ID/self/expected candidate ID; duplicate handshake; ordinary message before handshake | No admitted session or requests; rejection releases socket/workers |
| NW05 | Initial bitfield length/types/bool-int rules, HAVE range; missing initial BITFIELD after handshake until admission deadline; non-BITFIELD first message; repeated BITFIELD after admission | Exactly one valid initial BITFIELD is required; no silent normalization masking invalid input; exact metadata count; bounded session deadline |
| NW06 | EOF before frame/mid-prefix/mid-header/mid-payload; reset, partial write, idle and trickle timeouts | Correct clean close/error; incomplete frame never replayed on same stream; no bogus full-write ack |
| NW07 | Many senders, writer backpressure, full queue, slow receiver; queued cancellation and cancellation after writer starts | One writer preserves byte order; bounded queue; identity withdrawal only before start; started frame finishes or connection closes |
| NW08 | Response before sent event, delayed/duplicate ack, send failure, callbacks after close, queued messages on shutdown | Correct original-message ack identity; no request resurrection/double counting; owner-thread state only |
| NW09 | Lower-ID initiation; simultaneous connect attempts; duplicate sessions; reconnect same peer/new connection ID | At most one active session per identity; monotonic local connection IDs; stale events harmless |
| NW10 | Ten-connection cap, eleventh attempt, exhausted pending slots, closed-worker reaping | Bounded resource use and clean rejection; no starvation or unbounded retired connection list |
| NW11 | Continuous upload+download, both legacy and runtime connection paths, piece handler and transfer store | Full duplex correct; standalone behavior retained; production scheduler remains sole policy owner |
| NW12 | Request IDs 1, 2^63−1, 0, −1, bool and 2^63; increasing IDs with gaps; identical/conflicting pending duplicates; retired-ID reuse; opposite-direction namespaces; repeated retired CANCEL | Valid boundary identities and harmless repeats handled exactly; conflicting/invalid reuse rejected; one direction cannot corrupt the other or a replacement request |

### 6.4 Scheduling, recovery, uploads and policy — Prabhat

| ID | Required cases | Expected result/evidence |
|---|---|---|
| SC01 | MISSING→REQUESTED→VERIFYING→HAVE; zero/partial/full local state; invalid transitions | Only verified persistent data becomes HAVE; owner-thread mutation enforced |
| SC02 | Sequential/random/rarest-first; unavailable/owned/reserved exclusions; equal rarity and fixed seed; disconnected/choked provider | Independent reference model agrees; rarity uses active neighbor knowledge only |
| SC03 | Two providers/one missing piece; concurrency/reordered events; all windows 1/2/3/4 | One reservation per piece; per-connection bound includes queued/transmitted/verifying work |
| SC04 | Interest/NOT_INTERESTED transitions; control enqueue failure; request enqueue failure | No requests before accepted interest/permission; failed enqueue releases reservation |
| SC05 | Queue deadline 5 s; response deadline 10 s after actual full write; boundary ±epsilon | Independent fake clock; no response clock at enqueue; late ack does not recreate expired request |
| SC06 | Reject, choke, timeout, disconnect, corruption, cancellation, failed write; new provider available | Exact reservation cleanup and bounded cooldown; new request identity; no same-stream frame replay |
| SC07 | Stale/duplicate/wrong-connection/wrong-request/wrong-piece response before/after retry | Current request remains intact; no double verification/byte count/HAVE |
| SC08 | Persistent disk/assembly error vs bad remote bytes; explicit resume after local repair | Correct local pause/error; no blame/retry storm against healthy provider |
| SC09 | No remaining provider, newly available HAVE, reconnect, last source removed | Honest STALLED; timer progresses; later recovery; never invented COMPLETE |
| SC10 | Queue/read/upload-job caps; cancel before read/during read/before writer/during frame; output pressure | Bound all active+queued work; cancellation before writer start prevents payload release; an already-started frame finishes or the connection closes |
| SC11 | Two upload slots, ≥3 interested peers, five-second interval, positive contribution, zero scores, new arrivals | At most two acknowledged permissions; score interval resets; regular+optimistic choice follows original policy |
| SC12 | Seeder rotation, completed downloader, free rider before/after COMPLETE, delayed/rejected permission ack | No overgrant, stable rotation/opportunity, free rider always uploads zero |
| SC13 | Upload success/failure/partial write/retransmission/corruption | Count only complete acknowledged payload; prevent double count; useful download count separate |
| SC14 | All legacy picker/request/choking/scheduler classes, request_pipeline/recovery/upload_service/choking_policy APIs and CLIs | Independent contracts exercised; no deleted implementation or unused package disguised by import-only coverage |

### 6.5 Application, whole system, portability and operational faults

| ID | Required cases | Expected result/evidence |
|---|---|---|
| SY01 | Metadata→listen→announce→connect→handshake→bitfield→interest→unchoke→request→piece→verify/store→HAVE→assembly→COMPLETE→seed→stop | Correlated actual event chain and independently verified bytes; no stage inferred from another |
| SY02 | Source-isolated redistribution before whole-file completion AND from completed downloader | A verified piece is shareable immediately; B receives from A; tracker/supervisor never supplies contents |
| SY03 | S=1/L=6, S=2/L=6, L=8; early/late joins; simultaneous uploader/downloader | All expected outputs correct; bounded windows/queues/slots; no hidden serial-download substitute |
| SY04 | Kill downloader/provider while work in flight; retained seeder vs no source; reconnect/restart | Survivors complete when possible; unavailable piece stalls; correct new-session identity and resume accounting |
| SY05 | Tracker restart/slow or absent tracker; bogus endpoint mixed with valid ones | Real transfers stay responsive; bad candidate cannot suppress healthy discovery/transfer |
| SY06 | Corrupt provider mixed with honest provider; repeated corrupt piece; malformed socket alongside healthy session | No corrupt data advertised; accurate hash-failure accounting; recovery not false success |
| SY07 | Storage failure while receiving and during assembly; stop during disk read/write/frame/HTTP/queue saturation | No false completion, bounded cleanup, accurate nonzero/error status when cleanup cannot finish |
| SY08 | Normal Ctrl+C/SIGTERM/stop-file, startup bind failure, backend start exception, repeated shutdown, forced target kill | Graceful peers clean up; forced faults labelled; no killing unrelated process or abandoned child |
| SY09 | Current output root plus spaces/Unicode/moved checkout/external cwd/read-only location, source collision and same filename in different swarms | Correct dynamic path resolution, isolation and explicit errors; no machine-specific source paths |
| SY10 | Two laptops and another supported OS; correct LAN interface and metadata; clock offsets | Independently verified remote files and timing; no localhost-only claim generalized to LAN |
| SY11 | 30-minute stress, 100 churn cycles, repeated shutdown/restart, max piece count, slower links and latency | No unbounded threads/sockets/RAM/disk jobs; resources return to reviewed baseline; test deadline observed |
| SY12 | Package wheel/editable, both CLI entry paths, every export and standalone example; default configs | Correct installed import origins; no dependency on archived sources or test-only sys.path hacks |
| SY13 | Two concurrent swarms with different file IDs, same filename and overlapping peer identities; cross-swarm handshake attempt | Tracker membership and socket admission remain isolated; no wrong-source upload, output-path collision or byte leakage |

### 6.6 Metrics, logs, artifacts, documentation and original deliverables

| ID | Required cases | Expected result/evidence |
|---|---|---|
| EV01 | Every expected case/child/run present; empty/truncated/duplicate/skipped evidence negative controls | Verifier rejects incomplete inventory; no fabricated pass counts |
| EV02 | Logging disabled/enabled, invalid log path, concurrent writes, partial final JSON line, changed destination | Appropriate bounded/nonfatal logging behavior; missing mandatory experiment evidence fails campaign |
| EV03 | 27 real matrix runs; failed-run corpus; fixed revision/config/seed/fixture; unstarted/timeout/no-trigger | Complete classified manifests and expected survivors; no silent omissions |
| EV04 | Independent byte/message/request/retry/hash-failure formulas, partial-write caveat, resume/dedup | Exact definitions and correct counters; unknown not zero; no useful/wire-byte conflation |
| EV05 | Collector malformed/absent inputs, grouping/joins, availability reconstruction and baseline reuse | Correct rows or explicit failure; no empty-success or dropping bad runs without accounting |
| EV06 | All five comparison families, uncertainty and repetitions, units, failure/free-rider interpretations | Graphs reproducible from preserved CSV; no unsupported hypothesis or outlier removal |
| EV07 | README, architecture, protocol, paths, config, ownership, contribution, AI-USE, dependencies; trusted-metadata and trusted-lab limitations | Instructions match frozen code; SHA-256 is not sender authentication; tracker identities are unauthenticated; 0.0.0.0 is a bind address, not a peer destination; authorship/assistance recorded honestly |
| EV08 | All-member viva trace and demo; limitations; source-only clean install and final report | Required human demonstrations witnessed, not generated by Astra as fictional attendance |
| EV09 | Independent challenge rerun and artifact audit, external phase seals | Fresh reproducible evidence; verifier identity/results recorded; no self-attestation substituted |
| EV10 | About-once-per-second terminal status during active transfer: verified/total pieces, connected peers, pending requests, uploaded/downloaded bytes, current state | Fields agree with independently observed state and payload counters; output cadence does not block networking; absent original fields remain a documented gap |

### 6.7 Narrative contract checks beyond the named original tests

These rows make requirements from the original prose explicit. `G`, `R`, `D`,
`A`, `P` refer to the unchanged originals in §3; line numbers are those verified
in the Appendix D snapshot. Each NC row needs its own procedure/subcase evidence,
even when it shares an existing pytest test with another catalogue row.

| ID / original reference | Required procedure and oracle | Related cases |
|---|---|---|
| NC01 — G:863–865; A:116–122; P:68 | Assert both initial interest flags false and both choke flags true. Acceptor queues HANDSHAKE before BITFIELD; no INTERESTED/REQUEST until local BITFIELD queued and remote BITFIELD validated. Acquire a piece during snapshot/admission and prove subsequent HAVE follows BITFIELD and remote ownership catches up. | NW04–NW05, NW08 |
| NC02 — P:135 | Keep INTERESTED when a remote owns a still-missing piece reserved on another connection. Reservation changes alone must not generate incorrect NOT_INTERESTED. Recompute after local HAVE/remote inventory changes; emit controls only on actual transitions. | SC04 |
| NC03 — G:431; P:115–117 | Use bitfields where excluding a choked advertiser changes the rarest result. Count every distinct active advertiser, including choked neighbors, but choose only a source permitted by choke/window/cooldown. Share eligibility/source rules across all three strategies. | SC02 |
| NC04 — R:216–219 | Pre-create an unrelated destination with sentinel bytes. Inject assembly write/hash/replace failures: sentinel survives, no partial final file or COMPLETE, temporary file cleanup checked. Successful publication occurs only after exact size/hash verification under a frozen explicit overwrite policy. | ST09, ST11, ST13 |
| NC05 — A:162; G:310–312 | Construct literal expected control and PIECE bytes independently of project encoders. Include non-ASCII header text to distinguish UTF-8 byte count from character count. Check encoder→golden bytes and independent bytes→decoder separately; round trips alone are insufficient. | NW01–NW03 |
| NC06 — G:567; D:176–182 | Observe a real readiness/release barrier or the first-peer-launch fallback. Verify exact order/delays, peer launch/release/completion timestamps and one consistent distribution origin; test the current pre-tracker origin difference and derived columns explicitly. | EV03–EV06, Phase10 |
| NC07 — G:463–467; P:184–195,267 | Test 0,1,2,3+ interested neighbors; serve available candidates below two and fill vacancies when membership/interest changes. Send CHOKE/UNCHOKE only for permission changes. Reset contribution per interval; count newly verified bytes, excluding duplicates/corruption. | SC11–SC13 |
| NC08 — D:64,70 | Test missing/wrong Content-Type, invalid UTF-8 and correct/incorrect/bounded response Content-Length. Freeze and assert the implementation's reviewed HTTP error contract; do not treat every proposed status code as simultaneously required. Membership must remain unchanged on invalid input. | TR03–TR05 |
| NC09 — D:92–102; G:493 | Prove no started announce before successful listener bind, no completed announce before final verified assembly, and best-effort stopped after shutdown request. Repeat transitions while retry is pending. Console errors are rate-limited while structured failure evidence remains complete. | TR06–TR08, SY01, EV02 |
| NC10 — G:162; R:156–157,183–184 | Instrument source processing to prove bounded chunks and piece reads, avoiding unnecessary whole-source loading. Enforce the metadata byte cap before parsing; a valid bounded JSON metadata document may be loaded in full. Concurrent source reads cannot share an unsynchronized seek position. Mid-run truncation/unreadability is a local storage error, with no false availability or completion. | ST07–ST11 |
| NC11 — A:126 | Verify one consistent timeout policy on a reader/writer-shared socket: no per-thread settimeout race. Combine idle receive polling with concurrent send and partial-send failure; no false idle disconnect or same-stream frame replay. | NW06–NW07 |
| NC12 — G:881,887; P:167–169 | Deliver a late REJECT after a replacement request: replacement survives. Repeated corrupt responses cause bounded source cooldown/avoidance or connection closure, and a healthy provider gets an opportunity. Do not blacklist the entire swarm. | SC06–SC07, SY06 |

Existing anchors include
`tests/integration/test_peer_runtime.py::test_initial_bitfield_handoff_reconciles_only_newly_owned_pieces`
and `tests/integration/test_real_backend.py::test_early_events_wait_for_owner_admission`.
These paths are relative to `bittorrent_lite/`; collect from the actual repository
root before building selectors. A broad parent test is credit only for the
subclauses it actually asserts.

### 6.8 Parser, filesystem and preserved standalone contracts

The v1 network runtime and standalone member libraries have different scopes.
Do not apply a v1 limit to an unrelated standalone API and change preserved work
merely to make it conform. Record each implementation's own contract separately.

| ID | Scope and cases | Required oracle |
|---|---|---|
| SP01 | Metadata, HTTP, wire and standalone JSON loaders: root scalar/array, duplicate keys, bounded-size deep nesting, invalid UTF-8/BOM, nonfinite numbers, huge integers | Exercise each documented parser policy. Unsupported values produce controlled rejection, no invalid state, unsafe allocation or worker leak; record/resolve unspecified duplicate-key semantics before freeze rather than inventing a universal policy |
| SP02 | Metadata/source/output and DirectorySource paths: symlink/junction/hardlink aliases, outside-root resolutions, directory/nonregular piece paths, exact-length and length+1 reads | Use disposable owned paths and compare source bytes before/after. Assert existing samefile/symlink/outside-root protections, bounded reads and descriptor cleanup. Where a platform cannot create a path type, record that platform gap and cover the supported equivalent elsewhere |
| SP03 | Standalone request pipeline: every API/CLI operation, clock monotonicity, boundary window/timeouts, immutable snapshots, invalid calls, stale IDs | Assert the standalone documented limits and lifecycle. Invalid calls preserve state/time/RNG where guaranteed; snapshot mutation cannot change internal state; no reservation leaks |
| SP04 | Standalone recovery defaults: endgame enabled, max copies2, remaining threshold4, minimum age5s; penalty-provider256/entries4096/recent-events256 limits | Test below/at/above age, remaining, provider/copy/history bounds and eviction; seeded selection and invalid-call atomicity. Runtime separately uses endgame disabled/max copies1: no duplicate reservation there |
| SP05 | Standalone upload manifest: piece lengths1…4,194,304 bytes, count1…4096, JSON≤1,048,576 bytes; memory/directory sources; all job/output budgets | Test each exact boundary plus invalid neighbors, duplicate keys/indices, order, extra/missing fields, normalized digest case, cancellation/read/output byte limits and bounded shutdown. These are not the core v1 64KiB/1024-piece/256KiB-metadata limits |
| SP06 | Standalone choking policy: permission intent/ack, token reuse, reconnect, reset/shutdown epochs, failed acknowledgements, monotonic time | Old tokens cannot grant new-session permission; repeated acks are harmless/rejected per contract; permission accounting stays within its configured bound; invalid calls do not mutate accepted state |
| SP07 | Legacy scheduling, alternate transfer_store, exports/Protocols and examples | Preserve and assert each documented public API and alias identity, including alternate default policy behavior. A compatibility alias gets an identity test; a Protocol gets compatibility tests; executable behavior gets actual assertions, not import-only credit |

Useful existing starting points: `tests/scheduling/test_recovery_policy.py`,
`test_choking_policy.py`, `test_request_pipeline.py`,
`tests/networking/test_upload_service.py` and their integration counterparts.
Extend only where needed after inspecting actual assertions. Boundary-only tests
may use validated synthetic data; they do not become real-transfer evidence.

## 7. Original-plan comparison and decisions

Prepare a row for **every** normative bullet, interface, test ID, task deliverable
and final checklist item in G/R/D/A/P, including items not copied into this plan.
Use stable IDs such as `G-6-metadata-file-id` and the original named test IDs.
Record original document path/hash and section/line quote, current source symbol,
current behavior, required oracle, case IDs, actual node IDs, evidence links,
deviation rationale, reviewer and final status. Cite original text precisely;
do not compare only the section titles or claim one integration test covers all
subclauses. Historical dates/milestones cannot be retroactively marked met.

Required comparison dimensions include scope, file/layout organization, interface
contracts, default constants, error behavior, concurrency ownership, tests,
experiment methodology, raw data/plots/report, contributions and viva readiness.
Do not overwrite the original plans with the implementation to erase a mismatch.

### 7.1 Preidentified differences that MUST be resolved transparently

| Item | Original/reference | Current evidence at planning time | Required treatment |
|---|---|---|---|
| Folder structure | G's suggested `src/` tree | User-approved member packages inside `BitTorrent/bittorrent_lite/` | Document approved structural mapping; preserve responsibilities and original files |
| Crash resume | G excludes automatic crash-resume from planned scope | Verified-piece restart is shipped and tested | Label an extension; test its integrity/accounting without rewriting the original scope |
| HTTP timeout | G/D propose 3 seconds | Discovery default is 3 s; real backend explicitly uses 1 s | Compare behavior/latency; document reason and reviewed deviation, never silently claim exact conformance |
| Production piece size | G fixes 64 KiB for v1 | Metadata validator accepts any positive piece size; runtime wire payload is limited to 64 KiB | Exercise both boundaries; reject unsupported production metadata early or document an approved extension; helper fixtures do not silently redefine v1 |
| Metadata input bound | G §22 proposes 256 KiB before parsing | storage.metadata.load_metadata currently reads the entire metadata file before parsing and has no explicit input-byte cap | Add the boundary/oversize procedure, resolve the proposal and bounded-read expectation before acceptance; do not confuse this with standalone upload-manifest's separate 1 MiB cap |
| Neighbor limit | G proposes 12 | Real backend caps connections at 10 | Test actual cap and rejected eleventh connection; record proposal/current mismatch and review its effect on supported swarm sizes |
| Event/outgoing queue sizes | G proposes coordinator queue 128 and outgoing queue 32 | Live SchedulerBridge coordinator ingress remains 128; backend handoff and runtime control queues are separately 32; RuntimeConnection writer queue is 64 | Coordinator ingress matches; writer 64 versus 32 is a proposal deviation. Test each distinct queue by purpose, including added handoff/control limits |
| Session-state ownership | G §22.2/24 assigns semantic connection phase to coordinator | RuntimeConnection validates handshake/initial bitfield in reader dispatch before owner-thread admission; coordinator owns scheduling policy | Document the adapter split and synchronization; test early-event buffering/admission order and immutable handoff, without rewriting preserved code solely for architectural resemblance |
| Connection/handshake deadlines | G proposes connect 3 s and handshake 5 s | Real connector uses 0.5 s and admission deadline 10 s | Test proposed/current semantics and slow LAN behavior; record the reason and review, including component-specific timeout differences |
| Choking/picker alternatives | Original responsibilities overlap with later packages | Legacy and acknowledged modern implementations coexist | Exercise each separately; ensure default runtime uses one scheduler/policy |
| Instrumentation | Original counters include messages/requests/retries/hash failures | Real backend currently exposes verified/uploaded byte counters; other aggregates are not fully instrumented | PREPARE missing validated telemetry; incomplete measurement requirements stay BLOCKED |
| Real measurements | G/D require 27 measured runs and plots | Prior 33 E2E cases and three launcher scenarios are correctness evidence | Run the entire controlled matrix anew; do not relabel old tests as the experiment study |
| Measurement origin | G/D fallback starts distribution timing at first peer launch, or uses a real release barrier | Launcher run_start is before tracker startup; collector uses it for finish/distribution values | Prepare an explicit original-origin derivation or approve a documented deviation before freeze; preserve raw timestamps and distinguish total run duration from distribution |
| Portability/stress | Original local/LAN and bounded lifecycle claims | Prior acceptance was Windows localhost | Perform Phase 08–09; unavailable platforms/devices remain explicit gaps |
| Dependencies | G says avoid pandas/NumPy unless genuinely needed | Extras declare both; plot.py directly uses stdlib and matplotlib, which depends on NumPy; direct pandas use is not evident | Inspect and justify the optional dependency set and reproducible environment; preserve member tooling |
| Process/script exit codes | Requirement is honest failure reporting | Matrix may continue/return zero; collector/JSONL CLIs can hide semantic failures behind zero | Wrap with reviewed fail-closed checks; record behavior/deviation and test it |

### 7.2 Final comparison status

Use four separate judgments: **implementation conformance**, **test evidence**,
**original experimental deliverables**, and **human/demo deliverables**. A passed
code suite does not prove the report, 27-run study, contribution record or viva
was completed. Only requirements with fresh adequate evidence get PASS.

The original named tests and all-module ledger are expanded in the appendices
below. Reconcile them against the source documents at Phase 00 in case files
changed since this plan was prepared.

## 8. Every-module coverage ledger

Create one ledger row per production `.py` and each executable function/method,
plus config/CLI/export/doc resources. Include private methods and failure paths;
`__init__` files that only re-export symbols need identity/import tests. For every
row record whether it is the live backend path, a preserved alternative, test
support, an example or an entry point. Link behavior assertions, coverage and
original ownership; imported-but-never-executed code is not marked fully used.

No module may disappear merely because the runtime doesn't call it. The current
production groups and required evidence appear in the appendix. Discover the
actual file list again during execution, excluding generated caches and test
files only; any extra file must be classified. Missing methods/branches create
new cases and therefore a new freeze/full restart before acceptance.

## 9. Final evidence package and sign-off

Produce inside the final attempt, without modifying raw artifacts:

| Artifact | Mandatory contents |
|---|---|
| `CAMPAIGN-REPORT.md` | Scope, actual frozen revision/hashes, environment, exact fresh results, failures/restarts, all untested/blocked areas, honest conclusion |
| `requirements.csv` | Every G/R/D/A/P item and follow-up contract; source quote/section; current behavior; cases/evidence; pass/deviation/block status |
| `modules.csv` | Every file/function/branch and config/entrypoint; live vs legacy purpose; meaningful behavioral coverage and uncovered reasons |
| `cases.json` | Full planned/collected/executed node sets; manual cases; setup/call/teardown outcomes; no silent deselection |
| `commands/` and `logs/` | Real commands, PID/time/exit records, raw stdout/stderr; all preserved attempts and diagnostics |
| `junit/` and `coverage/` | Genuine XML and parent+child coverage raw files, combined reports, exclusions and verifier checks |
| `fixtures/` and `runs/` | Challenge provenance, independent expected hashes, configs, participant/event logs, source/partial/completed outputs, fault triggers |
| `results/` and `plots/` | All 27 indexed real-run manifests, peer rows, availability/summary CSVs, scripts and actual rendered graphs |
| `defects/` | Every unexpected failure, root cause, fix diff, regression, discarded attempt linkage and entire-restart proof |
| `seals/` | Source/environment and per-phase artifact hashes, external retained digests, final artifact index |
| `INDEPENDENT-REVIEW.md` | Reviewer identity/environment, selected fresh reruns, verifier negative controls, recomputed values, disagreements and final decision |

Global pass requires: every mandatory original/current case accounted for; all
tests completed without skips; no unresolved contract deviation; independently
verified real outputs; correct complete experiment corpus; coverage gaps closed
or explicitly reviewed platform limitations; no orphan processes; unchanged
source hashes; and independent verification. If any required hardware, tool,
telemetry or human evidence is absent, deliver a precise partial/blocked report
instead of saying "everything works".

## 10. Manual operator checklist and troubleshooting

Before each command: correct repository/interpreter; recorder ready; fresh
output/basetemp; ports checked; required fixture/config exists; expected exit and
deadline declared; stop-file path fresh; no previous campaign process owns the
same endpoint. Preserve source files and do not use recursive deletion for a
restart. Resolve any delete/move target inside the campaign root before acting.

When PowerShell invokes Python, use `& $Py` and an argument array; avoid nested
shell strings, backtick continuations and Bash syntax. Capture exit immediately.
Do not interpret a later `Get-Content`/`echo` success as the test result. Paths
passed to Python are separate arguments, not shell-quoted strings with literal
quote characters. Write JSON as explicit UTF-8 **without a BOM**. Existing
UTF-8 JSON readers do not uniformly accept a Windows PowerShell UTF-8 BOM.
Use `[System.IO.File]::WriteAllText($Path, $JsonText,
[System.Text.UTF8Encoding]::new($false))` for prepared inputs, with a resolved
fresh campaign-owned path. Treat BOM acceptance/rejection as a separate
declared negative/compatibility case; do not accidentally introduce it into
ordinary fixtures.

| Symptom | Stop-point inspection |
|---|---|
| Import failure | Actual interpreter, editable/wheel origin, cwd, PYTHONPATH, old archived source shadowing |
| WinError 10013 | Local socket permissions/sandbox policy; record environment fault, obtain appropriate permission, then full restart |
| Address already in use | Registered owner PID + creation time; choose predeclared free port or clean only owned process; never kill an unknown service |
| Handshake but no transfer | Valid BITFIELD → INTERESTED → UNCHOKE → REQUEST → full-write ack chain; inspect exact connection/request IDs |
| Repeated last-piece mismatch | Expected byte length, padding, index, independent metadata hashes; do not relax hashing |
| Invalid JSON after a delay | Fragment preservation, timeout boundary, single writer and payload length; retain offending bytes |
| Tracker outage stalls existing stream | Blocking HTTP on owner thread, discovery queue pressure, timer responsiveness |
| Passing exit but missing results | Exact manifest/JUnit/case/peer-row reconciliation; collector and matrix exit-zero traps |
| CLI JSON `ok:false` with exit zero | Semantic response error; normal-case failure even though process returned zero |
| Threads/processes remain | Guardian registry, close/join deadline, blocked I/O/provider; preserve stack/state and follow full-restart rule |
| Coverage reports only parent pytest | Child startup instrumentation/flush/data-file merge; do not claim application coverage |

Do not improvise unsupported flags. Read the actual `argparse` definitions before
running each CLI; the specific supported command forms are recorded in the
appendix. Recheck these if the source snapshot changes.

---

## Appendix A — Original named tests and delivery requirements

The five originals contain **27 master named tests, 65 individual named tests,
and six G0–G5 gates**. The mappings below specify intended coverage; no row is
currently PASS. At Phase 00 attach actual node IDs/manual procedures to every
row and expand combined subcases. These named tests do not replace the
requirement-by-requirement review of narrative/interface/final-checklist clauses.

### A.1 Master guide tests (27)

| Original ID | Required behavior | Catalogue |
|---|---|---|
| F01 | 65,537 bytes produces 65,536-byte and 1-byte pieces | ST01 |
| F02 | Changed piece byte gives hash error, no verified publication/HAVE | ST06, SC06 |
| F03 | Identical metadata bytes retain ID; reformatted JSON changes it | ST04 |
| F04 | Misleading piece filenames still assemble in numeric order | ST13 |
| T01 | Only live same-file peers, excluding self | TR01 |
| T02 | Expire at age ≥20 seconds | TR02 |
| T03 | Updates rebuild membership after tracker restart | TR07 |
| N01 | Arbitrary prefix/header/payload fragmentation reconstructs exactly | NW02 |
| N02 | Three coalesced frames yield three ordered messages | NW02 |
| N03 | Excessive header/payload rejected before unsafe allocation | NW03 |
| N04 | Wrong file/expected peer identity never becomes ACTIVE | NW04 |
| N05 | Partial send closes connection; no whole-frame replay on same stream | NW06 |
| S01 | Minimum positive eligible neighborhood rarity | SC02 |
| S02 | Two sources cannot create two reservations for one local piece | SC03 |
| S03 | At most four queued/transmitted requests per neighbor | SC03 |
| S04 | Old response cannot disturb replacement request | SC07 |
| S05 | Response-before-sent event accepted once; no resurrection | NW08, SC07 |
| C01 | Queued cancellation sends no canceled PIECE bytes; next frame valid | NW07, SC10 |
| C02 | Started frame finishes or connection closes; late receiver handling safe | NW07, SC10 |
| C03 | At most two upload permissions; rotating opportunities | SC11, SC12 |
| I01 | Two tracker-discovered processes exchange, verify, store actual TCP piece | SY01 |
| I02 | Downloader A supplies verified bytes to downloader B | SY02 |
| Y01 | S=1/L=6 and S=2/L=6 all required outputs match | SY03 |
| Y02 | Downloader killed in flight; surviving peers finish with retained seeder | SY04 |
| Y03 | Final missing-piece source removed: honest stall, no false completion | SC09, SY04 |
| Y04 | Established transfers continue when tracker stops | TR07, SY05 |
| Y05 | Free rider has zero completed uploaded payload; honest results | SC12, EV03–EV04 |

### A.2 Rishikesh tests (13)

| Original ID | Required behavior | Catalogue |
|---|---|---|
| R-T01 | 1, P−1, P, P+1, 2P: correct counts/last lengths | ST01 |
| R-T02 | Empty and >64 MiB rejected | ST01 |
| R-T03 | Invalid metadata fields/types rejected before use | ST03 |
| R-T04 | Copied exact metadata retains file ID | ST04 |
| R-T05 | Reformatting JSON changes byte-based ID | ST04 |
| R-T06 | Negative/out-of-range/boolean index rejected | ST05 |
| R-T07 | Valid received piece saved/read unchanged | ST06 |
| R-T08 | Hash/length mismatch never published as verified | ST06 |
| R-T09 | Partial temporary write failure gives no success/HAVE eligibility | ST09 |
| R-T10 | Missing stored piece makes assembly fail clearly | ST08, ST11 |
| R-T11 | More than ten pieces assemble numerically, including indices 9/10 | ST13 |
| R-T12 | Correct assembly has exact size/final SHA-256 | ST02, SY01 |
| R-T13 | Wrong seeder source cannot advertise complete ownership | ST07 |

### A.3 Debargha tests (12)

| Original ID | Required behavior | Catalogue |
|---|---|---|
| D-T01 | Same-file peers see each other, not self | TR01 |
| D-T02 | Refresh updates one record, not duplicates | TR01 |
| D-T03 | Two file IDs remain isolated | TR01, SY13 |
| D-T04 | Age19.9s live; age20s expired | TR02 |
| D-T05 | Repeated stopped removal harmless | TR01 |
| D-T06 | Invalid body/port/types do not mutate membership | TR03 |
| D-T07 | Slow/incomplete body bounded; server subsequently usable | TR03, TR05 |
| D-T08 | Tracker absence/restart: bounded retry and re-registration | TR06–TR07 |
| D-T09 | Stop during retry exits promptly | TR08 |
| D-T10 | Child crash preserves logs and cleans owned children | SY08, EV01 |
| D-T11 | Occupied port gives clear launch failure, no false readiness | SY08 |
| D-T12 | Failed analysis run counted, never silently omitted | EV03, EV05 |

### A.4 Anik tests (19)

| Original ID | Required behavior | Catalogue |
|---|---|---|
| A-T01 | Four-byte unsigned big-endian header prefix | NW01 |
| A-T02 | Fragmented prefix/header/body reconstructs one frame | NW02 |
| A-T03 | Three concatenated frames decoded in order | NW02 |
| A-T04 | Non-UTF-8 binary payload preserved exactly | NW01, ST02 |
| A-T05 | Zero/oversized header closes before unsafe allocation | NW03 |
| A-T06 | Negative/excessive payload rejected | NW03 |
| A-T07 | Boolean/noninteger index or ID rejected | NW03, NW12 |
| A-T08 | Wrong version/file/expected peer cannot reach ACTIVE | NW04 |
| A-T09 | Wrong-length/repeated BITFIELD fails per protocol | NW05 |
| A-T10 | Mid-prefix/header/body EOF gives controlled close, no partial event | NW06 |
| A-T11 | Idle polling timeout does not falsely fail connection | NW06 |
| A-T12 | Incomplete-frame deadline closes connection | NW06 |
| A-T13 | Multiple producers still use one intact writer stream | NW07 |
| A-T14 | Cancel before start skips upload/releases accounting | NW07, SC10 |
| A-T15 | Cancel after start finishes frame or closes connection | NW07, SC10 |
| A-T16 | Partial send closes; no same-stream replay | NW06 |
| A-T17 | Concurrent reader/writer failure cleans up once | NW08, SC06 |
| A-T18 | Old events cannot affect new connection | NW09, SC07 |
| A-T19 | Event saturation bounded; eventual coordinator cleanup | NW08, TR08 |

### A.5 Prabhat tests (21)

| Original ID | Required behavior | Catalogue |
|---|---|---|
| P-T01 | Correct positive rarity from known bitfields | SC02 |
| P-T02 | Owned/reserved/unavailable candidates excluded | SC02 |
| P-T03 | Choked rarest source causes eligible alternative selection | SC02 |
| P-T04 | Equal-rarity fixed seed gives repeatable isolated tie | SC02 |
| P-T05 | Two providers/one missing piece gives one request | SC03 |
| P-T06 | Pipeline four never permits five pending per neighbor | SC03 |
| P-T07 | Enqueue failure releases reservation | SC04 |
| P-T08 | PIECE before FRAME_SENT accepted once; late sent ignored | NW08, SC07 |
| P-T09 | Hash failure gives no HAVE and permits retry | SC06 |
| P-T10 | Storage failure is local error, no HAVE/provider blame | SC08 |
| P-T11 | Timeout/replacement/old response leaves replacement intact | SC07 |
| P-T12 | Duplicate HAVE does not inflate availability | SC02 |
| P-T13 | Reader/writer double close cleans once, no negative counts | SC06 |
| P-T14 | Stale old event leaves replacement connection unaffected | SC07 |
| P-T15 | Busy rejection avoids tight resend loop | SC06 |
| P-T16 | CHOKE stops new requests but sent responses remain valid | SC06 |
| P-T17 | Three interested peers: maximum two permissions and rotation | SC11 |
| P-T18 | Seeder/zero scores rotate fairly | SC12 |
| P-T19 | Completed free rider still has zero permissions | SC12 |
| P-T20 | Final assembly failure never emits COMPLETE | SC08, SY07 |
| P-T21 | No source gives stall/wait and periodic rediscovery | SC09 |

### A.6 Six original gates

| Gate | Required evidence | Plan coverage |
|---|---|---|
| G0 contracts | Shared metadata fixture, peer record, sample frame and event understood by all | Phase00; EV07–EV08 |
| G1 one piece | Two OS processes, real sockets, stored piece and matching SHA-256 | Phase04/07; SY01 |
| G2 small swarm | Full verified file, downloader upload, rarity test | Phase03/07; SC02, SY01–SY02 |
| G3 resilient swarm | Six downloaders, two-seeder variant, pipeline, failure/corruption recovery | Phases07–08; SY03–SY06 |
| G4 final features | Upload policy, free rider, all required behaviors, experiment pilot | Phases03–10; SC11–SC12, EV03 |
| G5 release | Fresh setup, reproducible tests, honest report, every member explains/modifies code | Phases09/12–13; SY12, EV07–EV09 |

### A.7 Original task and deliverable ledger

Each task within a grouped range needs its own final evidence row; do not reduce
an owner's tasks to one completion checkbox.

| Original tasks | Required artifacts/evidence |
|---|---|
| R01–R03 | Independently calculated boundary fixtures/table; metadata generator; serialization example while hashing actual saved bytes; strict validator and readable field errors |
| R04–R05 | Source validation/read API; immutable exact piece bytes; temporary write/publication behavior; separate corruption and local-I/O errors |
| R06–R08 | Real one-piece handoff and corrupt-data negative control; numeric assembly; downloader redistribution; six private output directories; second-seeder validation |
| R09 | Per-run/per-peer independent source/output hashes, expected/actual sizes, honest killed/failed classifications |
| R10 | Owner-reviewed report, consistent terminology/units, dataset-backed graphs, contribution/AI-use records, live boundary-change rehearsal |
| D01–D03 | Announce/response/stopped/error examples; membership tests; HTTP parsing/validation/timeout/error tests |
| D04–D05 | Usable real discovery endpoint; bounded worker; absent/restarted tracker evidence and responsive peer/shutdown |
| D06–D07 | Launcher, actual readiness, unique IDs/ports/storage, owned-child registry/cleanup, six-downloader/two-seeder manifests |
| D08 | Actual ≥25%-progress target kill record; retained seeder; trigger-unreached failure; zero free-rider uploaded payload |
| D09 | Pilot every experiment family; fixed timing/counter definitions; any shaping shared across a peer and consistently applied |
| D10 | Nine configurations ×≥3 repeats; raw observations/failures, verified outputs, reproducible labeled graphs with variation |
| D11 | Tracker/method/measurement/results sections; clean-start rehearsal; outage and limitations explanation |
| A01–A03 | Wire specification, control/data examples, independent codec fixtures, fragmentation/coalescing/binary/bounds tests |
| A04–A06 | Real tracker-discovered handshake/BITFIELD; actual stored piece; complete file; reciprocal and downloader-to-downloader transfer |
| A07–A09 | Single-writer concurrency, caps/queues, duplicate sessions, cancellation/write boundary, failures/reconnect/cleanup |
| A10–A11 | Choke/unchoke/reject ordering; full-write-only message/payload counters; protocol and transport report sections |
| A12 | Fresh handshake demonstration, byte-by-byte frame explanation, fragmented-read/mid-transfer failure, live validation-limit change |
| P01–P03 | State records/directional flags/single ownership; fake clock/RNG/store/transport tests; reserve-before-enqueue lifecycle |
| P04–P05 | Entry-point integration; one real piece; verified complete file, continued seeding and actual redistribution |
| P06–P07 | Shared eligibility/source rules for three strategies; seeded rarity; no inflated HAVE counts; window4 and scale evidence |
| P08–P09 | Deadline/reject/disconnect/stale-event/reconciliation; no-source stall; slot fairness and completed free rider |
| P10–P12 | Cleanup-path invariant review; final gate; log-grounded experiment interpretation; state/policy report; live strategy/window change |

### A.8 Numeric and structural original contracts

These are original values/proposals, not assertions that all current code
matches. Link mismatches to §7 and the frozen source; proposals may be reviewed
deviations but must not disappear from the comparison.

| Contract | Original value / rule |
|---|---|
| Metadata | Version1; file1–67,108,864 bytes; piece65,536 bytes; metadata≤256KiB; ordered lowercase64-hex piece/full-file SHA-256; file ID hashes exact metadata bytes |
| Partition | `ceil(F/P)`; indices0…N−1; no padding/extra empty piece; maximum1,024 pieces |
| Frame | Four-byte unsigned big-endian encoded-header byte count; H1…16,384; control payload0; PIECE exactly expected piece length |
| Message IDs | Eleven types; request IDs integer1…2^63−1, increasing separately per connection/requesting direction |
| Peer identity | 1–32 ASCII letters/digits/underscore/hyphen; one active session per peer; lower lexicographic ID initiates; both directions transfer |
| Resource proposals | Max12 neighbors; events128; outgoing queue32; accepted uploads≤4 per neighbor including active response |
| Pipeline | Initially1; final default4 queued/transmitted requests per neighbor; sole local reservation per missing piece |
| Tracker | POST `/announce`; source IPv4; port integer1…65,535, not bool; body4KiB/response64KiB; announce5s; expire age≥20s |
| Tracker timing | Client timeout3s proposal; retries2/4/10s capped, reset on success; bounded server-body wait |
| Transport timing | Connect3s and handshake5s proposals; incomplete frame10s from first byte; distinguish idle polling timeout |
| Coordinator timing | Checks about100ms; queued request5s; response10s after completed REQUEST write; busy cooldown about1s proposal |
| Upload policy | Two interested recipients; reconsider5s; recent verified-contribution slot plus rotating opportunity; seeder rotates both; free rider0 before/after completion |
| Scale | S1/L6 and S2/L6; comparison L2/4/6/8 with S1 |
| Matrix | Nine configurations; at least3 repeats=27; five optional; randomized order where practical; comparable seeds/start schedules |
| Failure experiment | Designated downloader killed at recorded≥25% progress; retain seeder; expected survivors exclude victim; compare same survivor subset in baseline |
| Fixture | Fixed deterministic32MiB suggested; choose/adjust within64MiB during pilot before measured matrix |
| Timing/units | Local monotonic elapsed time; never subtract cross-host monotonic clocks; controller-based LAN timing; 1MiB=1,048,576 bytes |
| Terminal/demo | Status about1s; suggested8-minute demo plus separate corruption/free-rider evidence |
| Schedule | Original work23September–24October2026; dated milestones need historical evidence, not new test passes |

### A.9 Required data schemas and numerical interpretation

Required run fields: `run_id`, `revision`, `environment`, `file_sha256`,
`file_bytes`, `piece_bytes`, `L`, `S`, `strategy`, `window`, `upload_slots`,
`upload_cap`, `seed`, `startup_method`, `scenario`, `expected_completers`,
`actual_completers`, `duration_s`, `status`, `failure_reason`.

Required peer fields: `run_id`, `peer_id`, `role_at_start`, `completion_s`,
`final_hash_ok`, `verified_download_bytes`, `uploaded_payload_bytes`,
`messages_sent`, `requests_sent`, `retries`, `hash_failures`, `exit_reason`.

Useful per-peer throughput is source bytes divided by that peer's completion
seconds. Aggregate `L × source bytes / distribution seconds` applies only when
all L expected downloaders complete. In the kill scenario, compare the surviving
population with the same subset in its matched baseline. Include assembly and
final verification in completion. Count completed application frames at the
sender, not both endpoints; completed PIECE payload bytes exclude header/control
bytes, and partial writes have unknown byte count unless actually observed.
Availability is reconstructed offline from live verified ownership, never fed
as global information into the runtime picker. Undefined duration stays empty;
failed rows stay present; `(run_id, peer_id)` must be unique. Retain individual
observations and report mean plus standard deviation or min/max; explain rather
than silently remove outliers.

### A.10 Report, documentation and genuine human evidence

| Deliverable | Original writer / reviewer | Required evidence |
|---|---|---|
| Problem/scope/metadata/storage | Rishikesh / Prabhat | F01–F04 and independent hashes |
| Tracker/discovery | Debargha / Anik | T01–T03 and announce examples |
| Framing/messages/lifecycle | Anik / Rishikesh | N01–N05 and wire table |
| State/selection/pipeline/upload | Prabhat / Debargha | S01–S05, C01–C03 |
| Experiment method/plots | Debargha; all review / Rishikesh assembly | Manifests, raw CSV, scripts and uncertainty |
| Limitations/conclusions | All / all | Supported observations |
| Contributions/AI-use | Each / all | Actual commits/reviews/assistance, no invented authorship |
| Final report assembly | Rishikesh | Owner-approved sections, consistent units, every graph traceable |
| Documentation | Responsible owners | Install/startup, storage, tracker, protocol, architecture, integration/tests, experiments, contribution, AI-use and dependencies |
| Demo | All | Source hash→tracker→handshake→rarity/pipeline→downloader upload→failure recovery→output hashes→continued seeding→graphs/limitations |
| Viva | Each member | Whole workflow and own component; edge-case prediction; small live change/test; explanation of another member's module |
| Release rehearsal | All | Fresh setup, saved evidence, recorded backup demo and contribution sign-off |

AI-use records must truthfully include date, tool, purpose, affected artifact,
accepted material and its human review/validation. Historical learning/review
meetings and milestones cannot be inferred from today's tests. Mark missing
human participation, approvals and recorded demo evidence PENDING/BLOCKED.
Screenshots require captions/run IDs and are supplemental to raw logs and hashes.

The guide says the actual assignment sheet was unavailable. Cross-check the
course rubric with the human, particularly whole-piece requests, required
choking scope and minimum-peer interpretation. Do not invent rubric approval
or attendance. Any changed acceptance requirement must be resolved before the
freeze or trigger the complete-restart rule.

## Appendix B — Production module and executable inventory

The read-only preparation census found **78 non-test Python files**, including
package markers and entry points. All prefixes below are relative to
`bittorrent_lite/`; every listed filename is joined to its row's prefix. Recount
at Phase 00 and retain the exact manifest; a changed count requires explanation,
not automatic failure if additions are legitimate. The tests in the last column
are existing coverage anchors, **not claims that every required behavior is
already tested or passing**.

The repeated static audit found **140 Python files total: 78 non-test and 62
under tests, including 51 `test_*.py` modules**. Fifty test modules appear in the
historical per-file case inventory; the fifty-first is the preserved empty
handshake-connection module. This is a filesystem census, not pytest collection
or a fresh result. Include test helpers/fixtures/plugins in the frozen manifest
and verify their behavior as acceptance tooling; do not count them as production
modules or extra passed tests.

| Prefix / owner | Exact files (count) | Existing anchors and required extension |
|---|---|---|
| Package root / shared | `__init__.py`, `__main__.py` (2) | `tests/integration/test_module_imports.py`, `tests/common/test_paths.py`, real module entry point; verify installed exports and both entry paths |
| `storage/` / Rishikesh | `__init__.py`, `file_store.py`, `generate_metadata.py`, `hashing.py`, `metadata.py`, `pieces.py`, `transfer_store.py` (7) | `tests/storage/`, `tests/integration/storage/test_file_manager.py`, `tests/integration/test_existing_behavior.py`; alternate transfer store via network piece-handler/transfer tests; ST01–ST13 |
| `discovery/` / Debargha | `__init__.py`, `tracker_client.py`, `tracker_server.py`, `tracker_state.py` (4) | `tests/discovery/test_tracker.py`, `test_tracker_client.py`, real outage/restart E2E; TR01–TR08 |
| `experiments/` / Debargha | `__init__.py`, `scripts/__init__.py`, `scripts/collect.py`, `scripts/launcher.py`, `scripts/make_fixture.py`, `scripts/matrix.py`, `scripts/plot.py`, `scripts/stand_in_peer.py` (8) | `tests/discovery/test_experiments.py` is synthetic; `tests/end_to_end/test_real_experiments.py` is real. Matrix planning/execution failure behavior needs direct cases; EV01–EV06 |
| `networking/` / Anik | `__init__.py`, `connection.py`, `framing.py`, `messages.py`, `network.py`, `piece_handler.py`, `runtime_connection.py`, `session.py` (8) | `tests/networking/`, `tests/integration/test_real_backend.py`, E2E; assert `session.Handshake is messages.Handshake`; NW01–NW12 |
| `scheduling/` / Prabhat | `__init__.py`, `coordinator.py`, `models.py`, `piece_picker.py`, `request_manager.py`, `upload_policy.py`, `uploads.py` (7) | `tests/scheduling/test_piece_manager.py`; scheduler/pipeline/recovery/upload/original-plan/runtime integration suites. Retained Part 1 request manager needs direct contract tests; SC01–SC14 |
| `scheduling/legacy/` / preserved work | `__init__.py`, `_choking_manager.py`, `choking.py`, `piece_picker.py`, `request_manager.py`, `scheduler.py` (6) | `tests/scheduling/test_choking.py`, `test_piece_picker.py`, `test_prabhat_selection_contract.py`, `test_request_manager.py`, `test_scheduler.py`; existing-behavior and export-identity tests. Exercise public APIs separately |
| `scheduling/request_pipeline/` | `__init__.py`, `__main__.py`, `manager.py`, `models.py` (4) | `tests/scheduling/test_request_pipeline.py`, `test_piece_manager.py`, integration pipeline tests; CLI and `example.json` |
| `scheduling/recovery/` | `__init__.py`, `__main__.py`, `config.py`, `policy.py`, `selection.py` (5) | `tests/scheduling/test_recovery_policy.py`, `tests/integration/test_recovery_integration.py`; JSONL error recovery; standalone endgame remains disabled in original-plan production runs |
| `scheduling/upload_service/` | `__init__.py`, `__main__.py`, `models.py`, `service.py`, `sources.py` (5) | `tests/networking/test_upload_service.py`, `tests/integration/test_upload_integration.py`; memory/directory sources, manifest validation, demo and existing-directory refusal |
| `scheduling/choking_policy/` | `__init__.py`, `__main__.py`, `models.py`, `policy.py` (4) | `tests/scheduling/test_choking_policy.py`, original-plan/upload integration; CLI intended operations and continued operation after rejected input |
| `application/` / integration | `__init__.py`, `adapters.py`, `cli.py`, `metadata_tools/__init__.py`, `network_backend.py`, `peer_state.py`, `runtime.py` (7) | `tests/integration/test_peer_runtime.py`, `test_existing_behavior.py`, `test_real_backend.py`, E2E. `metadata_tools/__init__.py` contains only historical wrapper documentation; no `run_peer.py`, `run_seeder.py` or `run_tracker.py` executable exists there |
| `common/` / shared | `__init__.py`, `config.py`, `events.py`, `interfaces.py`, `logging.py`, `paths.py`, `run_log.py`, `types.py` (8) | Existing-behavior/import/path tests and downstream contract use; add direct logging/event-stream boundaries. Protocol/type declarations need compatibility checks, not fictitious execution counts |
| `examples/` | `__init__.py`, `scheduler_demo.py`, `scheduler_dependencies.py` (3) | Dependency helpers exercised by integration; execute demo with assertions on output, plus helper API contracts; imports alone insufficient |

At the time of this census, `tests/networking/test_handshake_connection.py` is
empty. Preserve it and record its zero cases; it cannot support handshake
coverage. Do not infer ownership from the test folder alone: for example, the
upload-service tests live under `tests/networking/`.

Non-Python inventory: root `pyproject.toml`, `pytest.ini`, `requirements.txt`,
`AGENTS.md`, `README.md`, `AI-USE.md`, `.gitignore`; both experiment configs;
pipeline `example.json`; every current document, original/follow-up plan and
ownership/contribution record; `docs/integration/path-migration.json`; all test
data/manual input files; preserved workspace archives. Classify generated
artifacts/environments explicitly. Verify original-to-current mappings without
running historical archived checkouts as if they were the active project.

### B.1 Known missing acceptance evidence to prepare

These are observed gaps in scope/evidence, not newly executed failures:

1. Unique content per full piece and independent assembly-order oracle; the old
   E2E helper repeats one 64 KiB block.
2. Complete real request/retry/message/hash-failure telemetry, including killed
   peers that cannot emit final counters; event-reader strictness and accounting.
3. Continuous queue, request-window, reservation, permission and resource traces;
   final file success alone cannot prove limits were never exceeded.
4. Real corrupt/slow/stale/mid-frame fault provider/proxy and healthy-source
   recovery; existing malformed-client coverage is not the entire fault matrix.
5. Process-level storage failure tests, isolated from real user data; existing
   component write/replace/hash-error tests do not prove whole-process behavior.
6. Full stress grid, connection storms, bounded queue shutdown and resource
   sampling; two-laptop and additional-OS results; concurrent cross-swarm test.
7. Dedicated logging no-op/idempotency/concurrent JSONL/path-change/error cases;
   strict validation must expose missing mandatory evidence even when logging is
   deliberately nonfatal to transfers.
8. Full matrix planning/supervision tests, all 27 new measured runs and plots;
   wheel/sdist/relocation installation; explicit example execution.

Use the existing suites as starting points. Every added scenario must have a
reviewed method before the freeze. Preserve alternate implementations and test
them in their own roles rather than wiring incompatible policies into the live
backend solely to increase apparent coverage.

## Appendix C — Supported CLI command forms

These interfaces were checked by **reading the actual parsers**, not by running
them in this planning session. They are EXISTING command forms. The command
recorder, guardian, strict verifier and missing cases remain PREPARE items.
`$Py`, `$Repo` and `$AttemptRoot` refer to §4.3. Do not paste blocks as an
unchecked sequence: each native command needs an immediate exit check and its
semantic oracle, through the recorder, before the next dependent step.

### C.1 Metadata and three separately supervised processes

The challenge fixture below must already have been generated and independently
hashed after the freeze/token step. Metadata output must not already exist.
Select/check ports, freeze and record their assignments; the values here are
examples, not promises that these ports are free on another machine.

```powershell
$Fixture = Join-Path $AttemptRoot 'fixtures\challenge.bin'
$Metadata = Join-Path $AttemptRoot 'fixtures\challenge.torrent.json'
$ManualRoot = Join-Path $AttemptRoot 'runs\manual-peer'
$Downloads = Join-Path $ManualRoot 'downloads'
$SeedStop = Join-Path $ManualRoot 'seed-01.stop'
$PeerStop = Join-Path $ManualRoot 'peer-01.stop'
$TrackerUrl = 'http://127.0.0.1:18000'
& $Py -m bittorrent_lite.storage.generate_metadata --file $Fixture --output $Metadata --piece-size 65536
if ($LASTEXITCODE -ne 0) { throw 'Metadata creation failed; stop campaign' }
```

Metadata success requires independently checked metadata fields, source length,
per-piece/full-file hashes and the SHA-256 of the exact metadata bytes. Errors
return 2. The metadata parser supports `--file`, `--output`, `--piece-size`;
there is no tracker/discovery flag on this command.

Configuration-only smoke form (record it separately):

```powershell
& $Py -m bittorrent_lite --peer-id seed-01 --port 17001 --tracker $TrackerUrl --metadata $Metadata --seeder --file $Fixture --output-dir $Downloads --check-config
if ($LASTEXITCODE -ne 0) { throw 'Configuration smoke failed; stop campaign' }
```

This does not open sockets or prove the later seeder-hash/collision checks.
Start the following as **three distinct guardian-owned concurrent processes**;
these foreground forms describe arguments only. The tracker/seeder/downloader
do not naturally exit after a transfer, so these lines are not a sequential
one-terminal script. Preserve stdout/stderr, observe each readiness signal and
enforce a bounded deadline before starting its dependents.

```powershell
& $Py -m bittorrent_lite.discovery.tracker_server --host 127.0.0.1 --port 18000
& $Py -m bittorrent_lite.application.cli --peer-id seed-01 --port 17001 --host 127.0.0.1 --tracker $TrackerUrl --metadata $Metadata --seeder --file $Fixture --output-dir $Downloads --stop-file $SeedStop --strategy rarest-first --window 4 --seed 1 --upload-workers 0
& $Py -m bittorrent_lite.application.cli --peer-id peer-01 --port 17002 --host 127.0.0.1 --tracker $TrackerUrl --metadata $Metadata --output-dir $Downloads --stop-file $PeerStop --strategy rarest-first --window 4 --seed 1 --upload-workers 0
```

For every child, set a **distinct** `BTL_EVENT_LOG` and `BTL_PROC_ID` in its
private environment; create event-file parents first. Without `BTL_EVENT_LOG`,
structured logging does nothing. The launcher's normal runs set these itself;
direct CLI execution needs the supervisor to do it. Require `tracker_ready`
plus actual endpoint reachability and a valid HTTP probe; readiness is not
established by sleeping for an arbitrary duration.

The peer additionally supports `--free-rider`, `--shutdown-timeout`, strategies
`sequential|random|rarest-first`, windows `1|2|3|4` and upload workers `0|2`.
Test both worker modes. Seeder mode requires `--seeder --file`; receivers must
receive no source-file path. Tracker supports only `--host` and `--port`, with
no stop-file option. Correct output is
`<Downloads>/<peer-id>/<metadata.filename>`, not directly under Downloads.

Wait for genuine COMPLETE, independently verify bytes, then prove continued
seeding. Create each peer's initially absent stop-file only when requesting its
shutdown. Stop the tracker using guardian-controlled interruption/termination,
record the platform mechanism and verify every exit. Expected deliberate tracker
termination is a predeclared cleanup action, not an unexpected test failure.
Argparse errors return 2. The outer CLI handler also returns 2 for caught
`OSError`/`ValueError`, including source/FileStore validation, bind/startup or
escaped runtime errors. Normal runtime return with recorded storage/recovery/
shutdown errors returns 1; an uncaught exception normally exits 1 with traceback.
Declare the precise path, exit code, error/state and cleanup oracle for each
negative case. Exit 0 without completion and verified bytes is not transfer success.

For install checks, use absolute console executables inside the selected venv:
Windows `Scripts/bittorrent-lite.exe` and `Scripts/bittorrent-metadata.exe`;
POSIX `bin/bittorrent-lite` and `bin/bittorrent-metadata`. Verify existence and
origin before invocation. `python -m bittorrent_lite` and
`python -m bittorrent_lite.application.cli` must reach the same intended runtime.
On LAN replace loopback with the frozen reachable tracker address and peer bind
addresses; do not reuse localhost between laptops.

### C.2 Preserved standalone modules and example

Each command below is an independently recorded finite process. Use an absent
or empty directory for the upload demo; every other scenario gets a different
directory. Successful demo content is synthetic, not real P2P evidence.

```powershell
$PipelineInput = Join-Path $Repo 'bittorrent_lite\scheduling\request_pipeline\example.json'
$UploadDemo = Join-Path $AttemptRoot 'runs\upload-demo'
& $Py -m bittorrent_lite.scheduling.request_pipeline --input $PipelineInput
if ($LASTEXITCODE -ne 0) { throw 'Pipeline CLI failed; stop campaign' }
& $Py -m bittorrent_lite.scheduling.upload_service demo --directory $UploadDemo
if ($LASTEXITCODE -ne 0) { throw 'Upload demo failed; stop campaign' }
& $Py -m bittorrent_lite.examples.scheduler_demo
if ($LASTEXITCODE -ne 0) { throw 'Scheduler example failed; stop campaign' }
```

The pipeline example must produce six action results: request 1 on connection 1
for piece 0; sending confirmed at time 1; expiry at time 11 retires the response-timeout
request; final pending list empty. Invalid JSON/file/action returns 2. Test every
operation using versioned JSON fixtures: `register_connection`, `set_available`,
`set_permissions`, `reserve`, `fill`, `confirm_sent`, `start_verification`,
`finish_verification`, `reject`, `send_failed`, `cancel`, `disconnect`, `expire`,
`snapshot`. Retain each input's bytes/hash and validate the actual output schema.

The upload demo must accept two 32,768-byte pieces and finish with
`sent_bytes=65536`, `sent_pieces=2`, `active_jobs=0`, `closed=true`. The demo uses
simulated delivery. Nonempty destination returns 1; missing subcommand returns 2.
The scheduler demo uses ManualClock, InMemoryStore and RecordingTransport;
assert verified piece/HAVE/next pending request. No real-network label applies.

Recovery and choking use JSON lines on stdin; they do not implement argparse
options. The recorder must supply and retain the exact stdin bytes, rather than
discarding the input after a shell pipeline. These are minimal valid examples:

```powershell
@(
    '{"op":"create","num_pieces":3,"seed":1}',
    '{"op":"snapshot","now":0}'
) | & $Py -m bittorrent_lite.scheduling.recovery
if ($LASTEXITCODE -ne 0) { throw 'Recovery process failed; stop campaign' }

@(
    '{"op":"config","random_seed":1}',
    '{"op":"connect","peer":{"peer_id":"peer-A","interested":true},"now":0}',
    '{"op":"tick","now":0}',
    '{"op":"snapshot","now":0}',
    '{"op":"shutdown","now":1}'
) | & $Py -m bittorrent_lite.scheduling.choking_policy
if ($LASTEXITCODE -ne 0) { throw 'Choking process failed; stop campaign' }
```

Recovery operations: `create` once first, then `rank_candidates`,
`allow_duplicate`, `failed`, `succeeded`, `snapshot`. Success has `ok:true`;
errors have `ok:false`, `error`, `message` even though the process can exit0.

Choking operations: optional `config` first, then `connect`, `disconnect`,
`set_interested`, `record_contribution`, `set_seeder`, `set_upload_enabled`,
`tick`, `acknowledge`, `snapshot`, `shutdown`, `reset`. All non-config operations
require `now`. Successful tick/acknowledge/snapshot responses do not require an
`ok:true` field: validate their decision/intents/state, accepted, or state schema
as appropriate. Errors have `ok:false`. Insert predeclared invalid input between
valid operations and prove both the error and correct continued state.

There are no standalone CLI entry points for every storage/discovery/networking
module. Use reviewed API tests for those modules. Do not invent wrapper script
paths from historical docstrings.

### C.3 Fixture and experiment tools

The following fixture CLI is included to test that tool's behavior and perform
a pilot. It does not replace independently challenged acceptance fixtures. Its
hashes are produced through project code and need independent recomputation.
Require a fresh output directory because it can overwrite same-named files.

```powershell
$FixtureDir = Join-Path $AttemptRoot 'fixtures\fixture-cli'
$BaseConfig = Join-Path $Repo 'bittorrent_lite\experiments\configs\base.json'
$PilotRuns = Join-Path $AttemptRoot 'runs\real-pilot'
$RealRuns = Join-Path $AttemptRoot 'runs\real-measured'
$Results = Join-Path $AttemptRoot 'results'
& $Py -m bittorrent_lite.experiments.scripts.make_fixture --size-mib 32 --seed 30003 --out $FixtureDir
if ($LASTEXITCODE -ne 0) { throw 'Fixture CLI failed; stop campaign' }
```

Supported fixture flags: `--size-mib` (float), `--seed` (int), `--out`.
Require a positive size within 64 MiB. Output names are `fixture.bin` and
`fixture.torrent.json`. After validating them, use this separate pilot form:

```powershell
$PilotArgs = @('-m','bittorrent_lite.experiments.scripts.launcher',$BaseConfig,
    '--set','L=2','--set','name=pilot',
    '--set',('fixture=' + (Join-Path $FixtureDir 'fixture.bin')),
    '--set',('metadata=' + (Join-Path $FixtureDir 'fixture.torrent.json')),
    '--runs-dir',$PilotRuns)
& $Py @PilotArgs
if ($LASTEXITCODE -ne 0) { throw 'Pilot launcher failed; stop campaign' }
```

Launcher supports optional config path, repeatable `--set KEY=VALUE` and
`--runs-dir`. Values are JSON-parsed where possible. Relative fixture/metadata
paths resolve against its discovered repository root; absolute paths assembled
from `$AttemptRoot` are portable without embedding another laptop's user path.
Its exit0 means manifest status `ok`, not that every hash/child exit is correct.
Audit status, inputs, all child logs/exits, completion population, kill trigger,
recomputed output bytes and resource cleanup immediately after each run.

Inspect the matrix schedule with the existing dry-run only:

```powershell
& $Py -m bittorrent_lite.experiments.scripts.matrix $BaseConfig --repeats 3 --order-seed 2026 --dry-run
if ($LASTEXITCODE -ne 0) { throw 'Matrix planning failed; stop campaign' }
```

The actual 27-run execution requires the **PREPARE supervisor** around
`plan_runs` and `Run.execute`, as specified in Phase 10. It must pass the
independently challenged fixture and frozen overrides to every run. Its
implementation/command must be reviewed and recorded before freeze; no such
new supervisor command is claimed to exist in this document. Existing matrix
flags are `--set`, `--repeats`, repeatable `--only`, `--order-seed`, `--pause-s`,
`--runs-dir`, `--out`, `--dry-run`. Do not use `--only` for full acceptance and
do not use its non-dry-run loop to implement the first-failure rule.

After all 27 indexed real manifests independently pass, collect them as a
separate checked operation:

```powershell
& $Py -m bittorrent_lite.experiments.scripts.collect --runs-dir $RealRuns --out $Results
if ($LASTEXITCODE -ne 0) { throw 'Collection failed; stop campaign' }
```

Collector supports only `--runs-dir`, `--out` and scans
`<runs-dir>/*/manifest.json`. It can skip unreadable manifests and exit0 on empty
input. Require **27 run rows and 180 peer rows**, unique expected identities,
including seeders and killed targets, excluding trackers. The current matrix
has `3+5+7+9+7+7+8+7+7=60` peer rows per repetition. Recompute counts from the
frozen explicit schedule; if configuration changes, update the expectation
before freeze. Undefined killed-peer completion is not a missing peer row.

Then, after validating collected data, plot into a fresh figures directory:

```powershell
& $Py -m bittorrent_lite.experiments.scripts.plot --results $Results
if ($LASTEXITCODE -ne 0) { throw 'Plotting failed; stop campaign' }
```

Only `--results` is supported. Require these newly generated files under
`<results>/figures/`: `fig1_swarm_size_distribution.png`,
`fig2_swarm_size_throughput.png`, `fig3_selection.png`, `fig4_seeders.png`,
`fig5_free_rider.png`, `fig6_failure.png`, `fig7_availability.png`, `summary.csv`.
Missing availability can omit fig7; an output glob can return stale images.
Thus fresh-directory checks, exact newly created file sets and visual inspection
are mandatory. There are five experimental comparison families but seven plot
images in this implementation.

`experiments/configs/stand_in.json` invokes the synthetic peer, copies source
files and simulates progress/counters. Test it only in the separate synthetic
lane. Its `--simulate-source`, `--pieces-per-s`, `--exit-after-s` and
`--upload-slots` are not real-peer flags. Never feed them to the application CLI.
Runtime strategy is `rarest-first`; experiment config value `rarest` is translated
by the launcher. The launcher injects repo `PYTHONPATH`, so its success cannot
prove installed/external-cwd import portability.

### C.4 Cross-platform execution and final handoff

The snippets above use PowerShell. On POSIX, either use a verified PowerShell
installation with paths rebuilt for that host or prepare equivalent shell-free
argument arrays in the reviewed supervisor. The Python venv interpreter is
`<venv>/bin/python`, not `Scripts/python.exe`. Resolve paths with `pathlib`/host
path APIs; do not pass Windows backslash paths to Linux/macOS. Preserve argument
boundaries, explicit cwd, per-process environment, stdin bytes and immediate
native exit status. Verify equivalents during preparation and freeze them.

Suggested message for the user to give Astra, along with this file:

> Execute this final acceptance plan on the current preserved checkout. Start
> with the preparation gate; do not claim its missing helpers already exist.
> Preserve all member work. Run every required phase with genuine recorded
> evidence. Stop on the first unexpected fault, preserve it, fix the cause and
> restart the entire campaign at Phase00 in a new attempt. Compare the final
> evidence against all five originals. Report unavailable resources, missing
> human evidence or independent verification honestly; do not mark them passed.

**Planning-session delivery status:** only this plan was created/amended. No pytest
collection, test run, application launch, experiment or product-code change was
performed to produce it. Execution results will belong to the separate campaign.

## Appendix D — Static audit and original-plan comparison

**Review date: 22 October 2026, Asia/Calcutta. Method: read-only inspection of
all five originals, current source/parsers, test files and this plan, followed
by documentation corrections. No tests or application processes were run.**
This is a planning review, not the independent execution attestation in §2.5.

### D.1 Original provenance and named coverage

The copies in `docs/plans/original/` were compared with the original files in
`C:\Users\KIIT\Downloads\` supplied by the user. All five match byte-for-byte
by SHA-256. Preserve these hashes as the original requirement snapshot:

| Original | Lines in reviewed copy | SHA-256 |
|---|---:|---|
| R — 01-Rishikesh-Individual-Plan.md | 323 | `27a55a2b758be5fc7f0ef4afff4f1383a58d0cceaa75cbdd79562d17750dae84` |
| D — 02-Debargha-Individual-Plan.md | 294 | `5ee42a0873a20b74e2bdeb49112b77027ddb874a1228ab598eae6598fbb3a04a` |
| A — 03-Anik-Individual-Plan.md | 321 | `6df26c7a8f15e2a03279ea175b8c78179a1f21e8059b6a2b8286344d8d89e7fb` |
| P — 04-Prabhat-Individual-Plan.md | 369 | `58cd4ff7d6fdc2739b008349777b25652bb5f7efa35ea142def4edbaadfbf5f0` |
| G — BitTorrent-Lite-Revised-Project-Guide.md | 1,033 | `dffb144c70dc7dd3a81a2ccacf831e2cfef4bfa03157f4a042eafd4f5b5c70f6` |

Appendix A represents all **27 master tests + 13 R + 12 D + 19 A + 21 P = 92
named tests**, all six G0–G5 gates and all task ranges R01–R10, D01–D11,
A01–A12 and P01–P12. The original minimum experiment set remains nine distinct
configurations × three repeats, with a shared matched baseline: 27 run rows and
180 peer rows for the frozen current schedule. Named-test presence is not a
claim that every original narrative clause was tested; NC01–NC12 add explicit
oracles for narrative gaps found during this audit.

### D.2 Master-guide section comparison

| Original guide section(s) | Where this plan covers it | Comparison / evidence limitation |
|---|---|---|
| 1 project outcome; 2 retain/change decisions | §3, SY01–SY04, §7 | Full verified transfer, redistribution, recovery; proposed design changes compared rather than assumed implemented |
| 3 scope/technology | §3, §7.1, Appendix B, EV07 | Exclusions explicit; shipped extensions tested separately; optional dependency differences disclosed |
| 4 architecture/dependencies | §7.1, §8, Appendix B | User-approved member layout supersedes suggested filenames; adapter ownership split recorded |
| 5 ownership/workflow | A.7/A.10, EV07–EV08 | Owner tasks/report attribution retained; historical activity requires genuine records |
| 6 metadata/storage | ST01–ST13, NC04/NC10, SP01–SP02 | Integrity, size, numeric order, streaming, atomic publication and original bounds |
| 7 frozen interfaces | §4/§8, NW/SC/TR/ST tables, NC01 | Actual symbols and error paths must be linked before freeze, including immutable handoffs |
| 8 tracker | TR01–TR08, NC08–NC09 | Membership-only role, HTTP contract, expiry, retries, ordering and outage |
| 9 wire protocol | NW01–NW12, NC01/NC05/NC11 | Eleven messages, independent byte oracle, framing, phase/ID rules and shared-socket timing |
| 10 state/concurrency | SC01–SC14, NW07–NW10, NC01, Phase08 | Ownership, queue bounds, lifecycle and genuine stress evidence |
| 11 selection/pipeline/recovery | SC02–SC09, NC02–NC03/NC12 | Interest versus eligibility, choked-advertiser rarity, reservation and stale/fault fairness |
| 12 simplified upload/free rider | SC10–SC13, NC07, Phase10 | Sparse/interested populations, transition-only controls, interval contribution and zero-upload invariant |
| 13 runtime sequence | SY01/SY07–SY08, NC09 | Listener before started, verified assembly before completed, stopped/cleanup |
| 14 milestones | A.6/A.8/A.10 | Fresh evidence cannot retroactively prove dated milestones |
| 15 tests/evidence | Phases02–08/12, §6, A.1–A.6 | Named and narrative tests preserved; full no-omission ledger required |
| 16 experiments | Phases10–11, NC06, A.9, C.3 | Fixed comparison controls and populations; actual launcher timing difference exposed |
| 17 logs/status/demo | EV02/EV10, Phase11, A.10 | Dedicated structured events versus stdout; status fields and witnessed demo |
| 18 viva | EV08, A.10, §1.2 | Human understanding/live changes in a separate teaching copy; no invented participation |
| 19 risks/decisions | §4.4, §7, SY02/SY04/SY11 | Required decisions and resources block rather than silently weaken acceptance |
| 20 submission/AI use | EV07–EV09, §9, A.10 | Report/source/evidence/dependencies, genuine contributions and disclosed assistance |
| 21 execution/gates | Phases00–13, A.6 | All six original gates retained; human's stricter full-restart instruction takes precedence |
| 22 defaults/records/ownership | A.8, §7.1, SC/NW/TR, §8 | Compare queue roles correctly; numerical and ownership differences visible |
| 23 handoffs | SY01–SY02, NC01, Phases04/07 | Real discovery/TCP/storage; deterministic source-isolated redistribution |
| 24 message-processing details | NC01–NC03/NC07/NC11–NC12, SC05–SC13 | Ordering, cancellations, stale events, corruption, final completion and cleanup |
| 25 named evidence matrix | A.1 | All 27 master IDs mapped; no historical pass substituted |
| 26 debugging | §1.2, §10 | Small diagnostic reproducer allowed; repair still restarts the entire acceptance campaign |
| 27 experiment runbook/counters | Phases10–11, A.9, C.3 | Fresh runs, complete rows, honest failures, exact populations/units/timing |
| 28 report ownership | A.10 | Original writer/reviewer roles preserved; real approval still required |
| 29 learning/viva | A.10, EV08 | Historical sessions need records; current demonstrations need witnesses |
| 30 references/individual plans | §3, A.2–A.10, NC references | Four individual contracts reviewed as well as master; no external reference treated as permission |

The four individual plans' outcomes, concepts, interfaces, ordered tasks, test
tables, handoffs, troubleshooting, viva and final sign-offs are addressed by
their owner-specific catalogue, A.2–A.5, A.7/A.10, §10 and NC references. During
execution, attach precise clause-to-node/evidence links; a section-level match
in this comparison does not satisfy a missing behavior assertion.

### D.3 Corrections made by this review

- Made 12 narrative contracts explicit: initial flags/BITFIELD order and
  snapshot race, interest semantics, choked-advertiser rarity, atomic assembly,
  independent wire bytes, timing origin, sparse upload policy, HTTP details,
  announce ordering, bounded reads, shared-socket timeout ownership and stale
  REJECT/corrupt-source fairness.
- Added seven parser/filesystem/standalone contract groups, including path
  aliases, malformed JSON structures, standalone limits and token/epoch safety.
  These protect preserved extensions from incorrect core-v1 restrictions.
- Corrected the queue comparison: coordinator ingress is still 128; separate
  backend/control queues are 32. Outgoing 64 versus proposed 32 remains a
  documented difference. Recorded session-state ownership and timing-origin
  differences plus the missing explicit metadata input-byte cap.
- Separated mixed console output from strict event JSONL and specified the
  deliberate-crash tail exception without allowing invented events/counters.
- Corrected CLI exit-code interpretation, installed-package checks, challenge
  replay/freshness, fatal worker-warning handling and safe PowerShell setup.
- Added resource preparation and separated live-change teaching copies from
  the frozen acceptance source so the restart rule remains coherent.

### D.4 Original requirements versus added acceptance scope

The original plans already require the 92 named tests, core fault/integrity
behavior, six-downloaders/one-and-two-seeders, comparison matrix, report and
human demonstrations. This final plan adds stricter evidence controls, a
16-configuration/eight-hour-minimum stress grid, explicit packaging/relocation/
cross-platform coverage, all preserved standalone APIs, and extended parser,
path and resource cases. The 64 MiB primary comparison fixture is an added
default within the original limit; the original suggested 32 MiB, subject to
pilot decisions. Label these additions separately in the final comparison.
They are acceptance scope, not proof the original author required every added
procedure or that an unimplemented feature should be added automatically.

Static document validation additionally found: exact agreement between the
original and mapped sets of 92 named test IDs; 89 unique acceptance catalogue
groups including NC/SP additions; no missing referenced local files or heading
links; no unfinished placeholders; consistent Markdown tables; and 17 PowerShell
blocks parsed without syntax errors **without execution**. The 784-node count
was read from the historical inventory only. None of these checks is a runtime
test or a substitute for the acceptance evidence.

### D.5 Review conclusion and remaining execution gate

After these corrections, no known named original test, owner task range,
experiment family or current production module is omitted from the plan's
inventory. The remaining uncertainty is executable evidence, not a claim that
the software already conforms. The additional procedures/helpers, metrics,
fault injection, human records, external resources and independent execution
verification must still be prepared or obtained under §4.

Use this document as the governing specification for Astra's preparation and
test campaign. Do not describe it as a one-command exhaustive suite. If any
required method/resource/contract decision is missing, report it as BLOCKED;
if execution finds an unexpected fault, preserve it, repair it and restart
Phase 00. A static audit cannot guarantee that every possible software error
has been anticipated.

<!-- End of the single plan. No execution evidence is asserted by this document. -->
