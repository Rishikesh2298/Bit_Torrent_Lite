# BitTorrent-lite: audited project plan and team guide

CS-30003 · Coding Assignment 1 · P8 · Path A · CSE 33  
Working schedule: 23 September–24 October 2026

**Expanded revision: 22 September 2026.** Read sections 1–20 for the architecture and reasoning; sections 21–30 turn that foundation into an execution handbook. No implementation progress is assumed. Proposed defaults are project choices, not claims about the instructor's exact rubric.

Companion plans, intended to be shared with their respective members:

- [Rishikesh — file, metadata, integrity, and report](01-Rishikesh-Individual-Plan.md)
- [Debargha — tracker, discovery, and experiments](02-Debargha-Individual-Plan.md)
- [Anik — TCP, framing, and peer protocol](03-Anik-Individual-Plan.md)
- [Prabhat — coordinator, selection, and scheduling](04-Prabhat-Individual-Plan.md)

Each companion repeats its essential contracts so its owner can start independently. This master guide is the shared source of truth. Update affected companion contracts whenever the team changes it. The September 22 refinements below resolve event ordering and shutdown details without introducing new frameworks.

This guide revises the supplied plan. It is a design proposal, not an implementation or a claim that tests have passed. The repository could not be accessed during this review. Course requirements below come from your pasted text; the original assignment sheet was not provided. Your team should cross-check it before freezing the protocol, especially whole-piece requests, choking requirements, and how the minimum peer count is defined.

## 1. The project in plain language

Build a small file-sharing swarm. A tracker tells participants how to find one another. A seeder starts with the complete file. Other peers download pieces, verify them, and immediately make verified pieces available to others. Every downloader is also an uploader. The tracker carries discovery information, never file contents.

The final demonstration should prove three things: correct reconstruction, actual downloader-to-downloader transfers, and continued progress after a recoverable peer failure.

Use one program for both seeders and downloaders. A seeder is a peer that initially owns every piece. A completed downloader becomes a seeder and stays online until explicitly stopped.

## 2. Audit: what to retain and what to change

| Finding in the original plan | Why it matters | Revised decision |
|---|---|---|
| Python, sockets, hashing, and modular ownership | Appropriate for the learning objective | Keep them |
| Integration begins mainly in week 4 | Interface mistakes may survive for three weeks | Transfer one verified piece by 27 September |
| Rarest-first and pipelining are requirements but have lower priority elsewhere | The team could finish a demo that misses the assignment | Both are final acceptance requirements |
| Choking is described as optional, yet the free-rider experiment expects it | The experiment would have no defined mechanism to evaluate | Include a small upload-slot policy before this experiment |
| Tracker stores available pieces | Duplicates peer bitfields and introduces stale state | Tracker stores membership only |
| Seeder starts before tracker in one workflow | Startup behavior is unclear | Start tracker first; retries handle temporary unavailability |
| Request examples introduce offset and length without a block design | Adds incomplete-piece assembly, tracking, and cancellation complexity | Request entire 64 KiB pieces in version 1 |
| Message meanings are listed but wire format and failures are not fixed | Independent modules will disagree | Freeze a short protocol document first |
| State ownership is spread across networking and piece management | Causes duplicate requests and race conditions | One coordinator owns scheduling state |
| Network and scheduling members have the heaviest workload | Can make them integration bottlenecks | Give storage owner correctness/report work and tracker owner process harness/experiments |
| DHT, endgame, super-seeding, and a large library list appear | Increases implementation and viva burden | Exclude these extensions from this submission plan |
| Performance metrics lack precise definitions | Graphs may compare different quantities | Define population, timing, repetitions, and byte counters before experiments |

The original plan has a good conceptual foundation. Its main problem is unresolved engineering decisions, rather than insufficient features.

## 3. Scope and technology choices

### Final required scope

- One file per swarm; immutable metadata distributed manually before startup.
- IPv4 and TCP for peer-to-peer traffic.
- HTTP tracker with registration, refresh, discovery, and expiry.
- Custom, documented handshake and piece-exchange protocol.
- Per-piece SHA-256 verification and final-file verification.
- Neighborhood rarest-first, request pipelining, cancellation, and retries.
- One process per peer with its own files and state.
- Demonstrate six downloading peers plus one seeder; repeat with two seeders. This exceeds six total participants and avoids an ambiguous minimum.
- Simplified choking and a free-rider experiment.
- Terminal status, reproducible tests, experiment CSVs, graphs, and report.

### Exclude from the planned submission

DHT, magnet links, NAT traversal, internet deployment, encryption, multi-file torrents, compression, databases, web dashboards, endgame duplicate requests, super-seeding, automatic crash-resume, and compatibility with commercial BitTorrent clients.

### Small technology stack

| Technology | Use | What to explain in the viva |
|---|---|---|
| Python 3, same version for everyone | Entire project | Readability and standard-library support |
| `socket` | Peer TCP connections | Bind, listen, accept, connect, send, receive |
| `threading`, `queue` | Concurrent I/O and event delivery | Process versus thread, races, state ownership |
| `http.server`, `urllib.request` | HTTP transport for tracker requests | HTTP runs over TCP; team writes membership logic |
| `json`, `struct` | Metadata and framed messages | Text fields, binary payloads, byte lengths, network byte order |
| `hashlib` | SHA-256 | Integrity verification, not encryption or sender authentication |
| `pathlib`, `argparse`, `logging`, `time`, `csv` | Files, CLI, logs, timing, results | Be able to explain the functions actually used |
| `pytest` | Automated tests | Inputs, expected outcomes, regression tests |
| `matplotlib` | Final graphs | Meaning and units of each plotted value |
| Git/GitHub | Collaboration | Commits, branches, review, merges |

Skip pandas and NumPy unless later analysis truly needs them. CSV and basic Python statistics are sufficient for the proposed experiments. Do not mix asyncio with threading.

