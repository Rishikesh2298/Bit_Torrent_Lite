# Real backend and end-to-end validation — 22 October 2026

**The real network backend is connected, and the complete repository suite
passed: 784 passed, 0 failures, 0 errors, 0 skips and 0 expected failures.**
The final single run took **229.00 seconds (3 minutes 49 seconds)**. All 737
previously passing test IDs are included. The additional 47 cases comprise 33
real end-to-end tests, 12 adapter tests and two package-import checks.

The final run began at 15:17:33 on 22 October 2026, Asia/Calcutta. These results
apply to the uncommitted `refactor/member-owned-layout` working tree, based on
`6ea28b1ea8711e87b637d118699161f297143be6`. No commit, push, merge or history
rewrite was performed. The earlier unit/integration reports remain historical
records of the stages before this backend was connected.

## What changed

- Added `application/network_backend.py`, connecting the existing TCP listener,
  tracker discovery worker and runtime through bounded worker queues.
- Added `networking/runtime_connection.py`, a subclass of the existing peer
  connection. It validates session identity and initial bitfields, acknowledges
  actual full writes, supports exact queued-message withdrawal and delivers
  events only after owner-thread admission. The legacy connection and policy
  implementations remain available and tested.
- Connected the default CLI to the real backend while preserving dependency
  injection for component tests. Added listener-host selection, graceful signal
  shutdown and a portable stop-file control for process supervisors. Peer ID
  validation now matches the tracker's existing 1–32 character contract.
- Corrected partial-frame handling: data already read is retained across socket
  polling timeouts, with a bounded frame deadline. Previously, a timeout between
  fragments could return control to the reader as though a fresh frame began.
- Added runtime admission activation and verified-piece/progress events, then
  connected the existing experiment launcher to real readiness, counters,
  completion logs, output paths, strategy/window settings and graceful shutdown.
  The synthetic configuration and its tests are preserved separately.

The storage, discovery and scheduling implementations were not rewritten.
Their existing interfaces perform hashing, persistence, tracker membership,
selection, request recovery, uploads and choking. The old CLI test that expected
an absent default backend was updated to check default-factory dispatch and
cleanup, while retaining its configuration-only assertions and test function.

## What passed

| Group | Cases | Evidence |
|---|---:|---|
| Previous unit and integration inventory | 737 | Every prior test ID appears as PASSED in the final run |
| Imports of added production modules | 2 | Both new modules import successfully |
| Adapter boundaries | 12 | Fragmented/coalesced frames, partial-frame deadlines, queue limits, exact withdrawal, full-write vs failed-write acknowledgements, invalid sessions and early-event ordering |
| Real CLI smoke transfers | 3 | One byte, exactly 64 KiB, and 524,411 bytes with a short final piece |
| Real redistribution and swarm configurations | 22 | Redistribution without original source; one/two seeders with six downloaders; 18 strategy/window repetitions; 64 MiB transfer |
| Real process fault/recovery scenarios | 5 | Tracker outage/restart, absent tracker at startup, killed/restarted downloader, malformed client, persistent free rider |
| Existing launcher with real peers | 3 | Baseline, free rider and targeted peer crash, followed by collection |
| **Total** | **784** | **No skipped or expected-failure cases** |

The 18 configuration repetitions cover sequential, random and rarest-first
selection, each with request windows one and four, repeated three times. These
are correctness checks, not a statistical ranking of strategy performance.

## Real-transfer evidence

The new CLI acceptance tests launch separate tracker, seeder and downloader
processes with the installed Python executable. They use temporary working
directories outside the checkout, including a path with spaces, with PYTHONPATH
removed. Non-seeders receive metadata and an output path, but no source-file
argument. The supervisor does not supply piece bytes or choose requests.

Each expected completed output is independently checked for size and SHA-256.
Fresh downloaders' verified-byte counters equal the source size; the smoke
tests also require the seeder's acknowledged upload-byte total to match exactly.
Completion appears once, after assembly. The 64 MiB case passed twice: in the
progressive swarm group and again in the complete suite. Its final test case
took 74.244 seconds, including setup and cleanup; that is not a benchmark claim.

Redistribution is tested by completing the first downloader, stopping the
original seeder, renaming its source file, and starting a new downloader. The
new peer obtains the correct file from the completed downloader, whose upload
counter equals the transferred size.

The failure scenarios verify that:

- An established transfer completes while the tracker is down. Restarting the
  tracker permits a late peer to discover sources and complete.
- A downloader killed after storing some pieces restarts with the same identity
  and store; its new verified-byte total equals only the missing bytes.
- A free rider still uploads zero bytes after completion and after an upload
  rotation interval. A late peer with no other source does not falsely complete.
