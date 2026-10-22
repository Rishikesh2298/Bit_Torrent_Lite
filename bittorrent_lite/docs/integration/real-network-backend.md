# Real network backend

The CLI now constructs `application.network_backend.NetworkBackend` by default.
The existing injectable factory remains supported for component tests. The
backend connects Debargha's `DiscoveryWorker`, Anik's `PeerNetwork`/framing,
Prabhat's owner-thread runtime and scheduler, and Rishikesh's verified store.
It does not replace their standalone implementations.

## Transport and ownership

`networking.runtime_connection.RuntimeConnection` subclasses the existing
`PeerConnection`. It uses that connection's handshake, reader lifecycle and
close/join behavior, with a scheduler-specific dispatcher and writer. The
legacy request manager/piece-handler policy is not invoked in this adapter;
all scheduling and upload decisions remain in the runtime coordinator.

- At most ten live connections, ten queued outbound attempts, 32 discovery
  events and 64 outgoing frames per connection. Full queues reject admission
  or enqueue; they do not block the owner thread indefinitely.
- Handshake validates version, file ID, safe remote identity, self-connections
  and the expected identity for an outbound tracker candidate. The first normal
  message must be a bitfield of exactly the metadata's piece count. Duplicate
  handshakes/initial bitfields and out-of-range piece indices close the session.
- Candidate dialing runs on a worker with a 0.5-second connect timeout.
  Incomplete handshake/bitfield exchanges expire after ten seconds. Partial
  frame reads retain bytes across socket polls and have a ten-second deadline.
- Socket callbacks buffer a bounded number of early events. `Session.activate`
  releases them only after the owner registers the bridge and initial bitfield.
  Connection IDs increase and are never reused within a backend instance.
- The writer acknowledges the original message object only after `sendall`
  succeeds. A failed or uncertain partial write closes the connection. Exact
  object withdrawal succeeds only before the writer removes it from the queue.
- Disconnects, receive events and write acknowledgements cross the bridge;
  worker threads do not mutate the scheduler. The backend reaps closed workers.

## Portable CLI usage

Follow the canonical [teammate runbook](TEAM-RUNBOOK.md) to install the core in a
fresh environment from source or a verified wheel. Source installation starts
in the repository root; tests and plotting are optional extras. Use that
environment's interpreter for `python` below. Run the tracker and peers in
separate terminals, using your own source and metadata paths:

```sh
python -m bittorrent_lite.storage.generate_metadata --file "input.bin" --output "input.torrent.json"
python -m bittorrent_lite.discovery.tracker_server --port 8000
python -m bittorrent_lite --peer-id seed-01 --port 9000 --metadata "input.torrent.json" --seeder --file "input.bin" --output-dir "downloads"
python -m bittorrent_lite --peer-id peer-01 --port 9001 --metadata "input.torrent.json" --output-dir "downloads"
```

Outputs go to `<output-dir>/<peer-id>/<metadata.filename>`; pieces remain under
that peer's `pieces/<file-id>/`. Each downloader receives the same metadata;
only seeders receive a source-file argument. Peer IDs use 1–32 letters, digits,
underscores or hyphens, matching the tracker contract. Network pieces must be
at most 64 KiB; the project file limit is 64 MiB.

Relative user paths resolve against the caller's current directory. The backend
has no fixed checkout path or username. For another machine, use its reachable
tracker address with `--tracker http://ADDRESS:8000`; run the tracker with
`--host 0.0.0.0` to accept remote clients. Peer listeners default to `0.0.0.0`;
`--host` selects a specific local IPv4 interface. Current acceptance evidence
is Windows localhost, not a cross-machine/LAN certification.

Peers continue seeding after completion. Ctrl+C requests owner-thread cleanup;
POSIX SIGTERM does as well. Windows process termination APIs forcibly stop the
process and do not run that cleanup. Process supervisors should pass an
initially absent `--stop-file PATH` and create that file to stop peers gracefully,
including on Windows. Stop a manually launched tracker with Ctrl+C after the
peers. Graceful cleanup closes sessions, sends a
best-effort stopped announce, and joins backend/upload workers within the
configured deadline. Failures remain visible in STOPPED records and exit codes.

## Existing experiment harness

`experiments/configs/base.json` now runs real peers. The launcher supplies
strategy/window/seed controls, the shared output root and a stop-file path. Its
historical `rarest` label maps to the CLI's `rarest-first`. The free-rider scenario
passes `--free-rider`. `stand_in.json` still explicitly runs synthetic peers.

The CLI preserves stdout JSON records and additionally writes the existing
`BTL_EVENT_LOG` format when configured: listening, verified pieces, progress,
completion, final byte counters and exit. The transport logs fully written
PIECE payloads. Previously owned pieces do not count as new downloads; final
completion requires assembly and whole-file verification. Unimplemented
aggregate metrics, such as total requests/retries/hash-failure counters, remain
undefined in the collector rather than being filled with invented zeroes.

## Validation

See the [end-to-end report](end-to-end-validation-2026-10-22.md) for exact test
counts, attempts, logs, output hashes and limits. The preserved older unit and
integration reports describe the state before the real backend was connected.
