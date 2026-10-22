# Semantic original-requirement review

Companion to `original-requirements-reviewed.json`. This is a source review,
not acceptance execution, coverage measurement, member approval or independent
verification. No pytest collection, tests or application processes were run by
this review. Static Python AST parsing extracted real assertions and decorators
without importing project modules. An initial oversized static command failed
at the Windows command-length limit before execution; smaller static commands
then built the document. Later static reads used the repository's explicit
Python path and UTF-8 after the system Python alias and default text encoding
were unavailable. These are preparation tooling errors, not test outcomes.

## Inventory and meaning

The supplement contains all **92 named original tests**, all **six G0–G5 gates**,
all **45 individual work packages** (R10, D11, A12, P12), **139 follow-up
paragraph/schema/table clauses**, and **158 original narrative sections**.
Every entry retains original source text, exact line span and document SHA-256.
All five original hashes match the controlling plan's pinned hashes.

The static line reconciliation has no omitted nonblank, nonheading source
lines across the nine original/follow-up documents. This proves inventory
retention, not semantic test completeness. Narrative sections retain obligations
that the named test tables alone omit, including human handoffs, interfaces,
timing, metrics, report ownership and viva work.

There are **179 exact pytest function/class selectors** with their source hashes,
line spans, actual assertion/raises excerpts and parameterization decorators.
Selectors encompass all their parameters; genuine collection must still expand
and reconcile every individual parameter identity. Assertion source extraction
does not claim that helpers or fixtures have executed.

For narrow named-test scope, **81 assertion procedures are identified** and
**11 remain blocked** by a stated procedure gap. Every acceptance status remains
NOT_RUN. “ASSERTION_PROCEDURE_IDENTIFIED” is deliberately distinct from PASS,
measured coverage and readiness of a larger catalogue scenario.

The broader follow-up clauses deliberately retain SUPPORTING_SUITE_ONLY scope.
Their related tests are useful evidence leads, but the review does not assert
that a suite exhausts every field, operation, invalid input, boundary or branch
in the paragraph. Those clauses and original narrative sections remain BLOCKED
until exact clause-level proof is reconciled. All six gates remain blocked.
Consequently this supplement **does not open the overall PREPARE gate**.

## Narrow procedures added after the first review

- F01/R-T01 now have five literal partition oracles: sizes 1, 65535, 65536,
  65537 and 131072, with exact count/length expectations and independent hashes.
  The 65537-byte case explicitly requires `[65536, 1]`.
- A-T03/N02 now have three distinct ordered frames, including binary PIECE,
  through a finite socket double and actual connected sockets.
- A-T05/A-T06/N03 now assert receiver read requests before oversized body
  consumption, plus self-close and no received event. These bounds tests use
  controlled socket doubles and do not claim measured process-memory limits.
- A-T09–A-T13 now have distinct procedures for repeated BITFIELD after an actual
  handshake, eight prefix/header/body EOF offsets, pure idle polls, self-close
  before test cleanup at an injected frame deadline, and 48 frames from four
  producer threads through one actual socket writer.
- A-T14/C01 now inject owner-thread Request/Cancel into the actual upload
  controller and writer, assert zero canceled payload bytes, and decode the next
  HAVE and clean EOF through a real socket pair. This does not claim that the
  CANCEL itself traveled over a real network.
- A-T15 now pauses a mock write after three bytes, cancels the actual upload
  job, and requires complete PIECE then HAVE, exact bytes and reservation
  release only after completion. The late-receiver subcase separately revokes
  via CHOKE; C02's full cancellation composition remains blocked below.
- A-T16/N05 now assert exactly one send attempt after controlled partial failure,
  no replay or following frame, no successful-upload credit and unknown partial
  bytes in production telemetry.
- A-T17/P-T13 now synchronize controlled reader/writer failures and assert one
  disconnect, zero pending/outstanding/availability, nonnegative piece and
  pipeline counts, and zero upload job/slot/read/output reservations.
- P-T04 now compares four ranking histories from identical seeds while all six
  candidates have rarity two, checks input immutability, and proves that sixteen
  different seeds produce more than one tie order.
- P-T09/F02 now distinguish same-length one-byte hash corruption from length
  and local-I/O errors. Assertions require no HAVE/store/verified credit on
  failure, then a healthy alternate request for the same piece and sole valid
  commit with exact provider/request provenance. Root's diagnostic 045 exposed
  an authored test API error (`get_piece` instead of `read_piece`); root
  corrected that procedure without changing its exact-byte assertion. The
  source assertion index reflects the corrected `read_piece` call.

