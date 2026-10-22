# AI Usage Documentation

**Project:** BitTorrent-Lite (P8)

**Course:** CS-30003 – Coding Assignment 1

## Part 1

- **Tool:** Claude (Sonnet 5.5 / Opus 5.5), accessed through the coding assistant used for the project
- **Additional tool:** OpenAI coding assistant (repository review, picker assistance and regression fixes)
- **Period:** September–October 2026

## Part 2

Prabhat supplied the independently developed `bittorrent_lite.scheduling.request_pipeline.zip`. The package
is retained as `bittorrent_lite.scheduling.request_pipeline` with its standalone API and CLI. An OpenAI assistant wired
it into the scheduler, fixed malformed CLI operation handling, and added
lifecycle, fault, randomized accounting, and storage/bridge integration tests.
The source ZIP was preserved unchanged. This work did not merge other branches
or implement the peer network loop.

## Part 3

| Category | Description |
|---|---|
| **Debugging & Refinement** | AI was used to investigate errors, refine existing implementations, and suggest targeted fixes for review by the team |
| **Code Review** | AI helped review existing code for correctness, edge cases, consistency, and style |
| **Test Assistance** | AI assisted in drafting and improving unit, integration, boundary, and regression tests |
| **Test Analysis** | AI helped identify edge cases and suggest additional test scenarios; the team remained responsible for reviewing and running tests |
| **Documentation Refinement** | AI helped refine wording and clarify project status in documentation |
| **Implementation Support** | AI also provided limited implementation assistance in areas recorded in the detailed log; generated suggestions were subject to team review |
| **Debugging** | AI helped reproduce issues, reason about likely causes, and propose fixes for review and validation |
| **Test Generation** | AI assisted with test cases and test harnesses to help check expected behavior and regressions |
| **Refinement** | AI suggested targeted improvements; team members were responsible for understanding, reviewing, and validating changes |

## Combined Part 4

| Category | Description |
|---|---|
| **Core Protocol Implementation** | All peer wire protocol code (handshake, bitfield, HAVE, REQUEST, PIECE, CANCEL) was written by team members |
| **Choking/Unchoking** | The choking strategy was implemented by team members |
| **Peer State Machine** | The peer connection state machine was implemented by team members |
| **Message Framing** | TCP framing (partial reads, length-prefixed messages) was implemented by team members |

At Prabhat's request, the assistant also replaced the 56 skipped test placeholders
with executable checks, fixed handshake-version validation exposed by those checks,
and documented the seven failures caused by the unfinished tracker state.
On request, the assistant implemented the tracker-state methods and added regression
coverage for heartbeat errors, expiry boundaries, detached snapshots and concurrent
membership changes. The tracker HTTP server remains unfinished.
The expanded audit added worker-transfer and invalid-input regressions, then fixed
partial mutations on invalid upload shutdown/dispatch arguments and invalid tracker
expiry timeouts. Validation included the full suite with warnings treated as errors,
source compilation and the scheduler demo.
At Prabhat's request, the assistant compared the integrated code with the original
September individual/master plans and aligned project scheduling, request IDs,
CHOKE behavior, timer recovery, upload selection, cancellation hooks, event bounds
and final-assembly status. Original-plan regressions and handoff documentation
were added; standalone optional behaviors remain separate from project defaults.
On request, the assistant completed independent owner-loop orchestration, CLI
configuration, metrics/status, discovery/session handoffs and bounded shutdown,
removed the unused choking scaffold, and tested the runtime with simulated
backends and real disk storage. Real socket/tracker integration remains a team
handoff; no real-network acceptance result is claimed.

## Earlier project assistance

| Date | Member | What AI Helped With | Category |
|---|---|---|---|
| 2026-09-15 | All | Architecture design, module interfaces, project scaffolding | Design & Boilerplate |
| 2026-10-04 | Prabhat | OpenAI coding assistant audited progress, assisted the initial neighborhood availability and rarest-first picker implementation, wrote contract/import tests, repaired stale shared-type imports and an unused missing-constant import, and documented remaining work. This includes AI assistance with core selection code; Prabhat must review, understand and check course rules before submission. | Implementation Assistance, Testing, Integration Review & Documentation |
| 2026-10-04 | Prabhat | At the user's request for extensive repository testing, The OpenAI coding assistant reproduced and fixed validation, stale piece-state, source verification, output preservation and peer-state defects; wired the existing metadata CLI to implemented functions; added boundary, fault-injection, randomized and concurrent tests; corrected README status. | Debugging, Regression Testing & Documentation |
| 2026-10-16 | Debargha | Claude (Sonnet 5.5 / Opus 5.5) was used as a supporting tool during development, primarily to investigate bugs, refine existing code, review edge cases, and assist with generating and improving tests. It also provided implementation suggestions for parts of the tracker, discovery client, and experiment scripts. Debargha was responsible for reviewing and validating changes and should be able to explain the submitted work. | Debugging, Refinement, Test Assistance & Limited Implementation Support |
| | | | |

---

## Team Declaration

