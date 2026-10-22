# Prabhat Ranjan Swain — individual execution plan

**Roll number:** 2405590  
**Project:** CS-30003 P8, BitTorrent-lite, CSE 33  
**Revision:** 22 September 2026 · **Work starts:** 23 September 2026 · **Deadline:** 24 October 2026  
**Ownership:** peer coordinator, piece state, rarest-first, request scheduling, recovery, and upload-slot policy

## 1. Your outcome and scope

Your work makes this statement true: “A peer chooses useful missing pieces, requests them without duplicate local reservations, recovers from failed attempts, and shares verified pieces fairly enough for the planned experiments.” You connect the modules, but each owner remains responsible for defects in their module.

Follow P01–P12. Start with in-memory tests and one outstanding request. Add real transport/storage, then rarest-first, then pipelining, then recovery and upload policy. Do not implement all concurrency and algorithms at once.

The [master guide](BitTorrent-Lite-Revised-Project-Guide.md) is the shared contract. No feature is claimed implemented here. Under the supplied course rules, you write and understand the coordinator, selection, and choking core; AI may explain designs, review/debug your work, or help with tests/documentation.

## 2. Overall workflow you coordinate

```text
Load validated metadata -> start listener -> discovery worker announces
            |
Candidate peers -> connect -> handshake -> bitfield -> interest/permission
            |
Choose missing piece -> reserve -> enqueue REQUEST -> wait for response
            |
PIECE -> match request -> verify/store -> HAVE -> refill request window
            |
All pieces HAVE -> assemble + final verification -> COMPLETE -> keep seeding
```

Failures branch back to a missing/requestable state or a visible local error. No source means stalled progress, not success or an infinite tight retry loop.

Primary files: `src/scheduler.py`, `src/peer.py`. Own scheduler/state tests, integration checklist, and report sections for selection, concurrency, recovery, and upload policy.

## 3. Why one coordinator simplifies your work

The coordinator is the single thread that mutates neighbor state, piece states, reservations, pending requests, interest/choke flags, contribution scores, and connection phases. Readers/writers publish events. The tracker worker makes HTTP calls separately. Storage operations are initially short synchronous calls from your coordinator.

You therefore do not need many locks around scheduler dictionaries. This does not remove all synchronization: Anik still protects transport closure and uses synchronized queues/Events. Do not rely on Python's GIL as proof that multi-step logic is safe.

The loop must check timers even when no network events arrive. Use bounded event waiting, proposed about 100 ms between timer checks. Avoid long sleeps, blocking tracker HTTP, or waiting indefinitely for an outgoing queue slot.

## 4. Data model to agree and implement

### Local metadata and piece state

- File ID and validated metadata from Rishikesh.
- N piece states: MISSING, REQUESTED, VERIFYING, HAVE.
- Local HAVE bitfield for advertisements.
- Map from piece index to its sole active download reservation.
- Verified byte count and completion status.

State transitions:

```text
MISSING -> REQUESTED -> VERIFYING -> HAVE
              |             |
     queue failure/timeout   bad length/hash
      reject/disconnect     |
              +-> MISSING <-+
```

Disk failure is a separate local error: stop or visibly fail the local download rather than repeatedly blaming providers. Do not advertise HAVE until storage succeeds. Completing every piece does not emit COMPLETE until assembly and final-file verification succeed.

### Neighbor record

Connection ID, remote peer ID, phase, bitfield, local interested, remote interested, local choking remote, remote choking local, pending download count, accepted upload count, verified bytes received in scoring interval, and any retry cooldown.

Initially both interest flags are false and both choke flags true. Keep flag names explicit; “choked” without direction is easy to misuse.

### Download request record

Key: `(connection_id, request_id)` in the local outgoing-request namespace. Fields: piece index, local send-token, queued time, optional sent time, queue deadline, optional response deadline.

Request ID increases per connection from 1; a retry gets a new ID. A reconnect gets a new connection ID. Maintain reservations before enqueueing, not after a response can already arrive.

### Upload job record

Key: `(connection_id, remote_request_id)` in a separate incoming-request namespace. Fields: piece index, send-token, queued/started/completed/canceled accounting, cancellation Event, and immutable bytes when loaded.

