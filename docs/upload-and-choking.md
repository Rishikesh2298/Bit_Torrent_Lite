# Combined Part 4: uploads and choking policy

The project now uses `ProjectUploadPolicy`: five-second interval scores and stable
rotating choices. The standalone `choking_policy.Policy` keeps its separate
rolling-window/random contract. See [original-plan alignment](original-plan-alignment.md)
for required transport withdrawal/closure hooks and current runtime boundaries.

This integration combines `part4.zip` (the `upload_service` library) and
`choking_policy.zip` (the permission-policy library originally planned as Part 5).
They remain separate importable packages but form one reviewable Part 4 change.
The original archives are unchanged. The standalone packaging manifest is retained
as `docs/upload-service-standalone.toml` for reference; it is not the repository's
build configuration.

## Connecting the services

Use the existing FileStore and scheduler bridge on their owner thread:

```python
from bittorrent_lite.scheduler.adapters import SchedulerBridge
from upload_service import UploadConfig
from choking_policy import Config as ChokingConfig

bridge = SchedulerBridge()
coordinator = bridge.create_coordinator(
    store,
    upload_config=UploadConfig(workers=2),
    choking_config=ChokingConfig(max_slots=2),
)
# After validating the handshake:
bridge.register(connection_id, peer_id, connection.send,
                withdraw=withdraw_exact_message, close=close_transport)
# Receiver callback:
bridge.received(connection_id, message)
# Sender callback, only after the entire frame is written:
bridge.sent(connection_id, message)
# Owner loop:
bridge.drain(coordinator)
coordinator.tick()
```

Direct `Coordinator(...)` construction remains download-only unless an
`UploadController` is passed through `uploads=`. The factory enables both upload
and download services. Requests and cancellations arriving through the bridge
are routed to the upload controller; received PIECE messages remain download
responses. Remote CHOKE controls downloads, independently of local upload policy.

## Permissions and transport acknowledgements

The policy reserves two slots by default: one regular contributor and one
optimistic peer. A pending UNCHOKE reserves its slot, but grants no local upload
admission until `bridge.sent` confirms the write. Pending CHOKE retains its policy
slot until acknowledged. Local admission stops immediately when permission is
no longer desired, interest disappears, or uploads are disabled.

The transport must pass the **same message object** back to `bridge.sent` or
`bridge.send_failed`. Reconstructed objects and callbacks from another connection
are ignored. Successful enqueue is not successful delivery. False/OSError/queue.Full
from enqueue means the message was not queued. Report `send_failed` only when
failure is known; partial/uncertain writes require closing the connection and
calling `bridge.disconnected`. Unknown outcomes must not be acknowledged as a
successful allow or deny.

Only verified, newly accepted download pieces add contribution bytes. Corrupt,
stale and duplicate responses add none. Once all local pieces are owned, the
controller switches to seeder fairness. Disable uploads with
`coordinator.uploads.set_upload_enabled(False)`; download operation continues.

## Bounded upload lifecycle

The service defaults to 40 jobs globally, four per connection, 40 output slots,
and 8 MiB each for logical read/output reservations. Configuration supports zero
or two read workers; workers run only source reads and verification. The owner
thread alone mutates service, policy and controller state.

The FileStore source adapter opens fresh bounded streams and avoids mutating
FileStore's owner-thread bitfield from workers. Downloaded pieces are atomically
replaced by FileStore. Seed files must remain immutable while serving. Every
output passes exact length and SHA-256 verification, including the final short
piece. Missing, oversized or corrupt data generates a rejection, never PIECE.

Service peer IDs are connection-ID strings; policy IDs retain the original peer
identity. This accommodates the standalone service's 64-character peer limit
without truncating the policy's 128-character peer identities. Each connection's
wire request IDs must be positive and strictly increasing. Exact active repeats
are ignored, and old/reused IDs are rejected without keeping unbounded history.

Polling a service output hands it to the transport but retains its reservations.
Sent-byte totals increase only after a successful full PIECE write. Failed sends
release reservations without credit. Delivered rejection records are likewise
released after their write result. The controller keeps bounded active-job and
pending-message mappings, with diagnostic history limited to 128 entries.

## Cancellation, disconnect and shutdown

CANCEL matches connection, request and piece exactly. Queued/ready work is
released immediately. A cancelled read retains its reservations until its worker
returns, then suppresses its output. Delivered data cannot be recalled: its
reservation remains until a transport result or disconnect. Permission loss
cancels work that is still cancellable; it does not pretend to retract a frame
already handed to the transport.

Disconnect removes peer permission state, invalidates old callbacks, releases
delivered records as failed, and cancels remaining reads/jobs. Reconnect with a
new connection ID cannot inherit an old permission acknowledgement.

Call `coordinator.uploads.shutdown(wait=True)` on the owner thread to stop jobs.
Permission shutdown may still require ticks and write acknowledgements for CHOKE,
or confirmed disconnects. An unresolved UNCHOKE keeps policy shutdown pending.
`wait=False` returns without waiting for running reads; later tick or shutdown
reaps them. Python cannot forcibly stop a blocked custom source callable.

## Integration fixes to supplied packages

- Upload manifest construction reports invalid non-iterables as ManifestError.
- MemorySource rejects boolean keys that otherwise alias integer indices.
- Upload shutdown requires a real boolean `wait` value.
- Choking-policy contribution-window configuration requires an integer.
- Choking-policy interest changes are rejected while shutting down.

The rest of the integration is in scheduler adapters, events, coordinator and
`bittorrent_lite/scheduler/uploads.py`. Existing package APIs remain available.

## Validation and limits

Pre-alignment full-suite audit on 20 October 2026: **437 passed, 0 failed, 0 skipped**.
All former placeholders execute; tracker-state implementation resolves the seven
failures from the initial audit. See [test audit](test-audit.md) for scope and remaining gaps.

Historical integration validation on 19 October 2026: **364 passed and 56 existing skips**. The final
diff check also passed. Coverage includes source integrity, admission and
byte limits, fair dispatch, two-worker cancellation/shutdown, strict ownership,
permission reservation/ACK races, optimistic selection, bounded diagnostics,
CLI behavior, stale callbacks, failed writes, and a complete simulated seeder-to-
downloader transfer through both bridges with byte-for-byte file reconstruction.

Run `python -m pytest -q --basetemp=env/part4-tests` from the repository root.
The standalone upload example is
`python -m upload_service demo --directory ./env/upload-demo-new`; use an empty
or nonexistent directory. `python -m choking_policy` accepts JSON lines on stdin.

The peer network loop is still a stub on this branch. These tests exercise local
bridges and real storage, not a TCP swarm. The existing bridge event queue and
external transport queue are not bounded by upload-service limits; the network
integration must enforce its own backpressure and lifecycle callbacks.