The new wire file contains 14 functions and 29 declared parameter cases. Root
reports its initial diagnostic 041 passed; subsequent added counter assertions
and the new hash-retry procedure require their own recorded diagnostics. This
review did not execute or independently verify those runs. The ledger describes
source procedures, and none of these reports is acceptance credit.

## Remaining named procedure gaps

- R-T03: deep JSON and local startup validation now have repaired procedures;
  duplicate-key/extra-field contract decisions and complete field-domain
  reconciliation remain unresolved. No owner approval is implied.
- D-T10: a real process-tree negative-control procedure now starts the guardian
  while its actual supervisor is alive, observes a predeclared supervisor exit
  17, and requires worker/grandchild cleanup with exact preserved binary logs.
  Explicit child identities register immediately with expected-identity checks.
  It launches the OS-observed interpreter directly, preserving the parent's
  exact psutil module path/hash, to avoid conflating Windows venv redirector PIDs
  with script PIDs. Observed OS-created auxiliaries retain their owned ancestry
  and must also be gone. Windows read-only process handles require actual normal
  guardian/worker/grandchild exits of zero; unavailable POSIX non-child statuses
  remain unknown. This reviewer parsed, but did not execute, the procedure.
  Persistent evidence goes under the enclosing command record when present.
  Root's recorded preparation diagnostic 055 passed its single fixture test:
  the supervisor exited 17 as declared, and guardian, worker and grandchild
  each exited zero. Existing [command evidence](../../../.validation/final-acceptance/preparation-20261022-01/diagnostics/055-guardian-live-supervisor-crash/command/record.json)
  and [JUnit](../../../.validation/final-acceptance/preparation-20261022-01/diagnostics/055-junit.xml)
  are indexed with fixture records and independently recomputed raw-stream
  hashes in the supplement. This review is by the same preparation team and
  supplies no independent-verifier or acceptance credit.
  A separate finite procedure now calls the preserved original `Run._start`
  and `Run._kill_target`, requires the actual interpreter to stop while a
  separate owned control stays alive, and retains the raw target streams.
  This is a controlled target kill without network credit. The complete original
  launcher's own crash/registration/descendant-cleanup lifecycle remains a
  separate uncovered obligation, so D-T10 stays blocked. D-T12's
  failed-row retention oracle does not establish all graph/uncertainty semantics.
- P-T21: component stall and fake-clock retry assertions do not yet establish
  combined live no-source status with periodic tracker rediscovery.
- C02: a composed outgoing CANCEL/endgame/timeout path, started response and
  safe late-frame discard on that same session remains needed. The new mock
  stream and separately CHOKE-revoked receiver are explicitly partial support.
- I01/I02/Y01–Y05: existing live test code is useful, but its diagnostic fixture
  cannot become a fresh independent challenge by relabeling. Source rename is
  not access denial; before-completion sharing and exact source provenance,
  six-peer failure conditions, continuous resource bounds and independently
  verified outputs remain separate requirements.

Seventeen helper procedures support D-T10's identity and evidence
handling: fourteen strict-interpreter process-double tests, two registration tests,
and one parameterized strict-event parser test. They check identity changes,
actual-versus-wrapper exit status, PID reconciliation and sequence validation.
They also require a fresh local fallback registry, preserve an inherited registry
without claiming guardian verification, and refuse to reuse an existing local
registry while preserving its sentinel file.
The latest controls distinguish exact Windows psutil exit 15 from Popen exit 1,
reject exit 1 for a psutil tracker, and reject nonzero as ordinary graceful stop.
Their process doubles and synthetic JSON are explicitly supporting unit evidence;
they do not establish the original launcher's live crash lifecycle or close D-T10.

## Additional narrowly scoped preparation procedures

The JSON now includes five supplemental procedure groups and fourteen exact
helper/function source entries with hashes, line spans and retained source text.
These entries supplement the original clauses without changing any acceptance
status or closing a broader blocked requirement.

- Installed-transfer controls comprise ten test functions with twenty declared
  parameter cases. Their mocked processes and artificial events validate helper
  rejection rules only. The separately versioned
  [installed-transfer stage](PREPARE-INSTALLED-TRANSFER-PROCEDURE.md) requires
  fresh successful packaging, then actual wheel and sdist execution at 1,
  65536 and 524411 bytes. Its oracle binds isolated interpreter commands and
  installed hashes, strict OS identity, send/receive/commit provenance, retained
  piece bytes and exact final output. No execution result is inferred here.