At most four accepted upload jobs per neighbor including its active response. Release count once when a job completes, is skipped/rejected, or the connection closes. Download requests and upload jobs with the same numeric ID are different records.

### Core invariants

1. At most one active outgoing request for a local missing piece across all neighbors.
2. A piece becomes HAVE only after Rishikesh reports successful verification/storage.
3. A neighbor contributes at most once to a piece's availability.
4. At most four queued/transmitted download requests per neighbor in final default mode.
5. Request cleanup removes only the matching connection/request/reservation.
6. Stale events cannot revive completed requests or alter a replacement connection.
7. Upload policy chooses at most two interested recipients, aside from already-started frames finishing after a slot change.

Make these observable in tests and debug assertions where useful.

## 5. Interfaces you consume

| Owner | Interface/result | Your action |
|---|---|---|
| Rishikesh | Valid metadata, read_piece, verify_and_store, assemble_file | Use exact lengths; distinguish corrupt data from local I/O failure |
| Debargha | PEERS_DISCOVERED and TRACKER_ERROR events | Connect eligible candidates; retain healthy transfers during tracker failure |
| Anik | CONNECTION_OPENED, FRAME_RECEIVED, FRAME_SENT, SEND_FAILED, CONNECTION_CLOSED | Apply semantic state transitions and request accounting |
| Anik | connect_peer, send_message queued/rejected, send-token cancellation, close/status | Submit bounded commands; never treat queued as delivered |

Anik's parser checks structure. You check session phase, remote identity using his helper, request matching, permissions, and state. The file store checks content integrity. This separation prevents duplicate/conflicting checks in three modules.

## 6. Piece selection explained precisely

### Start with sequential selection

Select the lowest eligible missing index with an available source. This is the learning baseline and one experiment strategy. Prove the request lifecycle before adding rarity.

### Final rarest-first

Recompute counts from distinct active neighbors' bitfields when scheduling. At this scale, scanning is simpler than maintaining incremental counts that can drift.

A candidate piece must be MISSING, unreserved, advertised by at least one active neighbor, and requestable from at least one advertising neighbor that has unchoked us, has room in its window, and is not in a temporary retry cooldown.

Count replication across all active neighbor advertisements, including neighbors currently choking us. Then choose the smallest positive count among requestable candidates. Break ties randomly with a recorded/test seed. Choose an eligible source, preferring lower pending load or using a documented random tie. Keep source selection the same across selection-strategy experiments.

Example bitfields:

```text
A: 1 1 0 1 0
B: 1 0 1 0 0
C: 0 1 1 0 1
   ---------
   2 2 2 1 1
```

If all pieces are missing, 3 and 4 are equally rare. If 3 is reserved, choose 4. If C chokes us, 4 has no current source, so choose 3 if A permits it. If neither rare piece is currently requestable, choose an eligible common piece; do not wait unnecessarily for a blocked rare piece.

This is neighborhood rarity, not global swarm knowledge. The tracker and experiment harness must not feed a global piece map into your scheduler.

### Interest

Local INTERESTED means the neighbor has at least one piece we still do not HAVE, even if it is temporarily reserved elsewhere. NOT_INTERESTED means none remains useful. Recompute when local HAVE or the remote bitfield changes. Send only on transitions. Remote interest controls whether that neighbor should be considered for our upload slots.

## 7. Request lifecycle and difficult event ordering

### Reservation to completion

1. Choose piece and source.
2. Allocate new request ID, set REQUESTED, and reserve piece.
3. Try enqueueing REQUEST with a send-token.
4. If submission fails, release that exact reservation and retry later.
5. FRAME_SENT supplies successful send time and starts the 10-second response deadline if the request still exists.
6. PIECE must match connection ID, request ID, piece index, expected length, and a live pending request.
7. Move to VERIFYING and call storage verification.
8. On success, mark HAVE, record verified bytes, clear request/reservation once, broadcast HAVE, and refill slots.
9. On invalid data, return to MISSING, record failure, and prefer another source.

