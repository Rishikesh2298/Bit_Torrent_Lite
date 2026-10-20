# Post-merge dynamic end-to-end testing

Run after the team integrates the tracker, transport and peer runtime into main.
The current 453 passing tests validate modules and simulated transport boundaries;
they are not evidence of real-network acceptance. Do not merge automatically.

## Entry checks

- Record the merged revision, Python version, OS, configuration and seeds.
- Confirm real tracker and peer processes start, announce, handshake, exchange
  bitfields and use bounded queues, writer withdrawal and closure callbacks.
- Check tracker isolation by file ID and expiry at the original plan's boundary.
- Use a fresh run directory, fresh download stores and known fixture hashes.
- Give every run a deadline; save failures and stop only processes started by
  the test harness.

## Progressive acceptance

1. Transfer one real piece, then complete files across separate processes.
   Check exact bytes, size and SHA-256, including a short final piece and 64 MiB.
2. Prove redistribution: A downloads a piece, then B receives that piece from A
   as its only source. The harness must never supply bytes or choose peer pieces.
3. Run one seeder with six downloaders, then two seeders with six downloaders.
   Verify every expected output independently and retain per-peer logs.
4. Exercise sequential, random and rarest-first selection with identical fixed
   settings; compare windows one and four in separately labelled runs.
5. Test upload rotation with more than two interested peers, new arrivals,
   seeder mode and a free rider that remains disabled after completing.

## Fault and timing campaigns

- Fragment/coalesce TCP frames; delay writes and acknowledgements; apply queue
  backpressure. Check exact framing, bounded memory and responsiveness.
- Inject invalid headers, lengths, IDs, bitfields and corrupt payloads.
  Reject or close the affected connection without damaging healthy transfers.
- Cancel before writer start and during a frame; verify queued withdrawal,
  complete in-progress frames and harmless late responses.
- Kill a peer with work in flight; reconnect with a new connection ID.
  Verify reservation cleanup, recovery and stale-event rejection.
- Stop/restart the tracker during established transfers; verify continued data
  flow and eventual discovery recovery.
- Remove the final source for a missing piece; require visible stalled status
  and no false COMPLETE.
- Inject storage and final-assembly failure; require local errors and no false
  HAVE/COMPLETE. Exercise clean shutdown with reads/writes/queues occupied.
- Repeat stress runs with deterministic recorded seeds; monitor memory, worker
  counts, request windows and upload-job accounting for leaks or starvation.

## Evidence and fix loop

Preserve launch configuration, revision, seeds, timestamped logs, participant
statuses, output hashes, duration, uploaded/verified bytes and fault triggers.
Measure completion through final assembly verification. Record partial-write
failures separately from completed payload counts.

For each failure: capture a minimal reproducer, identify the responsible module,
add a regression test, fix it, rerun the affected scenario and the full suite.
Then repeat affected system comparisons. Never hide failures with skips.
Use at least three repetitions per experiment configuration; retain unsuccessful
runs and explain limitations rather than claiming a guaranteed strategy winner.
