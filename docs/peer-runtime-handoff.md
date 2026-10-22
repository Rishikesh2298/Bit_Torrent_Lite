# Peer runtime: independent completion and team handoff

Prabhat's owner-thread orchestration is implemented in `peer/runtime.py`. It runs
against an injected backend; the default CLI does not pretend the unfinished
socket and tracker implementations work.

## Implemented responsibilities

- Validated strategy, window, RNG seed, free-rider and upload-worker controls.
  Project configuration always disables endgame duplicates.
- Metadata/store construction, separate output directories per peer, safe output
  filenames and protection against overwriting the seeder source.
- Bounded discovery/session buffering and scheduler event batches. Workers
  publish facts; only the owner thread mutates the coordinator.
- Lower-ID connection initiation, self/duplicate filtering, bounded connection
  attempts and cooldown retries while established transfers continue.
- Timer-driven request recovery with at most 100 ms loop waits, even in silence.
- Verified assembly, one COMPLETE notification, ongoing seeding and persistent
  free-rider mode after completion.
- JSON START, CONNECTED, TRACKER_ERROR, CONNECT_FAILED, REQUEST_EXPIRED, STATUS,
  COMPLETE and STOPPED records through an injected sink (stdout in the CLI).
- Status includes owned/total pieces, verified download bytes, acknowledged
  upload payload bytes, completion duration including assembly and local errors.
- Shutdown stops admission, closes sessions, discards unadmitted sessions,
  releases reservations, suppresses late events and joins/reaps workers within
  a deadline. Failures remain visible instead of claiming cleanup succeeded.

Existing pieces are not newly downloaded bytes. Duplicate/invalid responses do
not increase verified totals. Upload totals count only acknowledged full PIECE
payloads, not control headers or uncertain partial writes. Detailed per-frame
tracing belongs to the transport; run aggregation belongs to the experiment harness.

The unused `piece_manager.choking.ChokingManager` scaffold is removed.
That module exports `ProjectUploadPolicy`; the runtime constructs acknowledged
uploads through `SchedulerBridge.create_coordinator`. There is no alternate
unimplemented rate-only policy to select.

## CLI and backend construction

Existing flags are retained. New flags:

```text
--strategy {sequential,random,rarest-first}
--window {1,2,3,4}
--seed INTEGER
--free-rider
--upload-workers {0,2}
--shutdown-timeout SECONDS
--check-config
```

`--check-config` parses metadata and validates configuration without opening
sockets or creating output directories. Actual runtime construction, rather than
this check, hash-validates seeder bytes through the store adapter. Normal startup
without a backend returns exit code 2 and explains the missing integration.

Supply `main(argv, backend_factory=...)`. The factory receives parsed arguments,
metadata and file ID, and must not start resources until `start(runtime)`.
It uses the requested listener port, tracker URL and exact file ID.

| Backend method | Contract |
| --- | --- |
| `start(runtime)` | Launch listener/discovery workers and return promptly |
| `connect(Candidate)` | Queue an attempt; return whether accepted |
| `completed()` | Queue completion announce without blocking HTTP |
| `stop()` | Signal workers, best-effort stopped announce, unblock I/O |
| `join(timeout)` | Wait no longer than timeout; report whether all stopped |

Arbitrary blocking callbacks cannot be interrupted safely by Python. The backend
must honor these bounds and implement its own connect/handshake/frame deadlines.

## Worker handoff

Workers publish at most 128 same-file `Candidate(peer_id, ip, port)` records with
`publish_candidates`. False means full/stopping; retry a fresh snapshot later.
`publish_tracker_error` reports discovery failure without interrupting transfers.

Publish `Session` only after protocol version, file ID, remote identity and
initial-bitfield validation, and local initial BITFIELD enqueue. It contains:
connection ID, peer ID, remote bitfield, send/withdraw/close callbacks and the
exact `local_bitfield` snapshot queued during handshake.

The runtime reconciles pieces acquired since that local snapshot with HAVE.
Omitting the snapshot conservatively sends redundant HAVE for current pieces;
production adapters should supply it to avoid queue pressure.
`runtime.advertised_bitfield` is an immutable snapshot for worker reads.
Session rejection closes that transport. Connection IDs must never be reused.

Active callbacks call `runtime.bridge.received/sent/send_failed/disconnected`.
Pass the original message object to full-write acknowledgements. Withdrawal
must return True only when that exact frame was removed before writer start.
Started frames finish; partial-write failures close the connection. Close and
withdraw must be thread-safe and never call the coordinator synchronously.

## Runtime lifecycle

Call `run()` on the constructing thread. It always cleans up on stop/exception.
`request_stop()` is worker/signal-safe. Tests may use `start()/step()` with fake
time and a finally block calling `shutdown()`. Completion keeps serving until stop.

An assembly error pauses completion without repeated automatic retries. After
repairing storage, explicitly call `coordinator.resume_after_storage_error()`.
Discovery errors do not undo verified completion.

Shutdown attempts every closer, even when one fails. The CLI reports failure for
storage/recovery errors or incomplete cleanup. A permanently blocked provider
cannot be forcibly killed; deadline expiry is reported. `reap_shutdown()` can
harvest a later result without restarting work; historical diagnostics remain.

## Evidence and remaining boundaries

Verified on 20 October 2026: **495 passed, 0 failed, 0 skipped**, with warnings
treated as errors. Python compilation and CLI help checks passed. No commit or
push was made for this runtime work.

`tests/test_peer_runtime.py` uses real scheduler/upload/storage implementations
with simulated queues/backends. It covers strategies, windows, free rider after
completion, counters, retries, queue bounds, owner-thread rules, assembly/startup
failures, cancellation, blocked-provider shutdown, CLI and handshake reconciliation.

This is not real-network acceptance evidence. Remaining shared work is the
backend adapter, HTTP tracker/client, TCP connections, actual handshake validation
and worker deadlines, merged-interface review and real-process smoke tests.
Then run `post-merge-testing.md`.

For the report/viva: trace reservation, write acknowledgement, verification and
HAVE; distinguish stall, bad data and local storage failure; explain queued versus
started cancellation, assembly before COMPLETE and persistent free-rider mode.
Attach actual experiment measurements only after the real-process runs.