- An invalid wire header closes the affected connection without preventing a
  healthy downloader from completing afterward.
- Peers started before the tracker retry discovery and complete after it starts.

The existing launcher also ran three real configurations. Their manifests are
labelled `localhost`, with `synthetic: false`; expected survivor outputs passed
hash verification. In the crash configuration, only the designated peer was
killed after reaching at least 25% progress. Surviving peers exited cleanly.
The free-rider run's collector recorded zero uploaded bytes for its target.

## Failure discipline and execution history

All test commands used `-x` to stop at the first failing case. **Every test
execution in this resumed stage passed on its first attempt**, so no failed
application scenario had to be repaired and rerun. Boundary issues found during
interface review were addressed before these executions, then covered by the
new tests. Groups were followed by a complete regression run on the final code.

| Execution | Result | Pytest elapsed time |
|---|---|---:|
| Adapter group | 12 passed | 0.74 s |
| CLI smoke group | 3 passed | 7.64 s |
| Swarm/configuration group | 22 passed | 131.20 s |
| Fault/recovery group | 5 passed | 42.55 s |
| Real launcher group | 3 passed | 15.52 s |
| Complete repository suite | 784 passed | 229.00 s |

The post-test evidence helper initially encountered unrelated unit-test files
also named `manifest.json`, including deliberately malformed fixtures. Its
selection was narrowed to real-launcher artifacts and the full audit rerun
successfully. This was a report-helper correction, not a failing application
test; no production code changed after the final test run.

## Preservation, environment and cleanup

The migration audit confirms all **148 mapped original files** are present and
all original function/class definitions remain (with the earlier documented
unit-test rename accounted for). All **five original plans** still match their
preserved SHA-256 hashes. All prior test node IDs remain present and passed.
These checks demonstrate retention; they do not claim changed adapter behavior
is byte-for-byte identical to the pre-integration source.

The final run used Windows, Python 3.12.14, pytest 9.1.1 and pytest-timeout 2.4.0
in the existing editable `.venv`. The default per-test timeout was 30 seconds;
the real process modules explicitly use 120/180 seconds, and the preserved
synthetic module uses 90 seconds. Localhost sockets and child processes were
permitted outside the execution sandbox's network restriction.

The run reported **14 matplotlib/pyparsing deprecation warnings**, unchanged
from earlier stages. They were not suppressed. No unhandled-thread warning
appeared. Final process records show completed cleanup for all 30 direct CLI
scenario artifacts and all three real-launcher manifests. Expected hard-killed
fault targets have recorded exit codes. A Windows process inspection found
**zero matching project Python processes** afterward.

Source/config snapshot SHA-256:
`c2ced6fb98401c3b5fa76739e13c44fa037acc4410f7eafed99b7b3b6261a2ab`.
The machine-readable inventory stores individual file hashes and original-test
coverage, so this result is tied to the actual working tree rather than only
the base Git commit.

## Limits and next use

Real CLI transfers now work in the tested Windows localhost configuration.
This is not evidence for a second laptop, Linux/macOS, a real LAN, NAT traversal,
long-duration load behavior, exhaustive malformed-traffic fuzzing or every
possible disk failure. No line/branch coverage percentage is claimed. Existing
component tests cover additional corruption/storage/backpressure cases, but
those should not be relabelled as separate-process acceptance tests.

The collector records real verified/downloaded and acknowledged/uploaded bytes.
Aggregate metrics that are not yet instrumented, such as total request/retry/
hash-failure counts, remain undefined rather than fabricated. Original plans
and follow-up plans are retained as references; passing this suite does not
assert every research experiment in those plans has been performed.

The [backend guide](real-network-backend.md) contains portable install/run
commands, output locations and shutdown instructions. To rerun the entire
suite from the repository root after installing test/experiment dependencies:

```sh
python -m pytest -x -vv --strict-markers --timeout=30 bittorrent_lite/tests
```

## Saved evidence

- [Full log](../../../.validation/logs/full-real-1.log) and [JUnit XML](../../../.validation/results/full-real-1.xml).
- [Machine-readable inventory](end-to-end-validation-inventory.json): all 784 passed node IDs, per-file counts, attempt summaries, source hashes and process/manifest paths.
- [Real test artifacts](../../../.validation/temp/full-real-1): commands, per-process stdout/stderr, stop controls, downloaded files, partial stores, hashes, manifests and collector outputs.
- [Evidence audit script](../../../.validation/e2e_audit.py).

Raw logs and temporary artifacts are local evidence in ignored `.validation/`;
the report, inventory, source and test cases are in the project tree. Existing
attempts were retained. No cleanup deleted the test evidence.
