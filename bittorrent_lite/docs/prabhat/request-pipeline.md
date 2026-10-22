# Part 2 request-pipeline integration

Part 3 now adds recovery policy and endgame cancellation to the coordinator.
See [recovery integration](recovery-policy.md) for the current behavior; the
Part 2 implementation and verification history below describe its baseline.

The independently supplied `bittorrent_lite.scheduling.request_pipeline.zip` is integrated as the top-level
`bittorrent_lite.scheduling.request_pipeline` package. Its standard-library API and JSON CLI remain usable
independently. The original archive is unchanged. The only change inside the
submitted package is validation of non-string CLI operation names, so malformed
JSON actions report their action number and exit 2 instead of raising TypeError.

## Project wiring

`bittorrent_lite.scheduling.Coordinator` uses `PipelineManager` as the authority
for reservations, outstanding counts, request identity, deadlines, verification,
connection permissions and owned-piece state. The old scheduler RequestManager
is retained for direct legacy imports; the coordinator no longer uses it.

- `SchedulerConfig` defaults to the project constants: four outstanding requests
  per connection, ten active connections, ten-second response timeout and
  five-second send-confirmation timeout. Window sizes 1 through 4 are supported.
- The coordinator chooses globally among requestable pieces, then selects a
  least-loaded source with rotating ties. Source availability includes choking
  neighbors. The standalone pipeline retains its round-robin `fill` API.
- Register only handshake-validated connections. Duplicate active provider IDs,
  reused connection IDs and excess connections are refused and recorded in
  `snapshot()['problems']`. New IDs may reconnect a disconnected provider.
- Interest must successfully enqueue before requesting. Remote choke or lost
  interest cancels unsent work, preserving sent and verifying requests.
- The integrated pipeline uses connection-scoped request IDs; standalone default
  IDs remain globally assigned. See [original-plan alignment](../integration/original-plan-alignment.md).
- Reservations are created before enqueue. Failed enqueues release their slots;
  no busy retry loop runs inside one scheduling call.
- RequestSent confirms the actual socket-write timestamp. Response timeouts
  start there, not at enqueue. Unconfirmed sends use the separate queue timeout.
  All supplied times use one monotonic clock; delayed confirmations may carry
  historical timestamps between enqueue and the current clock value.
- Responses match connection ID, request ID and piece index. Stale responses,
  rejections and send failures cannot clear replacement requests.
- Verification keeps its reservation and slot. Success records ownership and
  advertises HAVE only after storage accepts the bytes. Bad bytes release the
  request; an OSError pauses new reservations until explicitly resumed.
  Other already outstanding requests remain tracked while paused.
- `tick()` returns expired requests without scheduling replacements. The owner
  loop should call `schedule()` afterward when ready to refill.
- `snapshot()` preserves the earlier scheduler fields and adds cumulative
  `pipeline_counters`. `ready_to_assemble` means all pieces are verified;
  the caller must still assemble the output successfully.

The standalone library supports explicitly authorized duplicate requests with
at most two different providers and cancellation of the losing reservation.
The coordinator uses normal, nonduplicate fill only. Automatic endgame policy,
wire CANCEL for competing requests, backoff, upload service and choking policy
remain future work; this integration does not silently enable those features.

The SchedulerBridge still serializes worker events for the owner thread and
FileStoreAdapter still supplies verified ownership and disk validation. The
bridge event queue and scheduler diagnostic histories remain unbounded as in
Part 1. Neither a passing suite nor the local bridge test establishes a real
TCP swarm: peer_main and transport on this branch remain stubs.

## Commands

From the repository root, with Python 3.10+ and pytest installed:

```sh
python -m bittorrent_lite.scheduling.request_pipeline --input bittorrent_lite/scheduling/request_pipeline/example.json
python -m bittorrent_lite.examples.scheduler_demo
python -m pytest -q --basetemp=env/part2-tests
```

The demo explicitly uses `SchedulerConfig(request_window=1)` to retain the
sequential walkthrough. Ordinary Coordinator construction now uses four slots.

## Verification

Verified on 17 October 2026: **252 passed, 56 skipped**. This includes 47 new
Part 2 cases and all 205 previously passing cases. The 56 skips are pre-existing
legacy placeholders. The standalone CLI, sequential scheduler demo and
`git diff --check` also pass. On this device, verification used the bundled
Python runtime, existing `env/test-deps` pytest dependencies and a repository-local
temporary directory because the system `python` alias is unavailable.

`bittorrent_lite/tests/scheduling/test_request_pipeline.py` covers fair fill, per-source/global bounds,
exact identity, time validation, configurable deadline boundaries, competing
requests, ownership, permission loss, immutable snapshots, atomic invalid
inputs, CLI success/errors and 1,500 seeded randomized lifecycle operations
with independently recomputed count/state invariants.

`bittorrent_lite/tests/integration/test_pipeline_integration.py` covers six peers with 24 distinct requests,
ten peers with 40 requests, reconnect/provider limits, mixed sent/unsent
expiration, failed enqueue batches, choke during verification, late send
failure, storage pause/resume, rarest-first selection and an out-of-order
four-slot download through SchedulerBridge into real FileStore storage. That
transfer includes corrupt and duplicate responses and checks byte-for-byte
final reconstruction. Part 1 regression tests retain explicit one-slot settings.
