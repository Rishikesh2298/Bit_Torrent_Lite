# AI Usage Documentation

**Project:** BitTorrent-Lite (P8)

**Course:** CS-30003 – Coding Assignment 1

## Part 1

Prabhat developed and supplied the standalone Part 1 code in
`prabhat_scheduler.zip`. An OpenAI assistant helped with planning and integration into the
existing project. Integration included adapters, correctness fixes, regression
tests, and verification. The original ZIP was preserved unchanged.

## Part 2

Prabhat supplied the independently developed `request_pipeline.zip`. The package
is retained as `request_pipeline` with its standalone API and CLI. An OpenAI assistant wired
it into the scheduler, fixed malformed CLI operation handling, and added
lifecycle, fault, randomized accounting, and storage/bridge integration tests.
The source ZIP was preserved unchanged. This work did not merge other branches
or implement the peer network loop.

## Part 3

Prabhat supplied the independently developed `recovery_policy_part3.zip`.
Its standalone library and CLI are preserved under `recovery_policy`.
An OpenAI assistant integrated policy decisions with scheduler lifecycle events,
added cancellation dispatch and capacity-failure handling, and wrote policy,
recovery and disk/bridge regression tests. The original archive is unchanged.

## Combined Part 4

Prabhat supplied `part4.zip` and `choking_policy.zip`. Their standalone packages
are retained as `upload_service` and `choking_policy`. An OpenAI assistant
connected bounded uploads, permission intents, transport acknowledgements and
verified contribution accounting to the scheduler, added validation fixes and
tests, and documented the integration. Both source archives remain unchanged.

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

- **15 September 2026 — Google Antigravity:** Architecture, interfaces, and scaffolding.
- **4 October 2026 — OpenAI assistant:** Initial piece-picker code and tests, repository bug fixes, metadata CLI wiring, and documentation.

The team is responsible for reviewing, understanding, and explaining the final
submission and checking its use of AI against course requirements.
