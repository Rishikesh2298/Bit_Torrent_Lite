# AI Usage Documentation

**Project:** BitTorrent-Lite (P8)

**Course:** CS-30003 – Coding Assignment 1

## Part 1

- **Tool:** Claude (Sonnet 5.5 / Opus 5.5), accessed through the coding assistant used for the project
- **Additional tool:** OpenAI Codex (repository review, picker assistance and regression fixes)
- **Period:** September–October 2026

## Part 2

Prabhat supplied the independently developed `request_pipeline.zip`. The package
is retained as `request_pipeline` with its standalone API and CLI. An OpenAI assistant wired
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
| 2026-10-04 | Prabhat | OpenAI Codex audited progress, assisted the initial neighborhood availability and rarest-first picker implementation, wrote contract/import tests, repaired stale shared-type imports and an unused missing-constant import, and documented remaining work. This includes AI assistance with core selection code; Prabhat must review, understand and check course rules before submission. | Implementation Assistance, Testing, Integration Review & Documentation |
| 2026-10-04 | Prabhat | At the user's request for extensive repository testing, Codex reproduced and fixed validation, stale piece-state, source verification, output preservation and peer-state defects; wired the existing metadata CLI to implemented functions; added boundary, fault-injection, randomized and concurrent tests; corrected README status. | Debugging, Regression Testing & Documentation |
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