A reader can enqueue PIECE before the writer's FRAME_SENT event is consumed. Since you reserve first, the matching response remains valid. Later FRAME_SENT for an already completed request is ignored. Never recreate the pending request from that late event.

### Pipelining

Start window=1. Final default window=4 per neighbor, counting both queued and transmitted requests. Refill when a request completes/fails. Do not reserve four copies of the same piece simply because four slots are free.

At 64 KiB per piece, four pending responses represent 256 KiB of requested data per connection, before buffer overhead. Respect connection and queue limits too.

### Timeout and CANCEL

Proposed queue deadline=5 seconds; response deadline=10 seconds after complete REQUEST write. If queued REQUEST expires, tell Anik to cancel its unsent job. If already started, allow REQUEST to finish and enqueue CANCEL after it. Release the reservation and make the piece eligible for another source with a new request ID.

If PIECE later arrives for the old attempt, discard it under the agreed version-1 late-response policy. It cannot satisfy or release the replacement request. This keeps the design simple; it may waste a valid late piece, which is an acceptable documented tradeoff.

### REJECT and CHOKE

REJECT affects only a matching pending request. Release it and avoid immediate retry loops; a one-second source cooldown after busy is a reasonable default. Reject reason unavailable indicates the advertised state or serving conditions changed; log it and seek alternatives.

Incoming CHOKE stops new requests to that neighbor. Cancel local unsent requests, but keep already transmitted ones pending until response/reject/deadline because responses already started may finish. Local CHOKE cancels queued uploads and sends REJECT choked for them; started frames may finish.

## 8. Upload handling and simplified policy

### Serving REQUEST

Check ACTIVE phase, request fields, permission, local HAVE, duplicate incoming ID, and accepted-work bound. Invalid protocol values cause connection failure; valid but unserviceable requests receive REJECT unavailable/busy/choked. Do not crash because a remote asks for something unavailable.

Read exact bytes through Rishikesh, enqueue a PIECE job through Anik, and record accepted-work accounting. Only completed writes count as completed upload payload. Failed/withdrawn jobs release accounting once.

For incoming duplicate REQUEST with the same ID and piece already pending, ignore it without creating another job. Reuse for a different piece or reuse of a retired/completed ID is a protocol error. Keep the highest observed incoming request ID and the bounded pending-upload map; new IDs must increase, but gaps are allowed. A repeated CANCEL for retired work is harmless. Never accidentally duplicate bytes because the same request event is processed twice.

### Final two-slot policy

Every five seconds, and when interest/connection changes leave a free slot:

- Consider interested active neighbors.
- While downloading, choose one contributor slot by verified bytes received in the preceding scoring interval.
- Break ties fairly; use a stable rotating tie order when all contributions are zero.
- Choose another distinct neighbor via a rotating opportunity slot.
- When complete, rotate both slots fairly; contribution-based ranking is not meaningful for a seeder that no longer downloads.
- If fewer than two neighbors are interested, serve the available ones.
- Send CHOKE/UNCHOKE only when permission changes.

Define the interval score exactly: bytes newly verified and stored from each neighbor since the previous five-second policy tick. Snapshot/reset at the tick; never credit rejected or duplicate bytes. Rotation state must survive ticks; always choosing the first dictionary entry is not fair rotation.

Free-rider mode has zero upload slots, even after completing its own download during that test. Otherwise it would stop being a free rider mid-experiment. It still downloads and reports status normally. A free rider can finish through seeder and rotating opportunities; do not claim a guaranteed block.

## 9. Ordered implementation tasks

### P01 — Freeze records, ownership, and invariants

**When:** 23 September.

Agree event names and queue submission results with Anik, metadata/errors with Rishikesh, and discovery-worker events with Debargha. Draw one piece lifecycle. Decide exact field names for all directional flags.

**Done when:** every mutable table has one owner and one-piece success/failure transitions are written down.

### P02 — Build pure state/selection tests

**When:** 24 September.

Create fake neighbor bitfields, fake clock, deterministic RNG, fake transport recording commands, and fake store returning success/failure. Test missing/owned/reserved exclusion and source permissions. Use sequential selection first.

**Done when:** you can explain every selected request without real sockets.

### P03 — Implement one-request lifecycle