The standard HTTP server supplies HTTP parsing, not tracker functionality. Your team implements membership, expiry, validation, and peer-list responses. It is suitable here as a local teaching server; Python does not recommend it for production hosting. See the [official HTTP server documentation](https://docs.python.org/3/library/http.server.html).

## 4. Architecture and dependencies

```text
                HTTP announce / peer lists
         +-------------------------------------+
         |                                     |
      TRACKER                              PEER PROCESS
   membership table                     +-------------------+
   no file contents                     | Peer coordinator  |
                                        | and scheduler     |
                                        +----+----------+---+
                                             |          |
                                  read/write |          | send commands
                                             v          v
                                        File store   Networking
                                        metadata     TCP + framing
                                        SHA-256          |
                                                        | pieces
                                                        v
                                                  OTHER PEERS
```

Internal dependency rules:

```text
peer.py: creates and connects the components
tracker_client.py -> HTTP tracker -> membership dictionary
network.py -> protocol.py -> socket I/O
network events -> scheduler.py -> file_store.py
scheduler commands -> network.py -> remote peer
```

The file store knows nothing about sockets. The tracker knows nothing about piece selection. The protocol parser does not choose pieces. The scheduler does not parse raw TCP bytes. The entry point wires these modules together.

Suggested structure:

```text
Bit_Torrent_Lite/
  src/
    peer.py
    file_store.py
    tracker.py
    tracker_client.py
    protocol.py
    network.py
    scheduler.py
  tests/
  experiments/
  docs/
    protocol.md
    architecture.md
    test-plan.md
    experiment-method.md
    contribution.md
  README.md
  AI-USE.md
  requirements.txt
  .gitignore
```

Seven main source files are enough initially. Split a file when its responsibilities become hard to understand, not to make the tree look sophisticated. Keep generated downloads, piece directories, and bulky run logs out of Git.

## 5. Team responsibilities and individual workflows

| Member | Primary ownership | Additional ownership | Main handoff |
|---|---|---|---|
| Rishikesh Kumar — 2405600 | Metadata and file storage | Correctness fixtures, reconstruction evidence, report assembly | Metadata contract and verified-piece storage to Prabhat |
| Debargha Bhadra — 2405575 | Tracker and discovery client | Multi-process launch harness, experiment CSV collection and plots | Validated peer endpoints to Anik |
| Anik Dey — 2405558 | Framing, protocol encoding, sockets, connection lifecycle | Protocol document and malformed-message tests | Validated message events to Prabhat |
| Prabhat Ranjan Swain — 2405590 | Coordinator, selection, requests, upload policy | Scheduling tests and peer entry-point integration | Send commands to Anik; storage calls to Rishikesh |

Everyone writes tests for their own component. Prabhat is the integration owner, not the person who must repair everybody's module. Pair on cross-module defects; the responsible owner makes the fix.

### Rishikesh: file and metadata workflow

1. Agree on metadata fields, piece indexing, and exact final-piece length.
2. Create tiny test fixtures: one byte, an exact multiple of piece size, and a partial final piece.
3. Implement metadata creation and validation yourselves.
4. Implement reads by piece index; avoid loading the whole file into RAM.
5. Implement verification and storage of received pieces.
6. Expose a piece as available only after successful verification and storage.
7. Reconstruct pieces in numerical order and verify complete output.
8. Integrate one received piece with Prabhat before implementing every convenience feature.
9. Add storage-error tests and gather final correctness evidence for the report.

Deliverables: storage module, metadata example, boundary tests, corruption tests, reconstruction test, storage documentation.

Viva focus: piece boundaries, last piece, SHA-256, why a hash cannot establish authenticity without trusted metadata, disk versus memory storage.

### Debargha: tracker and experiment workflow

1. Agree on the announce request and peer-list response.
2. Implement an in-memory membership dictionary grouped by file ID.
3. Implement registration, refresh, stopped events, and expiry.
4. Implement a small HTTP client with timeout and retry behavior.
5. Give Anik discovery responses before the peer network is complete.
6. Test two independently running fake clients, then real peer processes.
7. Build the launcher with unique ports, directories, peer IDs, and logs.
8. Make the launcher stop only processes it started and preserve failed-run logs.
9. Run controlled experiments with the team and produce CSVs and plots.

Deliverables: tracker, client, expiry tests, launch instructions/harness, run manifest, raw results, graph scripts.

Viva focus: centralized discovery versus distributed data transfer, stale membership, HTTP request/response, timeout versus proof of failure.

### Anik: networking workflow

1. Write the framing and message table with the team.
2. Test encoding/decoding without live sockets.
3. Implement and test fragmented headers, fragmented payloads, and combined frames.
4. Establish one TCP connection and exchange handshakes.
5. Add bitfield exchange and one REQUEST/PIECE transaction with test data.
6. Connect to Rishikesh's real piece reader and Prabhat's scheduler.
7. Add HAVE, interest state, rejection, cancellation, and choking messages.
8. Add clean disconnect events, bounded buffers, timeouts, and reconnect handling.
9. Verify that simultaneous upload and download cannot interleave message bytes.

Deliverables: wire specification, parser tests, connection manager, transport tests, logs proving valid message exchange.

Viva focus: TCP byte streams, framing, EOF, network byte order, full duplex, application timeout versus TCP reliability.

### Prabhat: scheduler and coordinator workflow

1. Define piece states, neighbor state, and pending-request records.
2. Write selection tests against fake neighbor bitfields.
3. Start with sequential selection and one pending request per neighbor.
4. Integrate one actual transfer: reserve, request, verify/store, advertise.
5. Add rarest-first and seeded random tie-breaking.
6. Increase the request window to four per connection.
7. Add expiry, disconnection recovery, CANCEL, and late-response handling.
8. Add upload-slot selection and the free-rider experiment mode.
9. Integrate six downloaders, then help explain measured scheduler behavior.

Deliverables: scheduler, coordinator, request/state tests, selection evidence, upload-policy tests, integration checklist.

Viva focus: local rarity, atomic reservation, pipelining, request IDs, state transitions, why choking is separate from TCP flow control.

### Shared working routine

- Every working day: a short update containing completed work, next deliverable, and blockers.
- At least twice weekly: run the current integrated system together.
- Each change: implement a small unit, test it, commit it, request one teammate's review, merge after checks.
- Each interface change: update the contract and notify the affected owner before merging.
- Once weekly: each member explains another member's module.

Use short-lived branches such as `anik/framing-tests`; avoid six weeks of diverging personal branches. Preserve genuine commit authorship. Assign report sections by ownership; Rishikesh assembles them, but does not write everyone else's technical explanation.

## 6. Metadata and storage contract

Recommended metadata fields:

| Field | Meaning |
|---|---|
| `format_version` | Start with 1 |
| `filename` | Display name only; never an arbitrary output path |
| `file_size` | Exact number of source bytes |
| `piece_size` | Default 65,536 bytes: 64 KiB |
| `piece_hashes` | Ordered list of lowercase SHA-256 hex strings |
| `file_sha256` | SHA-256 of the entire original file |

Derive piece count from file size and piece size; validate that the hash list agrees. Indices start at zero. The last piece contains only the remaining bytes; do not pad it. Reject zero-byte input in version 1 and document that choice.

**Simple swarm identifier:** `file_id` is SHA-256 of the exact metadata-file bytes. Everyone copies that same file and hashes it before parsing. Reformatting its JSON creates a different ID. Store tracker URL separately in CLI configuration. This avoids ambiguous JSON reserialization rules and circular hashing of a metadata field containing its own hash.

Each downloader has a private piece directory. Save verified pieces under index-based names, then assemble them in index order. This is easier to reason about than concurrent random writes into one output file. It uses extra disk space during assembly; that is an acceptable, documented tradeoff.

The original seeder may read pieces directly from its source file. Verify its source against the supplied metadata before advertising all pieces, including when starting a second seeder.

## 7. Interfaces to freeze before independent implementation

These are responsibilities and conceptual signatures, not core implementation code.

| Interface | Inputs → result | Owner and rule |
|---|---|---|
| `load_metadata` | Metadata path → validated metadata and file ID | Rishikesh; reject inconsistent fields |
| `read_piece` | Index → exact piece bytes | Rishikesh; reject invalid/unowned index |
| `verify_and_store` | Index, bytes → success or explicit error | Rishikesh; never publish corrupt data |
| `assemble_file` | Output path → final verification result | Rishikesh; requires every piece |
| `announce` | File ID, peer ID, listening port, event → peer records | Debargha; bounded HTTP timeout |
| `connect_peer` | Peer record → asynchronous connection outcome | Anik |
| `send_message` | Connection ID, typed message → queued or rejected | Anik; enqueue does not mean delivered |
| Network event | Connection ID, event type, validated fields → coordinator | Anik; carries no scheduler decisions |
| `choose_requests` | State snapshot and available request slots → planned requests | Prabhat; excludes owned/in-flight pieces |
| `handle_event` | Network/timer event → state updates and commands | Prabhat; only owner of scheduling state |

Shared data definitions:

- Peer record: peer ID, IPv4 address, listening port.
- Neighbor: connection ID, peer ID, known bitfield, interest flags, choke flags.
- Pending request: request ID, piece index, connection ID, deadline.
- Local piece: MISSING, REQUESTED, VERIFYING, or HAVE.
- Stored piece bytes become shareable only after `verify_and_store` succeeds.

Specify whether each failure returns a result or raises an exception. Storage failures must be distinguishable from hash mismatches; retrying every disk-full error as if the remote peer were corrupt is incorrect.

## 8. Tracker design

Use a simple HTTP announce endpoint. A POST JSON request contains `file_id`, `peer_id`, `listen_port`, and an event: `started`, `update`, `completed`, or `stopped`. A successful response includes an announce interval and a list of other live peers for that file.

State is a dictionary indexed by `(file_id, peer_id)` with source IP, listening port, last-seen time, and optional completed status. Use the HTTP connection's source IP in the controlled local/LAN setup. Do not store bitfields or file contents.

Recommended starting values:

- Announce every 5 seconds.
- Expire entries after 20 seconds without refresh.
- HTTP timeout: 3 seconds.
- Validate port range, identifier format, and bounded request-body size.
- Exclude the requester and expired entries from each response.

For this small project, a single-threaded HTTP server can serialize the tiny membership operations; do not put slow file work inside its handler. Remove expired entries before responding to announces, so a background cleanup thread is unnecessary. No database is needed.

If the tracker fails, existing peer connections continue. Peers retry discovery with a bounded delay, for example 2, 4, then at most 10 seconds. If the tracker restarts, subsequent announcements rebuild its table. A stale tracker record is not a promise that a TCP connection will succeed.

## 9. Proposed peer protocol

This is your custom educational protocol, not the production BitTorrent wire format. The original BitTorrent specification is useful background on trackers and piece exchange, not an implementation dependency: [BEP 3](https://www.bittorrent.org/beps/bep_0003.html).

### Framing

Use one format for every message:

```text
[4-byte header length H, unsigned big-endian]
[H bytes of UTF-8 JSON header]
[payload_length bytes of raw binary data]
```

The header always includes `type` and `payload_length`. Control messages have zero payload. Only PIECE carries binary file bytes. The prefix counts encoded bytes, not characters.

Start with a 16 KiB maximum header. At the proposed 64 KiB piece size, a 64 MiB file has 1,024 pieces; an explicit JSON bitfield fits easily. Validate that the chosen metadata size/piece count fits this protocol bound. Reject excessive sizes clearly rather than silently truncating them. For version 1, limit files to 64 MiB and fix piece size to 64 KiB; expand limits only after testing.

TCP does not preserve application-message boundaries: one receive may contain part of a message or several messages. Read the prefix, header, and body to their specified lengths, with bounded allocations and a deadline for incomplete frames. EOF mid-frame is a failed connection. See the [Python socket HOWTO](https://docs.python.org/3/howto/sockets.html).

### Message table

| Message | Header fields beyond common fields | Meaning |
|---|---|---|
| HANDSHAKE | `protocol_version`, `file_id`, `peer_id` | Identify protocol, swarm, and peer |
| BITFIELD | `pieces`: list of 0/1 integers | Initial complete ownership snapshot |
| HAVE | `piece_index` | Sender has verified and stored this piece |
| INTERESTED | None | Receiver has something sender still needs |
| NOT_INTERESTED | None | Sender currently needs nothing receiver owns |
| REQUEST | `request_id`, `piece_index` | Ask for one complete piece |
| PIECE | `request_id`, `piece_index` | Response; payload is the raw piece |
| CANCEL | `request_id`, `piece_index` | Withdraw a request if sending has not started |
| CHOKE | None | Sender stops accepting new upload requests from receiver |
| UNCHOKE | None | Sender permits receiver to request pieces |
| REJECT | `request_id`, `piece_index`, `reason` | Valid request cannot be served: unavailable, busy, or choked |

Request IDs are monotonically increasing integers scoped to a connection and requesting direction. A response echoes its request's ID. A reconnect creates a new connection identity, preventing an old response from matching a new reservation.

For BITFIELD, the list is the simple wire representation of a bit vector; acknowledge that it is not bit-packed and consumes more bytes. Duplicate HAVE messages must not increase availability twice.

### Connection rules and validation

1. Initiator sends HANDSHAKE; acceptor validates and replies.
2. Reject unsupported version, different file ID, or self-connection.
3. Both sides send exactly one initial BITFIELD of the expected length.
4. Enter ACTIVE only after handshake and initial bitfield requirements are met.
5. Treat interest and choking as independent flags for each direction.
6. Reject invalid indices, field types, payload sizes, unknown types, and messages arriving in an invalid phase.
7. A malformed frame closes that connection; a valid but unserviceable request gets REJECT.

For a small full mesh, let only the peer with the lexicographically smaller ID initiate a connection to the larger ID. Both peers still upload and download on it. Periodic discovery lets the designated initiator find newly arrived peers. Retry failed attempts. Detect duplicate sessions defensively; do not count the same peer twice. This rule assumes all peers in the lab can accept incoming TCP connections.

### CANCEL behavior

CANCEL removes a request still waiting in the remote upload queue. If transmission has already started, let that complete frame finish; truncating it would break framing. The receiver checks whether the request remains pending and discards a late or canceled response. Cancellation therefore reduces avoidable work but cannot recall bytes already sent.

## 10. State machines and concurrency

### Process lifecycle

```text
START -> LOAD/VALIDATE -> LISTEN -> ANNOUNCE/DISCOVER
                                       |
                                       v
                                  DOWNLOADING
                                       |
                              all pieces verified
                                       v
                             ASSEMBLE/VERIFY FILE
                                       |
                                       v
                                    SEEDING
                                       |
                              explicit shutdown
                                       v
                                    STOPPED
```

An original seeder validates its source and enters SEEDING directly after startup. Tracker retries are background activity, not a reason to stop healthy transfers. No available pieces means WAITING/STALLED, not false success; periodically rediscover and report the cause.

### Connection lifecycle

```text
CONNECTING -> HANDSHAKING -> BITFIELD_EXCHANGE -> ACTIVE -> CLOSED
```

Failures can close a connection from any state. Remove its availability contribution once and release its pending requests. A listening peer process survives another peer's connection failure.

### Piece lifecycle

```text
MISSING -> REQUESTED -> VERIFYING -> HAVE
              |             |
       timeout/disconnect   invalid data
              |             |
              +-> MISSING <-+
```

Storage failure produces a clear local error and never marks HAVE. Within a run, HAVE pieces remain available; do not delete their stored files while advertising them.

### Recommended threading model

- One OS process per peer.
- One coordinator/main loop owns neighbor state, piece states, pending requests, timers, and upload-slot decisions.
- A listener accepts sockets.
- One reader and one writer thread per connection handle blocking I/O.
- Readers place decoded events on a bounded queue; writers consume bounded outgoing queues.
- The coordinator processes short events and schedules actions; workers do not modify its dictionaries.
- Small control events get priority over queued, unsent piece frames; an already-started frame always finishes first.

Anik owns thread and connection resources; Prabhat owns scheduling state. The file store is initially called through the coordinator. Small piece operations are acceptable here; measure before adding a disk-worker pool.

Queued upload jobs may use `threading.Event` cancellation flags. The coordinator can cancel an unsent job; the writer checks immediately before starting it. On CHOKE, withdraw queued jobs for that neighbor and reject them; already-started responses may finish. Set a per-connection cap on accepted upload work so a remote peer cannot create an unbounded queue.

One writer per socket prevents two threads interleaving bytes from different frames. Never block indefinitely while enqueuing: queue saturation must trigger backpressure, retry, or a connection failure. Use bounded socket writes and frame-progress deadlines. An idle healthy connection is not automatically a failed transfer.

Threads are useful for concurrent I/O, but do not assume ordinary CPython threads provide parallel execution of CPU-heavy Python code. See [Python threading documentation](https://docs.python.org/3/library/threading.html).

## 11. Piece selection, pipelining, and recovery

### Rarest-first

Recompute availability from current neighbor bitfields when scheduling. With a small swarm, this is easier to verify than maintaining many incremental counters.

1. Consider pieces this peer does not have and has not already reserved.
2. Exclude availability zero.
3. Count each distinct connected neighbor advertising the piece once.
4. Require an advertising neighbor that currently permits requests and has a free pipeline slot.
5. Pick the lowest positive availability among eligible pieces.
6. Break ties randomly; use a fixed recorded seed in tests and experiments.
7. Reserve the piece and record its request before sending.

Example: neighbors advertise `11010`, `10100`, and `01101`. Counts for pieces 0–4 are `2,2,2,1,1`. If all pieces are missing and both rare pieces have an eligible source, choose 3 or 4 first. If 3 is already requested, choose 4. If the only source for 4 is choking you, choose the rarest currently requestable alternative.

Call this **neighborhood rarest-first**. A peer does not have a globally authoritative map of the swarm. Choked neighbors may still count toward replication, even though they cannot currently serve a request.

### Pipelining

Start with one pending request per connection. After successful integration, use a configurable window of four whole-piece requests per connection. This allows several requests to be outstanding before the first response returns. It does not require parallel writes into one TCP connection.

At four 64 KiB pieces, one connection has at most 256 KiB of requested payload pending, before buffering overhead. Apply queue and neighbor limits as well; per-connection bounds alone do not bound the whole process.

Maintain one active reservation for each local missing piece across all neighbors. Different peers requesting the same piece is normal; the duplicate-work bug is one downloader unnecessarily requesting it from multiple sources at once.

### Recovery rules

| Event | Required behavior |
|---|---|
| Peer disconnects | Remove its availability and release its pending requests |
| Request exceeds deadline | Release reservation, send best-effort CANCEL, try another source |
| Matching response fails hash | Do not store/advertise; release and retry, preferably elsewhere |
| Repeated invalid data from one source | Close/temporarily avoid that connection; log the reason |
| Valid late or canceled response | Discard according to the documented request policy |
| Valid request for unowned piece | Send REJECT; downloader tries another source |
| Tracker unavailable | Continue established transfers and retry announcements |
| No live source has a missing piece | Report stalled progress; retry discovery; do not promise recovery |
| Disk failure | Report local failure and never send HAVE for the piece |

Start with a 10-second request deadline for local tests, configurable for throttled runs. Reserve immediately, track local queue residence, and begin the response deadline when the writer reports REQUEST sent; otherwise local congestion can cause false remote timeouts. Bound how long a queued request can remain unsent too.

## 12. Simplified choking and the free-rider experiment

Use a clearly named **simplified contribution-based upload-slot policy**. Do not claim full BitTorrent tit-for-tat behavior.

- A peer allows two interested neighbors to receive uploads at a time.
- Reconsider slots every five seconds.
- A downloading peer assigns one slot to the interested neighbor that supplied the most verified bytes in the preceding interval; break ties fairly.
- Rotate the other slot among remaining interested neighbors so newcomers can obtain their first pieces.
- A complete seeder rotates both slots fairly, because it no longer needs downloads and cannot use contribution ranking meaningfully.
- Send CHOKE/UNCHOKE only when a permission changes.
- If fewer than two neighbors are interested, serve the available ones.

Introduce this after pipelining and recovery, but before collecting free-rider results. Test slot rotation and permission handling independently.

Define a test-mode free rider as a peer that downloads normally but grants zero upload slots, including after it completes its own download for the remainder of that experiment. Measure its completion time, verified download bytes, and uploaded payload bytes, plus completion time for the cooperative peers.

It may still finish through rotating slots and seeders. That is an expected limitation, not evidence that the implementation necessarily failed. A short, uncongested run may reveal little; report this honestly. If needed, add a separate experimental upload cap shared across all connections of each peer, keeping it identical across comparison runs and documenting that it is application-level shaping. Do not quietly use a per-connection cap as if it were a per-peer limit.

## 13. Overall runtime workflow

1. Generate metadata from the source file and distribute the identical metadata file to all participants.
2. Start the tracker.
3. Start a seeder; validate the source, bind its listening socket, then announce.
4. Start downloaders with unique IDs, ports, and storage directories.
5. Each downloader loads metadata, starts listening, and announces.
6. Tracker returns live peers for that file ID.
7. Designated initiators establish TCP connections.
8. Peers validate handshakes and exchange bitfields.
9. Each peer updates interest and upload permissions.
10. Scheduler selects and reserves eligible missing pieces.
11. Writer sends REQUEST; neighbor returns PIECE or REJECT.
12. Receiver matches request ID, checks length, hashes bytes, and stores only valid pieces.
13. Coordinator marks HAVE, advertises it, and fills newly available request slots.
14. Other downloaders can now request that piece from this peer.
15. Disconnects and expired requests trigger recovery; announcements continue periodically.
16. When all pieces are verified, assemble and verify the final file.
17. Record completion, announce completed status, and remain seeding.
18. On explicit shutdown, best-effort announce stopped, close sockets, and stop workers.

## 14. Development order and dated milestones

Work begins on 23 September 2026, as requested. No tasks are required before that date and no earlier implementation progress is assumed. Section 21 gives the daily schedule; this table summarizes the revised milestones through the unchanged 24 October deadline.

| Dates | Shared milestone and exit condition | Individual emphasis |
|---|---|---|
| 23–24 Sep | Freeze scope, metadata, wire format, interfaces, state ownership; fixture tests run | R: boundaries; D: announce schema; A: framing spec; P: state model |
| 25–27 Sep | Two real processes transfer and verify one piece; tracker returns a usable endpoint | R: real storage; D: tracker/client; A: handshake/framing; P: one-request lifecycle |
| 28 Sep–4 Oct | Complete file transfer; one downloader serves a verified piece to another | R: assembly; D: launcher; A: HAVE/rejection; P: rarest-first |
| 5–11 Oct | Six downloaders work; two-seeder mode, pipelining, CANCEL, and recovery pass | R: corruption/storage tests; D: multi-process runs; A: transport failures; P: pipeline/retry |
| 12–17 Oct | Upload-slot policy and free rider work; experiment dry run; core feature freeze | R: correctness evidence; D: CSV pipeline; A: protocol edge cases; P: upload policy |
| 18–21 Oct | Controlled experiment matrix completed; raw logs preserved | All run/review; D collects and plots |
| 22–23 Oct | Report, clean setup rehearsal, recorded backup demo, viva practice | Each member teaches their own and another module |
| 24 Oct | Final verification and submission buffer | All sign off on evidence and contribution record |

Do not wait for every standalone module to be complete before integration. A hardcoded test fixture is fine for an early transport test; replace it in the integrated path immediately afterward.

**Two acceptance gates:** the early learning prototype is a one-piece exchange. The final submission requires the complete feature set above. Calling the prototype an MVP must not hide missing course requirements.

If time slips, cut polish and optional convenience work first. Keep required features, and record any actual requirement gap explicitly rather than silently downgrading it.

## 15. Testing strategy and acceptance evidence

### Unit tests

| Area | Important tests |
|---|---|
| Metadata/storage | One-byte file, exact boundary, short final piece, invalid hash list, reordered pieces, corrupt bytes, disk failure |
| Tracker | Register, refresh, expire, stop, exclude self, isolate file IDs, invalid port/body |
| Framing | Header split across reads, payload split, two frames combined, oversized header, bad JSON, mid-frame EOF |
| Message validation | Wrong swarm/version, invalid index, wrong bitfield length, invalid payload length, out-of-phase message |
| Scheduler | Zero availability, ties, owned/in-flight exclusion, duplicate HAVE, connection removal, source eligibility |
| Request lifecycle | Reservation before send, queue failure, timeout, late response, reject, cancellation before/during sending |
| Upload policy | Slot limit, rotation, new neighbor opportunity, seeder fairness, zero-slot free rider |

Use deterministic clocks and random seeds where possible. Do not make every timeout test sleep ten real seconds. Tests should check externally meaningful behavior and invariants, not merely duplicate implementation formulas.

### Integration tests, in order

1. Real peer discovers a real listener through the tracker.
2. Two processes exchange handshake and bitfield.
3. One requested piece is verified and stored.
4. Entire file completes and matches the source.
5. Downloader A uploads at least one verified piece to downloader B.
6. One connection sustains multiple outstanding requests without exceeding the configured window.
7. Timeout/CANCEL releases work and late responses do not corrupt state.

### System tests

- One seeder plus six downloaders: all outputs match.
- Two seeders plus six downloaders: all outputs match.
- Stop a downloader with requests in flight: surviving peers finish while a complete seeder remains.
- Inject one corrupt response: reject, retry, and complete correctly.
- Stop tracker after connections form: existing transfers continue.
- Stop the only source of a missing piece: report a stall instead of claiming recovery.
- Run the free rider with measured zero upload contribution.

Final invariants: HAVE implies verified stored bytes; no local piece has two active requests; queues and request windows remain bounded; a departed connection is removed once; assembled bytes match the source.

Preserve command/configuration, random seed, logs, expected outcome, actual outcome, and final hash for each acceptance run. A plausible terminal screenshot is not a substitute for correctness checks.

## 16. Experiment plan

### Definitions and controls

Define `L` as the number of initially empty downloaders and `S` as initial complete seeders. Total participants are `L + S`; the tracker is not a peer. Use these labels consistently.

Use one fixed file, for example a deterministic 32 MiB binary fixture, for the comparison matrix. Start with smaller fixtures for debugging. If pilot runs finish too quickly, adjust the workload within the documented size limit before collecting the comparison set, or introduce the explicitly documented upload cap.

Keep file, piece size, hardware, network, pipeline window, upload slots, startup method, and software revision fixed unless one is the independent variable. Use fresh storage and an empty tracker table for every run. Keep completed peers seeding until the run ends.

Use a readiness barrier: launch everyone with requests paused, wait for listeners, registration, and intended connections, then release downloads. This experiment-harness control is separate from the peer wire protocol. If you cannot implement a common release cleanly, time from the first peer launch, include startup overhead, and use exactly the same launch order and delay for all runs. Never mix those timing definitions.

### Measurements

- Peer completion time: final verification time minus that peer's download start.
- Distribution time: last required downloader's final verification minus common run start.
- Useful peer throughput: original file bytes divided by peer completion time.
- Aggregate useful throughput: `L × original file bytes / distribution time`, for successful full-completion runs.
- Sent message count, REQUEST count, retries, hash failures, and payload bytes uploaded per peer.
- Piece availability: number of live participants possessing each verified piece at a snapshot. The harness derives global summaries from logs; runtime peers still use only neighbor information.

Use monotonic elapsed timing. Do not subtract monotonic clock values from different machines. Begin the controlled measurement matrix on one host; for LAN runs measure global completion on the controller and explain notification/timing limitations. Localhost measurements are not evidence of internet-scale throughput.

### Comparison matrix

| Experiment | Configurations | Evidence to inspect |
|---|---|---|
| Swarm size | L = 2, 4, 6, 8; S = 1 | Distribution time, useful throughput, message count |
| Selection | Sequential, random, rarest-first; L = 6, S = 1 | Completion time, availability distribution, retries |
| Seeders | S = 1 versus 2; L = 6 | Distribution time and upload contributions |
| Free rider | Six cooperative downloaders versus five cooperative plus one free rider; S = 1 | Cooperative completion times, free-rider time/upload, choke changes |
| Failure | Baseline versus one scheduled downloader termination; L = 6, S = 1 | Retry behavior, surviving-peer completion, final hashes |

For failure runs, state the exact trigger, for example kill one designated downloader when it reaches 25% completion. Exclude the deliberately killed process from the surviving-peer completion target and label this difference. For the strict baseline comparison, also compute time for that same survivor subset in the no-failure run.

Run at least three repeats per configuration; five if time permits. Record individual observations and report mean plus standard deviation or min/max. Mark incomplete runs as failures with a timeout; do not silently discard them. Randomize configuration order where practical.

Suggested run columns: run ID, Git revision, configuration, L, S, strategy, random seed, file size, piece size, window, upload policy/cap, environment, duration, status. Store peer-level completion and byte/message counters separately.

Do not promise rarest-first will be fastest, more peers will always improve throughput, or a free rider will be blocked. The objective is a valid comparison and an explanation of the result. A complete seeder, homogeneous links, and very short runs can mask strategy differences.

## 17. Logging and terminal demonstration

Emit event records containing elapsed time, peer ID, remote ID/connection, event, piece index, request ID, and bytes where relevant. Suggested events: connected, handshake_ok, request_sent, piece_verified, piece_rejected, have_sent, request_expired, disconnected, choke_changed, complete.

Show a compact status line about once per second: verified pieces/total, connected peers, pending requests, uploaded bytes, downloaded bytes, and current state. Keep detailed frame logs at debug level.

Suggested eight-minute demo:

1. Rishikesh explains metadata and shows the source hash.
2. Debargha starts the tracker and announces the swarm.
3. Anik shows handshake/bitfield logs and explains framing.
4. Prabhat shows rarest-first choice, pending requests, and progress.
5. Show a PIECE transfer whose sender is a downloader, proving actual P2P sharing.
6. Stop one downloader; show released requests and surviving progress.
7. Verify completed output hashes and show a completed peer still serving data.
8. Briefly present experiment graphs and one limitation.

Keep a separate short corruption/free-rider demonstration or recorded evidence if the live time slot is tight. Use terminals and logs; a web UI is unnecessary.

## 18. Viva preparation

Every member should explain the complete path from discovery to final verification, then go deeper on their own component.

| Question | Answer you should be able to give |
|---|---|
| Why P2P? | Downloaders contribute upload capacity and redistribute verified pieces |
| Is the system fully decentralized? | No; discovery uses a central tracker, while data transfer is peer-to-peer |
| Why TCP? | Reliable ordered byte transport simplifies file exchange; application framing is still needed |
| Why pieces? | Independent verification, selective retry, and sharing before full completion |
| Why SHA-256 when TCP already checks data? | Validate against expected content, including incorrect peer data; a hash is not authentication |
| How does a bitfield differ from HAVE? | Initial complete snapshot versus later single-piece announcement |
| Why a length prefix? | TCP has no application-message boundaries |
| Why rarest-first? | Prefer less-replicated eligible pieces to improve availability; it is not guaranteed to minimize every completion time |
| Why random ties? | Avoid all peers deterministically choosing the same equally common piece |
| Why pipeline requests? | Keep useful work outstanding instead of waiting one round trip per request |
| Why CANCEL? | Withdraw queued work after timeout or a scheduling change; already-sent bytes cannot be recalled |
| Why request IDs? | Associate responses and cancellation with a particular request attempt |
| Why one coordinator? | Serialize related state changes and prevent two handlers reserving the same local piece |
| Does the GIL remove races? | No; multi-step application invariants still need ownership or synchronization |
| What if the tracker dies? | Existing connections continue; discovery waits for recovery |
| What if the seeder dies? | Completion is possible only if surviving participants collectively retain every missing piece |
| How is choking different from TCP flow control? | Choking is our upload-permission policy; TCP flow control protects receiver buffering |
| Why can a free rider still finish? | Seeders and rotating opportunities still supply it; this policy is not a perfect defense |
| Is this compatible with BitTorrent clients? | No; it is a custom educational protocol with simpler framing, hashes, and whole-piece requests |

Live modification practice:

- Rishikesh: explain and change a storage boundary check, then run its test.
- Debargha: change tracker expiry and prove stale entries disappear.
- Anik: lower the header limit or reject a malformed message and show the test.
- Prabhat: switch selection strategy or window from four to one and explain the effect.
- Everyone: predict what happens before running the modified program.

Do not memorize library names without being able to point to where they are used. A useful weekly exercise is a two-minute explanation of one bug, its cause, and the test that caught it.

## 19. Biggest risks and decisions to close

| Risk | Concrete mitigation |
|---|---|
| Late integration | One verified piece across real processes by 27 September |
| Protocol disagreement | Shared message table, fixtures, limits, and error rules |
| Incorrect TCP parsing | Fragmentation/coalescing tests before full swarm tests |
| Duplicate requests/races | Coordinator-only scheduling state and immediate reservation |
| Blocking and memory growth | Bounded queues, window limits, socket/frame deadlines |
| Successful downloads that all come from seeders | Require evidence of downloader-to-downloader upload |
| Free-rider experiment without visible policy effects | Log slots and contribution, use adequate run duration, report limitations |
| Last source disappearing | Distinguish recoverable failure from unavailable data |
| Unbalanced workload | Tracker owner runs harness; storage owner owns correctness/report assembly |
| Unexplainable code | Small commits, peer explanations, weekly live-modification practice |

Before coding, the team should record acceptance of these proposed defaults:

1. Python version and installation steps.
2. Whole-piece requests allowed by the assignment; no block offsets in version 1.
3. File-size/piece-size/header bounds and empty-file policy.
4. Exact metadata bytes determine file ID.
5. HTTP announce schema and expiry behavior.
6. Framing, message fields, validation, and cancellation semantics.
7. Single coordinator and worker boundaries.
8. Connection initiation rule and controlled reachable LAN/localhost topology.
9. Pipeline window and request/queue deadlines.
10. Simplified choking scope and free-rider definition.
11. L/S peer-count terminology and experiment timing definition.
12. Integration milestones, ownership, and AI-use record.

These defaults are ready to discuss and adopt; the team should not spend a week exploring alternative frameworks.

## 20. Submission checklist and AI-use boundary

- [ ] Source code written and understood by its contributing members.
- [ ] All final requirements demonstrated, including rarest-first, pipelining, cancellation, recovery, and the planned free-rider policy.
- [ ] Six-downloaders/one-seeder and six-downloaders/two-seeder evidence.
- [ ] Matching per-piece verification and final file hashes.
- [ ] Genuine downloader-to-downloader transfers shown.
- [ ] Unit, integration, and system-test results saved.
- [ ] Clean-machine setup and startup instructions rehearsed.
- [ ] Protocol, architecture, experiments, limitations, and contribution documentation.
- [ ] Raw results, graph scripts, labeled graphs, failed-run disclosure.
- [ ] Meaningful individual Git history.
- [ ] AI-USE.md accurately records assistance.
- [ ] Each member can explain the whole workflow and modify their own code live.

Under the AI rules you supplied, AI may help with design explanations, pseudocode, review/debugging, tests, boilerplate, experiment/plotting support, and documentation. The team must write the core tracker, peer protocol, framing/handshake behavior, scheduler, and choking implementation yourselves. This guide intentionally supplies an engineering foundation rather than ready-to-submit core code.

For AI-USE.md, record date, tool, purpose, affected artifact, what was accepted, and how the team reviewed or validated it. Record this plan as AI-assisted architecture and documentation. Do not imply AI-assisted work was independently authored or that unrun tests passed.

**First concrete milestone:** finalize the shared contracts, then make two independently running processes transfer one real piece that passes SHA-256 verification. Every later feature should extend that tested path.

## 21. How to execute this plan from 23 September

### 21.1 First meeting: establish actual progress

Spend 45–60 minutes together. Every member shows existing files, explains what they do, and runs any available tests. Mark each work item NOT STARTED, IN PROGRESS, BLOCKED, or VERIFIED. VERIFIED requires reproducible evidence; a filename or a confident explanation is not sufficient.

Record the shared Python version, operating systems, working repository branch, actual deadline, and any differences between the original assignment sheet and this plan. Do not rewrite working compatible code just to match the suggested filenames. Map existing functions to the contracts instead.

Use a simple task table in the repository: task ID, owner, status, dependency, acceptance test, commit, next action. No project-management service is required.

### 21.2 Immediate daily plan

| Date | Shared outcome | Rishikesh | Debargha | Anik | Prabhat |
|---|---|---|---|---|---|
| 23 Sep | Current-state review and contract agreement | Inspect storage; freeze metadata | Freeze announce request/response | Freeze frames and message fields | Freeze state and event records |
| 24 Sep | First independent tests | Piece length/hash fixtures | Register/update/expiry tests | Encode/decode, split-frame tests | Fake-neighbor selection tests |
| 25 Sep | Components accept agreed inputs | Verified piece store available | Real tracker returns endpoints | Real handshake and bitfield | Reserve one request with fake transport |
| 26 Sep | Integrate one transfer | Supply exact source bytes | Launch tracker plus two peers | REQUEST/PIECE on real socket | Verify/store/HAVE lifecycle |
| 27 Sep | Gate G1: one real verified piece | Confirm output bytes/hash | Save reproducible launch record | Test split reads and disconnect | Show reservation cleared exactly once |
| 28–29 Sep | Full small file | Assembly and final verification | Clean run directories and logs | Multiple frames and HAVE | Refill one-request window |
| 30 Sep–1 Oct | Real P2P redistribution | Read newly stored pieces | Launch third process | Bidirectional exchange | Show downloader-to-downloader upload |
| 2–4 Oct | Gate G2: small swarm + rarest-first | Boundary regression tests | Capture selection evidence | Validate peer identity/state errors | Replace baseline selection with rarest-first |
| 5–7 Oct | Six downloaders + pipelining | Large fixture correctness | Six-peer harness and two seeders | Stable readers/writers | Window four, request IDs, bounds |
| 8–11 Oct | Gate G3: recovery | Corrupt input and disk-error tests | Failure trigger and run status | Mid-frame failure/CANCEL tests | Timeout, reject, reconnect cleanup |
| 12–15 Oct | Simplified upload policy | Validate uploaded bytes | Free-rider run setup | CHOKE/UNCHOKE transport checks | Contribution slot + rotation |
| 16–17 Oct | Gate G4: feature freeze and pilot | Final correctness review | Pilot all experiment types | Resolve protocol defects | Check invariants and policy evidence |
| 18–21 Oct | Measured experiment matrix | Independently verify outputs | Collect/plot measurements | Inspect traffic/error counters | Explain selection/policy behavior |
| 22–23 Oct | Gate G5: release rehearsal | Assemble report | Clean setup and experiment package | Demo transport and limitations | Full-system demo and state walkthrough |
| 24 Oct | Submission buffer | All members check final package, authorship, and viva readiness | | | |

Dates are targets, not evidence of completion. If starting from zero on 23 September, prioritize G1 over polishing every module. If G1 slips, identify the failed boundary, pair its two owners, and pause features depending on it. Do not allow the integration owner to become the only person debugging.

### 21.3 Stop/go gates

| Gate | Required proof before proceeding | If it fails |
|---|---|---|
| G0: contracts | One metadata fixture, one peer record, one sample frame, one event example understood by all | Resolve disagreement before separate coding |
| G1: one piece | Two OS processes, actual sockets, matching SHA-256, stored piece | Repair framing or handoff; keep window at one |
| G2: small swarm | Full file verified; a downloader uploads; rarity test passes | Do not scale an unexplained failure to six peers |
| G3: resilient swarm | Six downloaders, two-seeder variant, pipelining, failure/corruption recovery | Preserve logs and isolate a smaller reproducer |
| G4: final features | Upload policy, free rider, all required behaviors and experiment pilot | Drop UI/polish; record any unmet requirement explicitly |
| G5: release | Fresh setup, reproducible tests, honest report, each member can explain/change code | Fix setup and evidence before cosmetic edits |

## 22. Shared configuration, records, and ownership

### 22.1 Proposed defaults to freeze

| Setting | Initial value | Purpose and qualification |
|---|---|---|
| Piece size | 65,536 bytes | Whole-piece requests; last piece may be shorter |
| File size | 1 byte to 64 MiB | Bound for this teaching implementation |
| Metadata input limit | 256 KiB | Enough for 1,024 SHA-256 entries; validate before parsing |
| Header size | 1–16,384 bytes | Reject zero and excessive prefix values |
| Piece payload | Exact expected piece length | Never accept arbitrary declared lengths |
| Maximum neighbors | 12 per peer | Supports eight downloaders plus two seeders in the experiment variants |
| Pending download requests | Initially 1; final default 4 per neighbor | Includes requests queued locally |
| Accepted upload work | At most 4 per neighbor, including active frame | Excess gets REJECT busy |
| Coordinator event queue | 128 events | Bounded buffering, not a throughput target |
| Per-connection outgoing queue | 32 frames total | Control + PIECE entries; handle Full explicitly |
| Coordinator timer polling | About 100 ms | Check deadlines even if no message arrives |
| Tracker announce / expiry | 5 s / 20 s | Expiry checked when handling announces |
| Tracker HTTP timeout | 3 s client; bounded server request-read time | Prevent discovery hanging forever |
| Tracker request / response size | 4 KiB / 64 KiB | Bound HTTP JSON input and client response parsing |
| Connect / handshake deadline | 3 s / 5 s | For local/LAN pilot; configurable |
| Incomplete frame deadline | 10 s from first frame byte | Idle sockets with no frame started are different |
| Unsent request queue deadline | 5 s | Cancel locally before requesting a retry |
| Response deadline | 10 s from successful REQUEST write | Adjust for documented shaping or slower network |
| Upload slots / reconsideration | 2 / 5 s | Simplified policy, not production BitTorrent |
| Operational peer ID | 1–32 ASCII letters, digits, underscore, hyphen | Unique per running process; predictable comparison |
| Request ID | Integer 1 through 2^63−1 | Increasing per connection and requester; do not reuse |

Use strict integer checks where required: JSON `true` must not be accepted as piece index 1 just because Python booleans are integer subclasses. Unknown required-version values are errors. Do not add third-party schema frameworks for this small contract.

Queue capacities are item counts. A queue of 128 full 64 KiB payloads can retain roughly 8 MiB of data, plus overhead. At 12 neighbors, outgoing queues could add more. Bound accepted uploads and active connections as well as individual queues. These are manageable lab limits, not a claim of a formally optimal memory budget.

### 22.2 Exact owner of mutable state

| State | Exclusive owner | Other components do what? |
|---|---|---|
| Tracker membership | Debargha's tracker handler | Return copies in responses |
| Tracker client retry/announce timing | Debargha's discovery worker | Publish results to coordinator |
| Peer neighbor map, connection phase, interest/choke flags | Coordinator, maintained using Anik's session rules | Readers report frames; writers report outcomes |
| Socket objects, buffers, writer queues, transport closed flag | Anik's connection resources | Coordinator sends commands; closure guard is synchronized |
| Piece states, reservations, pending requests, contribution totals | Prabhat's coordinator | Nobody modifies from a reader/writer thread |
| Verified piece files and storage error handling | Rishikesh's file store | Coordinator is its primary caller |
| Run records and child process handles | Debargha's harness | Never used for peer discovery or runtime selection |

The connection's physical close flag is a transport detail protected by a small lock/Event as needed; it is not a second copy of scheduler state. The coordinator owns semantic transitions. Anik supplies validation helpers and session rules called from that coordinator.

### 22.3 Keep tracker HTTP outside the coordinator

One discovery worker per peer performs announce HTTP calls and retry waits. It publishes PEERS_DISCOVERED or TRACKER_ERROR events. The coordinator must not stop processing PIECE events for three seconds during an HTTP timeout. A small queue or stop Event lets the worker receive completed/stopped status updates. A failed stopped announcement must not prevent shutdown.

### 22.4 Event contract

| Event | Minimum data | Coordinator responsibility |
|---|---|---|
| CONNECTION_OPENED | Connection ID, incoming/outgoing, endpoint, expected remote ID when known | Enter handshake phase; enforce limits |
| FRAME_RECEIVED | Connection ID, decoded header, immutable payload bytes, receive time | Apply session/state validation, then message handling |
| FRAME_SENT | Connection ID, local send-token, type, optional request ID, completion time | Start request timer or account upload completion |
| SEND_FAILED | Connection ID, send-token, reason | Release/close as appropriate; do not claim sent bytes |
| CONNECTION_CLOSED | Connection ID, reason | Idempotent cleanup and reassignment |
| PEERS_DISCOVERED | File ID, validated peer records | Filter self/duplicates; initiate allowed connections |
| TRACKER_ERROR | Category, time | Log/rate-limit display; preserve current connections |

FRAME_RECEIVED means framing and field structure have been validated. It does not mean that the remote peer is in the correct state or that a piece matches an outstanding request. Those checks belong in the coordinator.

If the bounded event queue is full, transport workers must not hang forever. Close the affected transport after bounded delivery failure and expose a synchronized closed flag. The coordinator reconciles those flags on timer ticks so it eventually cleans up even if a CONNECTION_CLOSED event could not be enqueued. This is a small failure-path check, not permission for workers to modify scheduler dictionaries.

Do not rely on events from different threads arriving in a convenient order. A response can arrive before FRAME_SENT is consumed locally. Reservations therefore exist before enqueueing. Accept a valid matching response even if local send acknowledgement is still queued; a later FRAME_SENT for that completed request is harmless and cannot recreate it.

## 23. Detailed handoff and integration playbook

### 23.1 Shared fixtures to create first

- `tiny.bin`: a deterministic non-empty fixture small enough to inspect manually.
- `boundary.bin`: exactly 65,536 bytes.
- `boundary-plus.bin`: 65,537 bytes; piece lengths must be 65,536 and 1.
- A metadata file generated once and copied without reformatting.
- Peer records such as `seed-01`, `peer-01`, `peer-02`, with distinct ports.
- A fake clock and deterministic random seed for scheduling tests.

Example network defaults for a one-machine lab: tracker `127.0.0.1:8000`, seeder port 7001, downloaders 7002–7007; optional second seeder 7008. These are examples, not hardcoded protocol constants. Check ports before a run and record actual values.

### 23.2 Handoff A: metadata and file store

Rishikesh gives Prabhat a validated metadata fixture, expected piece count and lengths, read/verify/store contracts, and error examples. Prabhat calls them with a fake PIECE event. The test passes only if invalid bytes leave the piece unavailable and valid bytes can subsequently be read back unchanged.

### 23.3 Handoff B: tracker to connections

Debargha starts a real tracker and registers a listening test peer. Anik's component receives the discovery result, applies the lower-ID initiation rule, connects, and verifies the handshake peer ID against the expected record. A raw HTTP 200 without a successful peer connection does not complete this handoff.

### 23.4 Handoff C: network to coordinator

Anik emits real FRAME_RECEIVED events using the agreed connection ID. Prabhat consumes HANDSHAKE, BITFIELD, and PIECE events. Malformed bytes must produce a controlled connection failure, not a half-valid scheduler event. Queue failure and closed-connection events must not leave permanent reservations.

### 23.5 Handoff D: first complete piece

1. Start source peer with verified metadata and one test file.
2. Start downloader with the same metadata and empty storage.
3. Discover, connect, exchange handshake/bitfield, and establish interest/permission.
4. Coordinator reserves piece 0 before asking network to enqueue REQUEST.
5. Uploader validates the request and returns its exact piece bytes.
6. Downloader verifies/stores, records HAVE, and clears the request once.
7. Read the stored bytes back and compare with the original fixture.
8. Save both peer logs plus launch configuration.

### 23.6 Handoff E: prove redistribution deterministically

A three-process success can accidentally be entirely seeder-to-downloader. To prove P2P sharing, first let downloader A obtain a specific piece. In a controlled integration test, connect downloader B to A as its only source for that piece, with any test topology restriction clearly separate from normal full-mesh operation. Show B's verified receipt with A as sender. Then restore normal discovery and test the full swarm.

Do not use a central harness to deliver bytes, choose pieces for peers, or provide global availability to the algorithm. The harness may control starts/stops and collect logs only.

## 24. Message processing details that prevent integration bugs

### 24.1 Startup and initial permissions

Every new connection starts not interested in either direction and choked in both directions. The initiator sends HANDSHAKE first. After receiving a valid handshake, the acceptor queues its HANDSHAKE before its BITFIELD; the initiator queues BITFIELD after validating the reply. Per-socket writer order preserves that sequence.

Do not send INTERESTED or requests until the local initial BITFIELD has been queued and the remote initial BITFIELD has been received and validated. Frames queued earlier in that writer remain ahead of later control frames. If the local ownership changes around the initial BITFIELD snapshot, queue subsequent HAVE notifications after the snapshot, so the remote state eventually catches up.

During the first one-piece milestone, a temporary always-allow upload policy can immediately issue UNCHOKE after activation. Label it as a development baseline. Replace it with the specified two-slot policy before final experiments; the wire-level permission flags remain the same.

### 24.2 Outgoing ordering and cancellation

Maintain order among control messages. Prioritize control over unsent PIECE jobs only; never let a CANCEL overtake the REQUEST it refers to, or BITFIELD overtake HANDSHAKE. Implement priority only if it stays easy to test; a bounded FIFO with small pieces is an acceptable initial transport milestone, followed by explicit control-priority tests if introduced.

A queued local REQUEST that expires must be withdrawn using its send-token/cancellation flag. If it has started writing, let the complete frame finish and queue CANCEL afterward. A timeout does not permit silently leaving the old REQUEST in the outgoing queue to transmit later.

Cancellation checks are best effort at the boundary between queued and started. If cancellation and writer start race, treat the frame as already started and allow it to finish. The receiver's late-response policy preserves correctness. Do not promise that a cancellation flag can atomically recall an in-progress write.

### 24.3 Receiving CHOKE and REJECT

On incoming CHOKE, stop making new requests to that neighbor. Keep already transmitted requests pending until PIECE, REJECT, disconnect, or deadline, because started transfers may finish. Cancel local unsent requests and release their reservations. On local CHOKE, cancel queued upload jobs, send REJECT choked for withdrawn requests, and allow started frames to finish.

REJECT releases only the matching live request. A late REJECT cannot release a replacement request with a different ID. REJECT busy can trigger a short source cooldown, such as one second; avoid immediately flooding the same neighbor with identical retry attempts.

For duplicate incoming REQUEST IDs, adopt one version-1 rule: an identical request still pending is ignored without creating another job; reuse with a different piece index or a previously completed/retired ID is a protocol error. New request IDs increase within the requesting direction, so keep the highest observed ID and a bounded map of pending uploads. Opposite-direction requests use a separate namespace. A repeated CANCEL for already-retired work is harmless.

### 24.4 Source corruption and retry fairness

A failed hash is an application data-integrity failure. Do not advertise or add its bytes to verified-contribution scores. Close or avoid a repeatedly corrupt connection. A short per-source cooldown prevents repeated requests to the same bad provider when a good alternative exists. Do not permanently blacklist an entire swarm because of one failure.

### 24.5 Exact completion

All piece states HAVE is necessary but not the final completion event. Assemble in index order, confirm exact file size, compute final SHA-256, and only then emit COMPLETE. An assembly error is a local failure, even if network transfer succeeded. Continue serving already verified pieces during the rest of the experiment; for the short bounded file, synchronous assembly may briefly pause coordinator processing and should be included in measured completion time.

### 24.6 Disconnect and shutdown

Reader and writer can both observe the same broken socket. Protect physical close so it is safe more than once, and make coordinator cleanup idempotent. Release each reservation once, remove the bitfield once, clear queued work, and ignore stale events from the old connection ID.

On global shutdown: stop scheduling, signal discovery/listener workers, best-effort send stopped, close sockets to unblock reads/writes, wake queue consumers, join workers with a bound, flush logs, and exit. Do not assume daemon threads or garbage collection prove clean shutdown.

## 25. Requirements-to-evidence matrix

These are proposed test IDs so team discussions can refer to one concrete check. The team writes/runs tests; none are marked passed here.

| ID | Requirement / scenario | Setup and action | Expected result | Lead |
|---|---|---|---|---|
| F01 | Last-piece size | 65,537-byte fixture | Two pieces: 65,536 and 1 bytes | Rishikesh |
| F02 | Corruption rejected | Flip one byte in a valid piece | No HAVE, no verified file entry, explicit hash error | Rishikesh |
| F03 | Metadata identity | Reformat identical JSON values | Different byte-based file ID; original copied file matches | Rishikesh |
| F04 | Assembly ordering | Provide all piece files with misleading lexicographic names | Numerical order, correct length and final SHA-256 | Rishikesh |
| T01 | Discovery isolation | Register peers in two file IDs | Response contains only live same-file peers, excluding self | Debargha |
| T02 | Expiry | Fake monotonic time reaches expiry boundary | Entry with age at least 20 s is excluded | Debargha |
| T03 | Tracker restart | Clear/restart tracker while peer worker continues | Announce update recreates membership | Debargha |
| N01 | TCP fragmentation | Deliver prefix, JSON, payload in arbitrary fragments | Exactly one reconstructed frame | Anik |
| N02 | Frame coalescing | Feed three consecutive frames together | Three ordered decoded messages | Anik |
| N03 | Bound validation | Advertise huge header/payload | Reject before large allocation; one connection closes | Anik |
| N04 | Wrong swarm/identity | Send wrong file ID or mismatched expected peer ID | No ACTIVE connection or piece requests | Anik |
| N05 | Mid-frame send failure | Interrupt a frame write | Close connection; no retry of whole frame on same stream | Anik |
| S01 | Rarest eligible | Fixed bitfields with owned/reserved/unavailable pieces | Select minimum positive eligible rarity | Prabhat |
| S02 | Reservation race | Two eligible sources, one missing piece | One pending request for this local piece | Prabhat |
| S03 | Pipeline bound | More than four available pieces from a source | At most four queued/transmitted requests pending | Prabhat |
| S04 | Stale response | Timeout and reassign, then old response arrives | New request remains intact; stale payload discarded | Prabhat |
| S05 | Response before sent-event | Reorder local worker events | One accepted completion; no request resurrection | Prabhat |
| C01 | Queued cancellation | CANCEL before writer starts response | No PIECE bytes for canceled job; next frame remains valid | Anik + Prabhat |
| C02 | In-progress cancellation | CANCEL after response starts | Complete frame allowed; receiver safely discards if canceled | Anik + Prabhat |
| C03 | Slot policy | Three or more interested neighbors | At most two upload permissions; rotation creates opportunities | Prabhat |
| I01 | One real piece | Two peer processes via tracker | Bytes verified and saved; genuine TCP transfer | All |
| I02 | Actual P2P | Downloader A supplies B | B verifies data sent by A | All |
| Y01 | Required scale | S=1, L=6; repeat S=2, L=6 | All required outputs match | All |
| Y02 | Recoverable crash | Kill downloader with work in flight; retain seeder | Survivors finish; requests reassigned | All |
| Y03 | Unrecoverable availability | Remove final source of a missing piece | Stall reported, no false completion | All |
| Y04 | Tracker loss | Stop tracker after connections establish | Existing peer transfer continues | All |
| Y05 | Free rider | Zero upload slots for one downloader | Zero completed uploaded payload bytes; results honestly measured | All |

Test malformed lengths/types separately from hash mismatch. Tests that use tiny artificial piece sizes should target generic boundary helpers only; production metadata remains fixed at 64 KiB unless the whole team explicitly changes the version-1 contract.

## 26. Debugging by observed symptom

| Symptom | First inspect | Likely boundary |
|---|---|---|
| Tracker returns peers but connection fails | Source IP, listening port, process still alive, bind address | Discovery → socket |
| Localhost works but LAN does not | LAN IP and listener bind; host firewall setting | Environment, not rarest-first |
| Handshake succeeds then no progress | BITFIELD, INTERESTED, UNCHOKE logs | Session → scheduler |
| Everything is available but no REQUEST | Missing vs reserved sets, source permissions, pipeline counters | Scheduler |
| Hash mismatch on every last piece | Expected last-piece length and padding | Protocol → storage |
| Messages occasionally become invalid JSON | Concurrent socket writes, wrong byte count, partial reads | Framing |
| Requests remain forever after disconnect | Closed event, connection ID, idempotent cleanup | Transport → coordinator |
| Healthy transfers time out when tracker stops | Synchronous announce blocking main loop | Discovery worker integration |
| One downloader gets no upload opportunity | Interest flags, seed rotation, timer progression | Upload policy |
| Total reported bandwidth seems doubled | Counts of send and receive for same bytes, useful vs wire bytes | Metrics |
| Program cannot exit | Blocking queue get, open sockets, worker stop signal | Lifecycle |

Debug in this order: reproduce with the smallest topology, identify the last expected event, check its inputs, write one failing test, fix the responsible module, rerun that test and the relevant integration gate. Do not change selection strategy to conceal a framing failure.

## 27. Experiment runbook and result files

### 27.1 Minimum comparison set

Use rarest-first, L=6, S=1, window=4, cooperative uploads as the baseline. Reuse baseline observations across plots only when every fixed setting, startup method, revision, and file matches. This gives nine distinct configurations: four swarm sizes; two additional selection strategies; one additional seeder count; one free rider; one failure. Three repetitions each means 27 measured runs, plus pilots and correctness tests.

Use independent run seeds and document how they are assigned. For strategy comparisons, reuse a comparable seed schedule and startup order across strategies without claiming identical thread/network interleavings. If the code or fixed configuration changes, rerun affected comparisons rather than mix incompatible data.

### 27.2 Per-run procedure

1. Record Git revision, configuration, environment, seed, and expected participants.
2. Create a new run directory; never reuse previous download storage.
3. Start tracker and verify readiness, not an arbitrary long sleep.
4. Start and validate seeders.
5. Start downloaders consistently and record the chosen timing origin.
6. Record readiness/start/verification/failure events.
7. Apply only the planned free-rider or failure condition.
8. Wait for the expected live completion set, or a documented timeout.
9. Independently verify final sizes and hashes.
10. Stop only owned processes and preserve all logs, including failed runs.
11. Write run summary and peer rows; review anomalies before rerunning.

Suggested folder contents: `config.json`, `run.csv`, `peers.csv`, one event log per peer, tracker log, correctness summary, and any failure-trigger record. Keep small selected evidence in the submission; bulky downloads are not source code.

### 27.3 Counter definitions

Count application messages at the sender after a complete frame write; do not add receive counts to estimate number of messages. Count completed PIECE payload bytes separately from control/header bytes. A failed partial write is an incomplete transfer; unless explicitly instrumented, do not invent its exact byte count.

`verified_download_bytes` increases only when a previously missing piece is accepted and stored. Repeated/corrupt payload bytes are not useful throughput. Sender uploaded payload can include bytes later rejected by a receiver. The two measurements answer different questions.

The plot titled "distribution time" includes final assembly verification. The plot titled "useful throughput" uses source bytes, not encoded-message bytes. Label seconds, MiB, or MiB/s explicitly; 1 MiB = 1,048,576 bytes.

### 27.4 Interpretation template

For each plot, write: what changed, what stayed constant, how many runs, observed numerical result, plausible explanation supported by logs, and limitation. If a hypothesis is not supported, say so. Do not remove outliers merely because a graph looks untidy; explain or report them.

## 28. Report and evidence ownership

| Report section | Writer | Reviewer | Evidence |
|---|---|---|---|
| Problem, scope, metadata, storage | Rishikesh | Prabhat | F01–F04 and file hashes |
| Tracker and discovery | Debargha | Anik | T01–T03, announce examples |
| Framing, messages, connection lifecycle | Anik | Rishikesh | N01–N05, protocol table |
| State, selection, pipeline, upload policy | Prabhat | Debargha | S01–S05, C01–C03 |
| Experimental method and plots | Debargha, with all reviewing | Rishikesh | Run manifests, raw CSV, scripts |
| Limitations and conclusions | All; each explains own component | All | Observations, no unsupported promises |
| Contribution and AI use | Every member writes own entries | All | Commits, reviews, assistance records |

Rishikesh assembles the report and checks consistency of terminology; that does not transfer technical authorship to him. Leave test results blank/pending until run. Every screenshot should have a caption explaining what it proves and which run produced it.

## 29. Viva and learning schedule

### 29.1 Four short sessions each week

1. Explain a concept in two minutes without opening code.
2. Trace it through your implementation with one concrete example.
3. Predict an edge case and run the relevant test.
4. Make one small live change, explain its consequences, and restore or commit deliberately.

Start with sockets, messages, piece boundaries, and tracker discovery. Next cover bitfields, requests, state ownership, and SHA-256. Then cover rarity, pipelining, failures, and choking. Finish with metrics, limitations, and cross-module explanations.

### 29.2 Each member must trace this example

"Peer B is missing piece 2. Peer A advertises it. B becomes interested; A unchokes B. B reserves piece 2 and sends request 17 on connection C. A reads verified bytes and sends PIECE(17,2). B validates request identity, length, hash, and storage; it then sends HAVE(2). If A disappears before completing the frame, B releases the reservation and can choose another provider. If no provider remains, B waits rather than inventing data."

Point out which owner handles every step. Replace the happy path with timeout, wrong hash, wrong swarm, or late response and explain how the path changes.

## 30. References and use of the individual plans

The four individual documents specify each member's first actions, responsibilities, task order, inputs/outputs, boundary tests, troubleshooting, dated milestones, report contribution, and viva practice. They are intentionally concrete but leave the core implementation to the students under the supplied AI rules.

Technical reading should be selective, tied to a task:

- [Python socket HOWTO](https://docs.python.org/3/howto/sockets.html): streams, partial reads/writes, and framing.
- [Python socket reference](https://docs.python.org/3/library/socket.html): socket methods and timeout/error behavior. A failed `sendall` does not report exactly how much data reached the peer; close a partially written frame's connection rather than replaying it blindly.
- [Python queue documentation](https://docs.python.org/3/library/queue.html): bounded thread-safe queues. A prior `empty()`/`full()` check does not guarantee the next operation succeeds; use the operation and handle its outcome.
- [Python HTTP server documentation](https://docs.python.org/3/library/http.server.html): simple handler construction; suitable for this controlled teaching setup, not production deployment.
- [Python hashlib documentation](https://docs.python.org/3/library/hashlib.html): SHA-256 on bytes, incremental updates, hexadecimal digests.
- [BitTorrent BEP 3](https://www.bittorrent.org/beps/bep_0003.html): conceptual comparison only; our protocol is intentionally different.

After each integration gate, each owner should update the task status, evidence reference, actual interface changes, and AI-use record. That makes these plans working guides instead of documents that stop matching the code after the first week.
