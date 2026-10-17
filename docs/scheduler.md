# Current integration status

Part 2 now backs the coordinator with `request_pipeline.PipelineManager`.
The default window is four; the one-request example opts into window one.
See [Part 2 integration](request-pipeline.md) for current behavior, limits and
verification. Part 1 history and interface background follow below.

# Integrated Prabhat scheduler (Part 1)

Imported from the user-supplied `prabhat_scheduler.zip` on 11 October 2026.
The core now lives in `bittorrent_lite.scheduler`. The original archive is
preserved outside the repository. Integration fixes and tests are recorded in
`AI-USE.md`; the archive is the reference for the submitted implementation.

Standalone piece selection and request tracking. Part 1 used one outstanding request per connection; Part 2 defaults to four. Python 3.10+, standard library only. No sockets, no tracker, no upload policy.

## Run the example

```
python -m examples.scheduler_demo
```

It registers one fake neighbor, sends bitfield and unchoke, enqueues a request, confirms the send, delivers valid bytes, verifies and stores the piece, advertises HAVE and enqueues the next request.

## Layout

| File | Contents |
|---|---|
| `scheduler/models.py` | `PieceState`, `NeighborState`, `PendingRequest`, `SchedulerConfig` |
| `scheduler/interfaces.py` | `Transport`, `PieceStore`, `Clock` protocols |
| `scheduler/piece_picker.py` | `PiecePicker`, rarest-first with random tie break |
| `scheduler/request_manager.py` | Legacy Part 1 `RequestManager`, retained for direct callers |
| `scheduler/events.py` | event dataclasses and the `ExpiredRequest` tick outcome |
| `scheduler/coordinator.py` | `Coordinator`, the only object the network layer talks to |
| `examples/` | fake transport, in-memory store, manual clock, demo |
| `bittorrent_lite/scheduler/adapters.py` | real FileStore adapter, protocol bridge, monotonic clock |

All `scheduler/` paths above are relative to `bittorrent_lite/`.
`bittorrent_lite.piece_manager.request_manager` now re-exports the implemented
RequestManager. Its former unimplemented piece-only API is superseded by this
connection/request/piece API. The existing legacy picker remains compatible
with its callers; the coordinator uses the submitted scheduler picker.
PieceState is shared with `bittorrent_lite.types`. PendingRequest is an internal
scheduler record; the older shared PendingRequest type remains unchanged.

## Public interfaces

Coordinator: `handle_event(event)`, `schedule()`, `tick()`, `snapshot()`, plus `resume_after_storage_error()`.
`handle_event` runs `schedule()` after every event, so callers rarely need to call it directly. `tick()` does not call `schedule()`.

PiecePicker: `update_bitfield`, `record_have`, `remove_connection`, `pick_piece`, `availability_snapshot`.

Legacy RequestManager (not used by Coordinator): `reserve`, `mark_sent`, `complete`, `cancel`, `cancel_connection`, `get_expired`, `get_unsent_expired`, `reserved_pieces`, `outstanding_count`, `can_request`. Extras: `get`, `mark_verifying`, `all_pending`.
`reserve` returns `None` when the piece is already reserved or the connection slot is full.

## Event fields

| Event | Fields |
|---|---|
| `ConnectionReady` | connection_id, peer_id |
| `BitfieldReceived` | connection_id, bitfield |
| `HaveReceived` | connection_id, piece_index |
| `ChokeReceived`, `UnchokeReceived` | connection_id |
| `PeerInterestChanged` | connection_id, interested |
| `RequestSent` | connection_id, request_id, piece_index, sent_at |
| `RequestSendFailed` | connection_id, request_id, piece_index, reason |
| `PieceReceived` | connection_id, request_id, piece_index, data |
| `RejectReceived` | connection_id, request_id, piece_index |
| `Disconnected` | connection_id |

A request is identified by connection_id + request_id + piece_index. Request ids start at 1, increase for the scheduler's lifetime and are never reused. Connection ids are never reused either; a reconnect needs a new one.

## Who owns which state

| State | Owner |
|---|---|
| Per-piece state (`MISSING/REQUESTED/VERIFYING/HAVE`), local bitfield, neighbor flags | `Coordinator` |
| Per-connection bitfield copies and availability counts | `PiecePicker` |
| Pending requests, piece reservations, per-connection outstanding counts, deadlines | `PipelineManager` |
| Verified data on disk | the team's piece store |
| Queued outgoing messages and sockets | the team's networking layer |

A request stays in the `PipelineManager` while its piece is being verified, so the piece stays reserved and the slot stays occupied until the store answers.

## Behaviour worth knowing