**When:** 25 September.

Reserve before enqueue; handle queued/rejected results; accept matching PIECE; verify/store; produce HAVE. Add wrong request ID, wrong piece, corrupt result, and storage-error cases. Ensure duplicate events cannot count completion twice.

**Done when:** one piece can transition through success and failure using fake events.

### P04 — Integrate real components

**When:** 26–27 September.

Wire entry point, metadata load, listener startup, tracker worker, connect commands, handshake/bitfield session handling, temporary always-allow permission, and one-piece transfer. Keep the window at one. Let component owners fix their own boundary failures.

**Done when:** G1 passes with real storage/network and saved logs.

### P05 — Complete a small file and share pieces

**When:** 28 September–1 October.

Refill requests until all pieces HAVE. Call assembly and final verification; only then emit COMPLETE. Keep the process serving pieces. Update interest and HAVE correctly. Prove a downloader supplies another downloader in a controlled integration test.

**Done when:** small complete transfer and I02 sharing pass.

### P06 — Add rarest-first and experiment alternatives

**When:** 2–4 October.

Implement neighborhood rarity using current active bitfields. Retain sequential and random behind one simple strategy option. They share the same eligibility, reservation, source-selection, pipeline, and upload behavior, so experiments isolate strategy.

**Done when:** known fixtures choose eligible minimum-rarity pieces; duplicate HAVE and disconnect do not inflate counts.

### P07 — Add window four and scale

**When:** 5–7 October.

Increase outstanding requests per neighbor. Count queued plus sent work; prove a piece has one global local reservation. Work with Debargha on six downloaders and two-seeder variant. Inspect response-before-sent-event ordering.

**Done when:** window bounds and multi-peer correctness pass without unbounded queues.

### P08 — Add recovery and cancellation

**When:** 8–11 October.

Implement queue/response deadlines, reject handling, disconnect cleanup, source cooldown, old-event rejection, and cancellation. Test that old responses do not release new reservations. Reconcile Anik's transport-closed flags each timer tick if a saturated event queue prevented delivery of close notification.

**Done when:** recoverable peer failure completes survivors; lost final source reports a stall; timer tests use fake time where possible.

### P09 — Add upload slots and free rider

**When:** 12–15 October.

Replace development always-allow uploads with the policy above. Test all-zero contribution, new neighbor, fewer than two candidates, seeder mode, and completed free rider. Coordinate queued-upload cancellation with Anik.

**Done when:** permissions remain bounded, rotating neighbors get opportunities, and free-rider uploaded payload is zero in measured tests.

### P10 — Freeze behavior and review invariants

**When:** 16–17 October.

Run the full acceptance suite with all owners. Review every cleanup path: complete, hash failure, storage failure, reject, timeout, canceled unsent job, disconnect, and shutdown. Each path must leave counters and reservations consistent.

**Done when:** G4 passes or remaining requirement gaps are explicitly recorded, with no new optional feature work.

### P11 — Explain experiment results

**When:** 18–21 October.

Help Debargha interpret completion/rareness/free-rider results. Verify strategy comparisons differ only in the chosen strategy and controlled variable. Point to logs showing the algorithm's actual selections. Do not claim rarest-first wins every topology or that contribution policy is a perfect defense.

### P12 — Rehearse and submit

**When:** 22–24 October.

Explain the full process, trace a request, change window 4→1 or switch strategy live, and demonstrate the expected behavior. Submit your state/selection/policy report section and integration evidence. All members participate in final sign-off.

## 10. Your test matrix

