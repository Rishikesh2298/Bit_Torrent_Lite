# Former placeholder tests

Latest independent-runtime validation: **495 passed, 0 failed, 0 skipped**,
with warnings treated as errors. See [runtime handoff](peer-runtime-handoff.md)
for the added lifecycle coverage and remaining real-network dependencies.

Earlier original-plan alignment verification: **453 passed, 0 failed, 0 skipped**
with warnings treated as errors. See [alignment review](original-plan-alignment.md)
for changed contracts, new regression coverage and remaining network boundaries.
The expanded-audit results below describe the preceding implementation.

Validation on 20 October 2026 after the expanded audit: **437 passed, 0 failed, 0 skipped**.
All 56 previous skipped placeholders now contain executable assertions against
project code. No skip or expected-failure markers hide missing implementations.

| Area | Former placeholders | Passing | Failing |
| --- | ---: | ---: | ---: |
| File management | 19 | 19 | 0 |
| Message objects | 15 | 15 | 0 |
| Piece and request management | 15 | 15 | 0 |
| Tracker state | 7 | 7 | 0 |

File tests exercise chunking, hashing, metadata persistence and deterministic IDs,
assembly, and preservation of output when pieces are missing or corrupt.
Piece tests use the integrated picker and request pipeline, including availability,
reservations, fairness, slot limits, completion and timeouts.
Message tests exercise JSON header and payload round trips. They follow the current
whole-piece request API and JSON-list bitfield format, replacing outdated scaffold
assumptions about block requests and binary bit packing.

The tests revealed that incoming handshakes accepted unsupported protocol versions.
Deserialization now rejects unsupported versions and non-integer values, including
booleans. The handshake regression test passes.

The initial audit found seven `NotImplementedError` failures in
`bittorrent_lite/tracker/tracker_state.py`. They covered registration, self-exclusion,
expiry, heartbeat refresh, removal, upsert/counting and concurrent access.
The expiry tests inject a deterministic clock; the concurrency test uses real
threads. All six tracker-state methods are now implemented locally, using a lock
for every access and monotonic timestamps for expiry. Peer lists return detached
records; registration refreshes the endpoint and heartbeat, unknown heartbeats
raise `KeyError`, and repeated removal is harmless. Expiry removes peers strictly
older than the timeout. No other branch was merged.

All seven original tracker tests now pass. Four additional regression tests cover
unknown heartbeats, reannouncement and exact expiry boundaries, snapshot isolation,
and concurrent registration/heartbeat/listing/cleanup/removal operations.

The scheduler/upload/choking integration is available, but TCP framing, the
tracker HTTP server and the peer network loop are still unfinished on this branch. These
results do not verify end-to-end network transfers.

Run from the repository root with the project's test dependencies installed:

```powershell
python -m pytest -q --tb=short --basetemp=env/test-audit-temp
```

The full-suite command exits successfully. No changes were staged, committed or
pushed during this audit or the tracker fix.

## Expanded audit

The full suite passed with `-W error`, so emitted warnings fail validation too.
Compilation checks passed for all six source/example directories, and
`python -m examples.scheduler_demo` completed successfully.
The suite includes unit tests, disk/bridge integration, command-line subprocess
checks, seeded randomized lifecycle checks, worker cancellation and thread tests.

New regressions reproduced 11 failing cases across three defects before fixes:

| Defect | Fix | Regression cases |
| --- | --- | ---: |
| Invalid shutdown `wait` partially closed the controller and policy before the service rejected it | Validate before changing shutdown state | 1 |
| Invalid dispatch budgets queued permission messages before raising an error | Validate before policy decisions, cancellation or sends | 4 |
| Invalid tracker expiry timeouts could remove members, silently disable cleanup or raise an inconsistent type error | Reject negative, boolean, nonnumeric and nonfinite timeouts before accessing membership | 6 |

All 11 cases pass after the fixes. Two additional transfer variants exercise two
upload worker threads, including a 262,148-byte binary file with 65,536-byte pieces
and a short final piece. They check reconstructed file bytes, successful-send byte
accounting, verified contributions and release of active upload jobs.
These use the real scheduler, storage, upload service and message objects with
in-memory transport queues, not TCP sockets.

The first large-file test attempt also exposed a test-harness issue: automatic
parameter names included the entire binary payload. Explicit short test IDs fixed
the fixture setup errors; this was not a product defect.

Still unfinished and outside the passing network claims: tracker HTTP server,
tracker client, TCP framing, peer connection threads and peer main loop.
The legacy `piece_manager/choking.py` scaffold is also unfinished; the integrated
implementation is `choking_policy` through `scheduler/uploads.py`.