- Reserve happens before `send_request`; if the transport refuses, the reservation is released and the piece goes back to `MISSING`.
- The response deadline starts at `RequestSent`, not at enqueue. A request that is never confirmed is released by `tick()` after `send_confirm_timeout` (reported as `send_unconfirmed`).
- A `PieceReceived` that arrives before `RequestSent` is accepted. The late `RequestSent` is ignored because the request no longer exists.
- Unsolicited, stale or mismatched `PieceReceived` events are ignored.
- Invalid data: piece returns to `MISSING`, reservation released, failure recorded in `snapshot()["invalid_pieces"]`.
- `OSError` from the store: piece is not marked owned, a storage error is recorded and new requests are paused until `resume_after_storage_error()`.
- `ChokeReceived` releases the connection's unanswered requests (the peer drops them). `Disconnected` releases everything for the connection and removes its availability.
- Rarity counts every active neighbor, including ones choking us.
- Failed interest enqueue blocks new requests. Bitfields accept only zero/one
  entries; malformed updates preserve the previous neighbor snapshot.
- `snapshot()["ready_to_assemble"]` means all pieces are verified and owned.
  It does not claim final assembly has succeeded; the misleading `complete`
  field from the standalone version has been removed.
- `tick()` releases expired requests and returns them. The piece is eligible again on the next `schedule()` with no backoff; recovery policy remains separate work.

## Hooking up the team's code

Anik's networking callbacks should only build an event and put it in a thread-safe `queue.Queue`. One coordinator thread reads that queue and calls `handle_event`, and also calls `tick()` on a timer.

| Networking callback | Event |
|---|---|
| handshake validated (file identity checked) | `ConnectionReady` |
| BITFIELD, HAVE, CHOKE, UNCHOKE, INTERESTED, NOT_INTERESTED, PIECE, REJECT received | matching event |
| outgoing request written to the socket | `RequestSent` with the monotonic time |
| outgoing request could not be written | `RequestSendFailed` |
| socket closed or errored | `Disconnected` |

The team's `Transport` implementation must queue messages and return `True`/`False`, then later publish `RequestSent` or `RequestSendFailed` for each request.

The team's storage must provide `verified_bitfield()` (only verified pieces, one bool per piece) and `verify_and_store(index, data)` (check size and hash, write, return `True`; return `False` for bad data; raise `OSError` for disk problems). The `Clock` must be monotonic.

## Remaining integration and policy work

Real sockets, tracker discovery, upload/choking policy, retry and backoff, provider reassignment, and endgame mode remain outside this scheduler integration.

## Project adapter usage

```python
from bittorrent_lite.scheduler import Coordinator
from bittorrent_lite.scheduler.adapters import FileStoreAdapter, SchedulerBridge

bridge = SchedulerBridge()
scheduler = Coordinator(metadata.num_pieces, bridge, FileStoreAdapter(store), bridge.clock)
# After the network layer validates the handshake:
bridge.register(1, remote_peer_id, connection.send)
# Receiver thread: bridge.received(1, message)
# Sender thread, AFTER successful write: bridge.sent(1, message)
# Send failure: bridge.send_failed(1, message, reason)
# Disconnect: bridge.disconnected(1)
# Owner thread, periodically:
bridge.drain(scheduler)
expired = scheduler.tick()
scheduler.schedule()
```

Register connections and run the coordinator only on its owner thread. Worker
threads publish events through the bridge. Incoming uploads and handshake
validation belong to their respective networking handlers, not `received()`.
The transport enqueue contract is nonblocking: False or an OSError/queue.Full
means refusal; None or True means queued. The bridge does not report queued
requests as sent. The current branch's PeerConnection and peer_main remain
stubs; this adapter is their integration boundary, not a working TCP service.

FileStoreAdapter uses `file_manager.file_store.FileStore`, validates seed files,
and rechecks cached pieces before publishing initial ownership. Construct it
before other threads begin writing the store. Disk verification is synchronous
in this baseline. Final assembly is the caller's responsibility.

The default request window is now four (use SchedulerConfig(request_window=1) for the baseline); response and send-confirmation timeouts
come from project config (10 and 5 seconds). `tick()` releases expired requests
but does not schedule replacements. Other handled events trigger scheduling;
rejected/corrupt pieces can therefore be immediately selected again. Backoff,
provider penalties, transport-queue cancellation, and bounded upload work remain
future work. The bridge's inbound event queue is currently unbounded.

## Verification

Run `python -m pytest` from the repository root. Scheduler-specific regression
and integration cases are in `tests/test_scheduler_integration.py`, including
real disk storage and final reconstruction, fake-clock deadlines, fault paths,
six-neighbor reservation behavior, and worker-to-owner event delivery.
These do not constitute a real TCP swarm test.

Verified on 11 October 2026: **205 passed, 56 skipped**, including 30 new
scheduler regression/integration cases and package-import checks. The runnable
demo, Python compilation, and `git diff --check` also passed. The 56 skips are
existing legacy placeholders; they are not evidence of implemented features.
