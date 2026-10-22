# Prabhat's original-plan alignment

The September 22 individual plan and revised master guide are the controlling
project requirements for this integration. Later standalone packages remain
usable independently; their optional extensions are not the project defaults.

## Implemented project behavior

- Default scheduler configuration disables endgame and limits copies to one.
  Explicit non-default recovery configurations can still exercise the standalone
  extension; do not enable it in original-plan runs.
- Request IDs start at one per connection. Every response and cleanup matches
  connection, request ID and piece. Connection IDs cannot be reused.
- Piece selection considers all requestable candidates before choosing a source.
  Rarest-first selects global neighborhood minimum rarity; sequential and random
  use the same eligibility and least-loaded, rotating source selection.
- Remote CHOKE cancels unsent requests, retaining sent/verifying requests until
  response, rejection, disconnect or deadline.
- Timer ticks expire requests and refill eligible windows, including after
  cooldown, without requiring incoming network events.
- Project upload policy uses exactly two slots and five-second intervals.
  Contribution scores are interval totals, reset at each timed selection.
  Stable rotating order resolves ties and assigns opportunities. Seeders rotate
  both slots. Membership changes fill vacancies without early full-slot rotation.
- Disabling uploads persists through seeder mode. ACKs still control confirmed
  permissions and slot reservations; queued permission is not permission applied.
- Invalid/reused remote request IDs close the session. Identical pending requests
  remain harmless. Valid unserviceable requests use choked/busy/unavailable.
- Local choke withdraws cancellable uploads and sends REJECT choked. Incoming
  CANCEL withdraws a queued response; a started frame may finish.
- Bridge event buffering defaults to 128 entries, never blocks indefinitely,
  and remembers a closed-session flag if enqueue fails. Draining reconciles
  cleanup even when the close event could not fit.
- `snapshot()['stalled']` identifies missing pieces with no advertised source.
  `finalize_download(path)` sets `complete` only after successful assembly and
  final verification. Failure reports a local storage error. Upload service
  remains open after completion.

## Transport handoff

Register only sessions that have passed handshake and initial-bitfield phase
validation. The socket owner supplies the existing send callback plus:

```python
bridge.register(
    connection_id, peer_id, send,
    withdraw=withdraw_exact_message,
    close=close_transport,
)
```

`withdraw(message)` must atomically return True only when that exact message was
removed before writer start. False means started/already sent or not withdrawable;
allow the whole frame to finish. The bridge uses the original message object as
its local send token. On queued REQUEST timeout it first attempts withdrawal;
otherwise it queues CANCEL after the REQUEST. `close(reason)` must safely close
the transport, unblock its workers and discard queued work. Both callbacks must
be thread-safe and must not synchronously call the coordinator.

Omitting these callbacks supports simple in-memory examples but cannot fulfill
physical socket closure/withdrawal requirements. A bounded FIFO writer preserves
REQUEST/CANCEL order. Partial writes require physical connection closure.

Owner-loop steps are drain, tick (which also schedules), then finalization if ready:

```python
bridge.drain(coordinator)
coordinator.tick()
state = coordinator.snapshot()
if state["ready_to_assemble"] and not state["complete"] and not state["storage_error"]:
    coordinator.finalize_download(output_path)
```

The [injected runtime](peer-runtime-handoff.md) now performs this owner loop,
completion logging, continued seeding and shutdown coordination. Its backend
owns listeners and discovery I/O. Storage errors require explicit resolution.

## Verification and remaining boundaries

Verified on 20 October 2026: **453 passed, 0 failed, 0 skipped**, with warnings
treated as errors. Source compilation and the scheduler demo also passed.

`tests/test_original_plan.py` checks original-plan reservation, IDs, CHOKE,
rarity/source ordering, timer recovery, policy intervals/rotation, free-rider
behavior, bounded-event failure, queued/started withdrawal, malformed/reused
requests, stalled state and assembly-before-completion.

The HTTP tracker, tracker client, TCP framing/connection threads, handshake
state machine and production backend adapter remain separate integration work.
No real-socket or six-peer acceptance gate is claimed. Tracker swarm indexing
and expiry, common protocol-header validation and the obsolete binary protocol
document belong to that shared/team handoff; this change does not rewrite them.
The standalone policy retains its original rolling-window/random policy.
The project subclass changes selection while reusing its ACK/reservation engine.