- The original-launcher finite target/control probe exercises actual processes
  through the preserved launch and kill methods. It does not exercise a complete
  supervisor crash or the six-downloader 25-percent network failure scenario.
- The [five-interpreter coverage procedure](COVERAGE-LIFECYCLE-PREPARATION.md)
  obtains its worker, guardian, tracker, seeder and downloader population from
  live OS registration/readiness evidence. Four normal interpreters must flush
  real branch databases; the tracker-only predeclared abrupt termination remains
  `INTERRUPTED_NOT_COUNTED`. Missing/unregistered/duplicate controls use retained
  copies. Function-body/arc anchors establish participation, not full coverage.
- The guarded localhost 1S/1L lifecycle procedure checks strict events, exact
  output bytes and useful downloader counters. Initial seeder source-readiness
  is kept separate from downloader completion/transfer credit. Its generated
  diagnostic fixture is not an independent acceptance challenge.
- Exact Windows API exit-code controls are finite process-double procedures,
  as distinguished above. They do not substitute for real wait/cleanup evidence.

Diagnostic 070 exposed a mutable `sys.argv` reference retained by coverage
startup: Python's `-m` processing later changes element zero. The repair captures
`list(sys.argv)` and leaves strict startup/finish equality intact. The new
regression uses a mocked finite collector/process, mutates the original argv
list and invokes the captured finish callback. It asserts unchanged startup
bytes and equality of every startup identity field. This is an authored helper
regression, not measured coverage or an inferred diagnostic pass.

## Product repairs reviewed after reporting the gaps

The root repaired `storage.metadata.load_metadata` to convert deeply nested
bounded JSON RecursionError into ValueError. The new CLI regression checks
controlled rejection, return code 2, no traceback and unchanged input bytes.

`--check-config` now calls shared local network validation and validates portable
names, source path/hardlink collisions, source hashes and optional resource
availability before its early return or backend construction. Assertions cover
Unicode/spaces from an unrelated directory, invalid tracker URLs, excessive
network piece size with the generic metadata API preserved, reserved/path names,
hardlink collisions and changed source bytes without output creation. Optional
resource-provider failure is a separate broader scenario requiring exact mapping.
The JSON supplement retains current source hashes, function spans and quotes
for these repairs. Root reports diagnostic 032 passed; this reviewer supplies
static source/assertion review, not independent execution verification.

Stale missing-procedure phrases were corrected in R03, D06, A02, A03, A07 and
A08: deep JSON/check-config validation, guarded OS registration, receiver bounds,
three-frame coalescing, concurrent producer framing and queued-cancel/next-frame
procedures now exist. Their broader malformed-domain, contract/handoff,
fragmentation, live resource/scale and composed late-CANCEL obligations remain
BLOCKED. No original clause, source quote or human approval was rewritten.

## Preserved distinctions and next review step

The deviation records keep standalone copy/endgame defaults, standalone upload
limits, original metadata limits, proposed HTTP error alternatives, discovery
timeout override, explicit-destination overwrite policy and historical protocol
draft distinct. No owner approval was invented. Current user authorization for
preparation/tests/repairs is explicit; historical staged testing allocations do
not erase it.

Use this file with the root's complete source-line and AST module/function/
decision inventories. Close each listed gap with an exact reviewed procedure,
then expand parameters through genuine collection. Add real human/manual
procedures where required. Rehash changed test files and preserve the revised
mapping before freeze. Only a complete fresh attempt and independent audit can
supply execution credit; this review supplies none.

The latest static refresh updated twelve previously indexed stale selectors and
added seventeen narrowly supporting selectors, including file hashes, line
spans, assertion excerpts and parameterization decorators. All 179 indexed
selectors and fourteen supporting helper source entries matched their current
files at review time. All requirement readiness/acceptance states and human
approval fields were preserved; the explicitly noted stale gap wording was
corrected while retaining its broader obligation. Previous JSON/Markdown bytes,
their hashes and the static refresh script are retained under
`preparation-preimages/semantic-review-final-helpers`. The JSON field
`source_hash_refresh_pending` records this as `REFRESHED_AT_REVIEW_TIME_NOT_FROZEN`.
This is not a frozen-revision claim. Any later change to an indexed source
requires another refresh before its mapping can support the freeze.