We confirm that:
1. AI assistance, including the specific implementation support recorded for the piece-picker on 17 October 2026, is disclosed in the log above.
2. AI was used as a supporting tool for activities described in this document, including debugging, refinement, test assistance, code review, and the limited implementation support explicitly recorded in the log. Team members are responsible for reviewing the applicable course rules and ensuring this disclosure is accurate.
3. Team members are responsible for understanding, reviewing, testing, and being able to explain the work they submit.

**Team P8:**
- Rishikesh Kumar (2405600)
- Debargha Bhadra (2405575)
- Prabhat Ranjan Swain (2405590)
- Anik Dey (2405558)

## 22 October 2026 — member-owned layout

At the user's request, an OpenAI assistant reorganized the merged main revision
into storage, discovery, networking, scheduling, application and common areas.
All project folders now live under BitTorrent/bittorrent_lite. The assistant
updated imports, CLI/module references, relative paths, documentation links,
packaging metadata and ownership documentation, and preserved original plans
and historical workspace material. It restored the existing ChokingManager
export after static inspection found it missing from the merged compatibility
module. No core algorithm was replaced. Verification was limited to static
inspection; tests and runtime execution await the user's explicit authorization.

## 22 October 2026 — authorized unit-stage validation

At the user's request, the assistant installed a fresh editable test environment,
inventoried 737 tests and ran the approved 537-test unit stage with stop-on-first-
failure behavior. It corrected a malformed-handshake test fixture, added four
constructor rejection cases and five portability cases, and reconciled a stale
choking-export assertion with the requirement to retain both implementations.
Affected groups were rerun from the beginning, followed by the complete unit
stage: 537 passed, no skips/xfails, with 14 dependency deprecation warnings.
A blank selector accidentally expanded one attempt to the full suite; the first
synthetic experiment began before interruption. This boundary error is recorded
in the report, was not accepted as validation, and led to blank-selector and
collection-allowlist guards. Further integration/system testing remains gated
on the user's explicit go-ahead. No production algorithms or history were changed.

## 22 October 2026 — authorized integration/system validation

The user authorized the remaining 200 tests, with first-failure stopping and
complete affected-group reruns. The assistant resolved a sandbox-only localhost
restriction by rerunning with permitted sockets, aligned five legacy networking
test fixtures with the existing integer protocol version, and corrected reader
error handling and socket cleanup in PeerConnection. The protocol-mismatch test
now also checks socket and worker cleanup. All 200 tests subsequently passed
together; a full 537-test unit regression also passed. No tests were skipped or
removed. The report distinguishes simulated runtime/synthetic harness testing
from real application end-to-end validation and records the still-missing CLI
backend integration. Original files, definitions and plan hashes were audited.
No commit, push or history rewrite was performed. Separate end-to-end testing
remains pending the user's go-ahead.

## 22 October 2026 — authorized real backend and end-to-end validation

After the user's go-ahead, safe-checkpoint pause and explicit resume, the
assistant implemented the network backend and scheduler transport adapter using
the existing tracker, TCP connection, framing, runtime, storage and scheduling
components. It added admission activation, bounded queues, write acknowledgements,
queued-frame withdrawal, frame deadlines, default CLI wiring, portable stop-file
shutdown and real experiment logging/path integration. Existing standalone
implementations were retained. One previous CLI test was updated for the now
available default backend. The assistant added 12 adapter and 33 real process
tests; package discovery also added two import checks. Progressive groups and
the complete suite passed: 784 tests, no skips, 14 dependency deprecation warnings.
The final audit retained all 737 prior test IDs, all mapped original definitions
and files, and the five original plan hashes. A report-helper artifact selection
issue was corrected without changing production code after the final run.
Results are Windows localhost acceptance evidence, not cross-laptop or exhaustive
stress validation. No commit, push, merge or history rewrite was performed.

## 22 October 2026 — final acceptance preparation, in progress

The user authorized final acceptance preparation, testing and necessary repairs.
The OpenAI coding assistant and cooperating agents authored acceptance recorders, process guardians,
strict evidence/collection verifiers, fault helpers, portability/build checks,
coverage support, telemetry and additional regression tests. Repairs include
bounded storage reads, controlled parser errors, logging order/descriptor cleanup,
wire field validation and local CLI path/input checks. Original implementations,
standalone modules, original plans and existing uncommitted work are retained.
The agents also assisted documentation and requirement mapping.

Fresh command records and failed diagnostics are under
`.validation/final-acceptance/preparation-20261022-01`. These are preparation
diagnostics, not a completed acceptance attempt. Failures and focused reruns are
retained separately. A source freeze/challenge, complete campaign, external-device
evidence and independent final verification remain separate gates. Contributor
review, course-rule approval, demo attendance and signatures remain pending;
this entry does not claim human review or substitute AI authorship for members.

## 22 October 2026 — college submission handoff

The user subsequently narrowed the task to practical college-project readiness
and explicitly stopped the intensive acceptance campaign. The assistant repaired
experiment success/exit validation and metric collection, added focused
regressions, and prepared portable setup instructions and a repository handoff.
Current verification and unexecuted work are recorded in the accompanying
submission report. The full 27-run study, cross-device demonstrations and formal
independent acceptance review are not claimed. Earlier failed diagnostics and all
contributors' files/history remain preserved in the working repository. No
commit, push or merge was performed. Team members must review the submission and
explain their contributions; this assistance does not establish human sign-off.