| ID | Setup | Expected outcome |
|---|---|---|
| P-T01 | Known neighbor bitfields | Correct positive rarity counts |
| P-T02 | Owned/reserved/unavailable candidates | Excluded |
| P-T03 | Rarest source chokes us | Choose best currently requestable alternative |
| P-T04 | Equal rarity, fixed seed | Repeatable tie outcome in isolated test |
| P-T05 | Two providers, one missing piece | One reservation/request |
| P-T06 | Pipeline four, many pieces | Never five pending to one neighbor |
| P-T07 | Enqueue fails | Reservation released |
| P-T08 | PIECE before FRAME_SENT event | Accept once; later sent event ignored |
| P-T09 | Hash fails | No HAVE; piece eligible for retry |
| P-T10 | Storage fails | Local error, no corruption blame or HAVE |
| P-T11 | Timeout then replacement then old response | Replacement intact, stale bytes discarded |
| P-T12 | Duplicate HAVE | Availability unchanged after first |
| P-T13 | Reader/writer both close same connection | Cleanup once, no negative counts |
| P-T14 | New connection, stale old event | New state unaffected |
| P-T15 | Busy rejection | No tight resend loop |
| P-T16 | Incoming CHOKE with sent requests | No new requests; existing responses still handled |
| P-T17 | Three interested peers | At most two allowed; opportunities rotate |
| P-T18 | Seeder or zero contributors | Fair rotation, no permanent first-entry preference |
| P-T19 | Free rider completes | Still zero upload permissions |
| P-T20 | All pieces owned, final assembly fails | No COMPLETE event |
| P-T21 | No available source | Stall/wait status and periodic rediscovery |

Master S01–S05 and C01–C03 are your main evidence groups; system tests need all four members. Use a fake clock for timers and deterministic seeds for selection, then real separate processes for end-to-end proof.

## 11. Integration and blocked-work choices

| Waiting for | Keep doing |
|---|---|
| Rishikesh's store | Use a fake returning success/hash-error/I/O-error; complete state tests |
| Anik's socket layer | Use a fake queue returning accepted/rejected and inject events |
| Debargha's tracker | Feed documented candidate records in an isolated test |
| Full experiment harness | Prepare invariants and expected selection traces |

Replace fakes with real components at each gate; unit success is not proof of integrated success. Do not expand your ownership to rewrite the tracker or parser to avoid a handoff discussion.

## 12. Debugging and viva

Common symptoms:

- **No requests despite availability:** inspect interest, remote choke flag, pending window, and reservations.
- **Same piece requested twice:** reserve before enqueue and check coordinator-only ownership.
- **Never retries:** inspect cleanup after timeout/close/reject and blocked source cooldown.
- **Old response breaks new download:** match connection plus request ID, not only piece index.
- **Rarity grows impossibly:** count distinct neighbor bitfields; HAVE is idempotent.
- **Free rider uploads after completion:** mode was lost when switching to seeder state.
- **Tracker outage stalls data:** discovery HTTP was called synchronously in the coordinator.
- **Busy peer locks up scheduling:** queue submission or retry path blocks/spins.

| Viva question | Key explanation |
|---|---|
| What exactly is rarest? | Minimum advertised replication among eligible missing pieces in my connected neighborhood |
| Why ignore zero count? | Nobody currently advertises a source for that piece |
| Why reserve before sending? | Prevent another scheduling step choosing the same piece |
| Why pipeline? | Multiple outstanding requests reduce waiting between responses |
| Does pipelining mean multiple writers? | No; one writer serializes frames while several requests remain pending |
| Why request IDs if piece indices exist? | Different attempts for the same piece must be distinguished |
| Why can late data be ignored? | Its request no longer exists; policy favors simple safe state over salvaging every byte |
| Why a coordinator? | One owner serializes related state mutations |
| How do seeders choose upload slots? | Fair rotation; they no longer download for contribution ranking |
| Does choking replace TCP congestion control? | No; it is application upload permission |
| Can every failure recover? | Only if missing data remains available and reachable |
| What proves completion? | Final reconstructed size/hash verification, not merely request count or progress percentage |

Final checklist:

- [ ] Shared records and directional flags are documented.
- [ ] Reservation, request, and upload accounting obey invariants.
- [ ] Rarest-first and alternatives share eligibility rules.
- [ ] Pipeline, timeout, cancellation, rejection, and reconnect tests pass.
- [ ] Actual downloader-to-downloader sharing is demonstrated.
- [ ] Upload-slot policy and free-rider behavior are measured honestly.
- [ ] Completion includes final file verification and continued seeding.
- [ ] Six-peer/two-seeder/failure evidence is saved.
- [ ] State/policy report section, contribution, and AI-use records are complete.
- [ ] You can trace and modify the coordinator live in the viva.
