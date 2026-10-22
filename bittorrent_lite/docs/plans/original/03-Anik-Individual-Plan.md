# Anik Dey — individual execution plan

**Roll number:** 2405558  
**Project:** CS-30003 P8, BitTorrent-lite, CSE 33  
**Revision:** 22 September 2026 · **Work starts:** 23 September 2026 · **Deadline:** 24 October 2026  
**Ownership:** TCP connections, framing, message encoding/validation, transport workers, and wire specification

## 1. Your mission and working order

Your work makes this statement true: “Each peer receives complete, correctly framed messages, and one broken connection cannot corrupt the rest of the swarm.” Your module moves bytes and reports events; it does not decide which piece is rarest or whether the whole download is complete.

Follow A01–A12. Work first without sockets, then with one connection, then with real storage/scheduling, and finally with the swarm. Most hard bugs are easier to expose using a deliberately fragmented in-memory byte stream than with six running peers.

Read the [master guide](BitTorrent-Lite-Revised-Project-Guide.md) for shared decisions. This standalone plan repeats your essential contract. It contains design guidance rather than a finished implementation: under the team's supplied AI rules, write and understand the core framing, handshake, and peer protocol yourselves.

## 2. Your place in the project

```text
Debargha: validated peer candidates
                   |
Prabhat: connect/send commands and semantic state
                   |
                   v
Your network module -> socket -> remote peer
                   ^
                   |
reader -> framed message event -> Prabhat's coordinator
writer -> sent/failed event ----> Prabhat's coordinator

Rishikesh provides exact piece bytes/lengths through the coordinator.
```

Own `src/protocol.py`, `src/network.py`, their tests, and `docs/protocol.md`. You supply connection-session rules and validation helpers; the coordinator executes semantic phase transitions. Keep transport resource state separate from scheduler state.

## 3. Learn these concepts through small exercises

| Concept | Explain it | Exercise |
|---|---|---|
| TCP byte stream | Sent messages may be split/combined on receive | Feed one frame in three fragments |
| Listening versus connected socket | Listener accepts; connected socket transfers | Identify both objects in a two-peer test |
| Full duplex | One TCP connection supports both directions | Exchange a request each way |
| Framing | Lengths let receiver find message boundaries | Draw prefix/header/payload for a PIECE |
| Network byte order | Both sides interpret integer bytes consistently | Encode a known header length on paper |
| EOF | Empty receive means connection ended, not “try again” | Close sender midway through a payload |
| Thread ownership | One writer prevents frame interleaving | Queue two frames simultaneously |
| Timeout | A bounded wait is not proof of permanent failure | Contrast idle socket and incomplete frame |

Do not use asyncio, a networking framework, BitTorrent library, or a second transport such as UDP for peer traffic. TCP plus threads is enough for this scale.

## 4. Shared version-1 assumptions

- Each peer is a separate process with an ID of 1–32 ASCII letters/digits/underscore/hyphen.
- One source file, 1 byte through 64 MiB, split into 64 KiB pieces.
- SHA-256 hashes are lowercase 64-character hexadecimal strings.
- `file_id` hashes the exact metadata bytes; a different file ID means a different swarm.
- One active connection per remote peer, at most 12 neighbors per process.
- Only the lower lexicographic peer ID initiates; both sides send and receive data on that connection.
- Every process must listen on a reachable local/LAN address. No NAT traversal is planned.
- Request window starts at one and finishes at four per connection.
- One reader and one writer per connection; no other thread writes socket bytes.

Example: `peer-01` initiates toward `seed-01`, but the seeder can still upload to `peer-01`. Alphabetical initiation does not define the direction of file transfer.

## 5. Exact framing and message definitions

### Frame layout

```text
4 bytes: H, unsigned big-endian integer
H bytes: UTF-8 JSON header
B bytes: binary payload, where B = header.payload_length
```

Bounds: 1 ≤ H ≤ 16,384; B must be zero for control messages and exactly the expected piece length for PIECE. Never allocate based on an unchecked declared length. Keep JSON and payload separate; do not base64-encode pieces or decode arbitrary file bytes as text.

Every header includes `type` and integer `payload_length`. Reject wrong types, missing required fields, booleans in integer fields, and invalid values. Protocol version 1 can reject unexpected header fields to catch typos, provided every sender follows that same strict rule; agree this with the team before coding.

### Message table

| Message | Additional fields | Permission/meaning |
|---|---|---|
| HANDSHAKE | `protocol_version`, `file_id`, `peer_id` | Identity/version/swarm check before other state |
| BITFIELD | `pieces` list of integer 0/1 values | Exactly N entries; once initially |
| HAVE | `piece_index` | Advertise one verified stored piece |
| INTERESTED | None | Sender needs something remote owns |
| NOT_INTERESTED | None | Sender currently needs nothing remote owns |
| REQUEST | `request_id`, `piece_index` | Request an entire piece when allowed |
| PIECE | `request_id`, `piece_index` | Binary response with exact piece length |
| CANCEL | `request_id`, `piece_index` | Withdraw queued request response if possible |
| CHOKE | None | Sender revokes permission for new requests |
| UNCHOKE | None | Sender grants permission for requests |
| REJECT | `request_id`, `piece_index`, `reason` | Valid request cannot be served; reason unavailable/busy/choked |

A conceptual request example is `type=REQUEST, payload_length=0, request_id=17, piece_index=2`. The corresponding PIECE echoes ID/index and has 65,536 payload bytes unless piece 2 is the shorter final piece. This is a schema example, not code to implement the protocol for you.

Request IDs increase from 1 to 2^63−1 for each requester on each connection. A responder echoes the incoming request ID; its own outgoing requests have their own sequence. Track direction so identical numeric IDs in opposite directions are not confused. Reconnects get new local connection IDs.

Duplicate REQUEST rule agreed in the master: ignore an identical still-pending request without creating a second upload; reusing the ID for another piece or after its retirement is a protocol error. New IDs must increase; canceled unsent requests may leave gaps. Repeated CANCEL for retired work is harmless. The coordinator applies these semantic rules.

### Layers of validation

1. Framing: prefix, encoded header length, bounded body.
2. Structure: known type, required fields, strict types/ranges, expected piece length.
3. Session: correct handshake/bitfield phase, matching expected peer/file identity.
4. Request state: permission, matching pending request, owned piece, duplicate/stale response.
5. Content: hash and successful storage.

You own 1–2 and supply rules/helpers for 3. Prabhat applies 3–4 in the coordinator. Rishikesh handles 5. Never label a structurally valid PIECE “verified” before storage/hash checks.

## 6. Connection lifecycle

States: CONNECTING → HANDSHAKING → BITFIELD_EXCHANGE → ACTIVE → CLOSED. An incoming accepted socket enters HANDSHAKING. Any failure can close from any state.

Handshake ordering:

1. Initiator sends HANDSHAKE.
2. Acceptor validates version/file/peer identity, rejects self or duplicate connection, and queues its HANDSHAKE then BITFIELD.
3. Initiator validates reply against the expected discovery peer ID and queues BITFIELD.
4. After valid remote bitfield and queued local bitfield, coordinator can enter ACTIVE.
5. Queue later control frames after handshake/bitfield; never reorder them.

Initial interest flags are false; both directions initially choked. A development always-allow policy can send UNCHOKE on activation. The final scheduler chooses upload slots. Your module must not silently bypass those permissions in final tests.

Timeout proposals: connect 3 seconds, handshake 5 seconds, incomplete frame 10 seconds. Idle connections with no frame underway remain eligible; a socket polling timeout is not automatically a disconnect. Record deadlines using monotonic time.

For one socket used by reader/writer threads, set its timeout policy consistently; do not have both threads continuously change a shared socket timeout. If a send times out after a frame may be partially written, close that connection. Retrying the whole frame on the same stream can corrupt framing.

## 7. Events, writer queues, and ownership

Provide nonblocking/bounded command submission. `send_message` returns queued or rejected, not “remote received.” Its local send-token identifies later writer outcomes and cancellation.

| Event | Data |
|---|---|
| CONNECTION_OPENED | Connection ID, direction, endpoint, expected remote ID |
| FRAME_RECEIVED | Connection ID, typed header, immutable payload bytes, receive time |
| FRAME_SENT | Connection ID, send-token, type, request ID if any, timestamp |
| SEND_FAILED | Connection ID, send-token, reason |
| CONNECTION_CLOSED | Connection ID, reason |

Coordinator owns neighbor maps, connection phase, pending requests, bitfields, and upload policy. You own socket handles, transport closure guard, receive buffer, and writer queue. Protect resource closure where reader and writer can race; do not introduce shared writes to scheduler dictionaries.

Suggested bounds: 128 coordinator events and 32 outgoing frames per connection, with at most four accepted uploads per neighbor managed by the coordinator. Use bounded puts and explicit failure handling. If event delivery is saturated, close the offending transport and expose its closed flag to coordinator reconciliation on the next timer tick. Never lose cleanup forever simply because CONNECTION_CLOSED could not be enqueued; agree and test this with Prabhat.

Start with FIFO sending to establish correctness. If adding control priority, allow controls to precede only unsent PIECE jobs, preserve order among controls, and add tests. HANDSHAKE cannot be overtaken by BITFIELD; CANCEL cannot be sent before its own REQUEST. One frame already writing must finish or the entire connection closes.

The standard queue supports synchronized exchange and bounded operations; its `empty()`/`full()` observations are not guarantees about the next operation. Handle actual operation outcomes. See [Python queue documentation](https://docs.python.org/3/library/queue.html).

## 8. Ordered implementation tasks

### A01 — Finish the wire specification before coding

**When:** 23 September.

Write the frame layout, message table, integer/string rules, limits, initial flags, deadlines, and invalid-message behavior. Include one control and one data-frame example. Ask the three owners to trace their boundary, then freeze the version-1 contract.

**Done when:** nobody is guessing field names, length units, or whether a request covers a block or whole piece.

### A02 — Encode/decode frames without sockets

**When:** 24 September. **Dependency:** A01.

Write your codec. Test control messages, binary payloads containing zero/non-UTF-8 bytes, strict validation, and known prefix byte order. Compare against independently constructed fixture expectations, not only encode-then-decode round trips that can share the same bug.

**Done when:** valid frames preserve meaning/bytes and invalid declared sizes fail before large allocation.

### A03 — Handle arbitrary receive fragmentation

**When:** 24–25 September. **Dependency:** A02.

Feed data one byte at a time, prefix split after one/two/three bytes, JSON split mid-character, body split at arbitrary offsets, and several combined frames. Your buffering or exact-read logic must retain enough state to assemble complete frames without losing leftover bytes.

**Done when:** the same logical stream produces exactly the same message sequence under every tested chunking pattern.

### A04 — Establish a real TCP session

**When:** 25 September.

Run two independent processes. Bind/listen/connect; exchange HANDSHAKE and BITFIELD in correct order. Validate expected identity and swarm. Add bounded handshake timeout and EOF behavior. Use Debargha's discovered endpoint when available; a manually configured endpoint is acceptable only as an earlier isolated test.

**Done when:** a real tracker-discovered connection reaches ACTIVE, and wrong file IDs cannot.

### A05 — Transfer one piece with the team

**When:** 26–27 September.

Let Prabhat submit REQUEST and supply an upload response command using Rishikesh's bytes. Report complete PIECE reception without altering payload bytes. Confirm one writer sends all frames. Capture both sides' logs.

**Done when:** independent processes pass G1, with matching stored bytes and hash. A network echo that bypasses storage does not pass G1.

### A06 — Support full file and reciprocal sharing

**When:** 28 September–4 October.

Add HAVE, interest transitions, rejection, and continuous multi-message operation. Demonstrate both ends of one connection uploading and downloading. Coordinate a deterministic downloader-A-to-downloader-B piece transfer. Confirm no premature socket close after the first response.

**Done when:** full-file reconstruction and I02 sharing evidence pass.

### A07 — Add concurrency and limits before scale

**When:** 5–7 October.

Run one reader/writer pair per connection with bounded queues. Enforce connection caps and duplicate remote-ID rejection. Stress simultaneous enqueues; reconstructed frames must never interleave. Verify writer failure becomes a cleanup event and that a slow receiver does not block the entire coordinator.

**Done when:** six downloaders operate while logs and queue counters remain sensible.

### A08 — Implement cancel/write boundary behavior

**When:** 8–9 October.

Queued upload jobs have cancellation flags. Before sending, writer checks if canceled. If cancellation arrives after sending begins, finish the frame. Report job outcome so accepted-work counts can be released once. Do not cut a frame short but keep the connection alive.

A local queued REQUEST can also be withdrawn. If it has already started, coordinator queues CANCEL after it. Coordinate this with Prabhat to prevent expired requests being transmitted later from a forgotten queue.

**Done when:** cancellation-before-start avoids payload; cancellation-after-start preserves framing and the receiver safely handles the late response.

### A09 — Test failures and cleanup

**When:** 9–11 October.

Interrupt connect, handshake, prefix, header, payload, and writer send. Feed unknown types and excessive lengths. Have reader and writer fail almost simultaneously; repeated cleanup must not remove another connection or double-release a request.

Test restart/reconnect with a new connection ID. Old queued events cannot affect the new session. Give Prabhat a transport-closed reconciliation hook for queue-saturation failures.

**Done when:** one peer disappearance does not crash survivors, leave immortal reservations, or hang shutdown.

### A10 — Finish choking messages and counters

**When:** 12–17 October.

Your transport faithfully conveys CHOKE/UNCHOKE/REJECT while Prabhat decides slots. Verify controls are ordered and active frames finish. Count a message as sent only after the full frame write succeeds. Count completed PIECE payload separately; do not invent bytes sent for a failed partial write.

**Done when:** free-rider and slot tests can be explained with reliable logs/counters; feature freeze reached.

### A11 — Support experiments and write protocol section

**When:** 18–21 October.

Help diagnose malformed frames, unexpected connection churn, or counter discrepancies. Avoid changing protocol mid-matrix; if a bug requires a change, record revision and rerun affected comparisons. Write the report's framing, messages, transport, timeout, and failure behavior sections.

### A12 — Rehearse live explanation and release

**When:** 22–24 October.

On a fresh setup, show one handshake, explain a frame byte by byte, demonstrate a fragmented-read test, and stop a connection mid-transfer. Change a validation limit live, predict its result, and run the test.

## 9. Required tests with explicit outcomes

| ID | Input/action | Expected behavior |
|---|---|---|
| A-T01 | Known header length | Four-byte unsigned big-endian prefix |
| A-T02 | Prefix/header/body fragmented | Exactly one frame after enough bytes |
| A-T03 | Three concatenated frames | Three ordered events, no lost remainder |
| A-T04 | Binary bytes with invalid UTF-8 | PIECE payload preserved as bytes |
| A-T05 | Zero/oversized header length | Close before unbounded read/allocation |
| A-T06 | Negative/excessive payload length | Reject |
| A-T07 | Boolean/non-integer index or ID | Reject |
| A-T08 | Wrong version/file/expected peer ID | No ACTIVE state |
| A-T09 | BITFIELD wrong length or repeated | Protocol failure according to spec |
| A-T10 | EOF in prefix/header/body | Controlled close, no partial message event |
| A-T11 | Idle read polling timeout | No false partial-frame failure |
| A-T12 | Incomplete frame exceeds deadline | Connection closes |
| A-T13 | Multiple producers queue frames | Single writer preserves frame integrity |
| A-T14 | CANCEL queued/not yet started | Upload skipped, accounting released |
| A-T15 | CANCEL after write begins | Complete frame or connection close, never truncated live stream |
| A-T16 | Failed partial send | Close; do not replay frame on same stream |
| A-T17 | Reader and writer both fail | Safe close; semantic cleanup once |
| A-T18 | Reconnect and stale old event | New connection unaffected |
| A-T19 | Event queue saturation | Bounded failure, eventual coordinator cleanup |

Master N01–N05 map to the framing/session tests. C01/C02 require joint review with Prabhat. Prefer fake streams/socket pairs for parser tests and real localhost processes for integration evidence.

## 10. Working with the other members

| Partner | Need from them | Give them |
|---|---|---|
| Rishikesh | Exact piece lengths, source bytes, invalid fixtures | Unmodified received bytes; transport errors distinct from hash failures |
| Debargha | Validated peer endpoints and launch readiness | Connection status, message counts, per-peer logs |
| Prabhat | Command/event agreement, upload job accounting, session-state caller | Transport commands, events, validation helpers, closed-resource status |

If scheduler integration is blocked, keep testing frames, malformed inputs, closure, and simultaneous send/receive using small test peers. Do not implement a second rarest-first scheduler inside networking to bypass the missing handoff.

## 11. Debugging guide

- **JSON works for small tests but fails under load:** inspect partial reads, byte-count calculation, and multiple writers.
- **Receiver waits forever:** compare declared body length to actual bytes; verify handshake and frame deadlines.
- **Frames after CANCEL are unreadable:** someone truncated a started frame.
- **Every peer pair has two connections:** check lower-ID initiation and active-ID duplicate handling.
- **Only one direction transfers:** inspect interest/choke flags; TCP itself is full duplex.
- **Pipeline fails but single request works:** inspect frame buffering, request correlation, writer ordering, and pending counters.
- **Timeout corrupts next message:** partial send was replayed on the same stream.
- **Shutdown hangs:** wake writer queue, close socket to unblock reader, signal listener and join with a bound.

## 12. Viva and final sign-off

| Question | What to explain |
|---|---|
| Does one send equal one receive? | No; TCP is a byte stream, so framing is our responsibility |
| Why `sendall`? | It attempts the complete buffer or raises; it still does not prove remote application acceptance |
| Can you replay a failed partial frame? | Not blindly on the same connection; close and recover at request level |
| Why one writer? | Prevent interleaved frame bytes from concurrent senders |
| What does EOF mean? | Remote connection ended; incomplete frame cannot be accepted |
| Why include file ID? | Prevent exchanging pieces between different metadata/swarm definitions |
| Why initial bitfield then HAVE? | Snapshot first, incremental updates afterward |
| Why a connection ID and peer ID? | Peer identity may persist; each connection lifetime is distinct |
| Is CANCEL guaranteed to save bytes? | No; it only avoids work not already started |
| Why no binary packed message types? | JSON fields simplify inspection; raw payload preserves binary data without base64 overhead |
| Is this production BitTorrent? | No; custom version-1 framing and whole-piece requests |

Read the relevant [Python socket reference](https://docs.python.org/3/library/socket.html) for exact send/receive/timeout behavior. Focus on APIs used in your code.

Final checklist:

- [ ] Complete wire spec matches actual encoder/decoder.
- [ ] Fragmentation, coalescing, limits, and binary payload tests pass.
- [ ] Handshake/bitfield sequence and identity checks work.
- [ ] One writer per socket, bounded resources, no indefinite coordinator blocking.
- [ ] CANCEL and partial-write behavior preserve framing.
- [ ] Disconnect/reconnect/shutdown cleanup is tested.
- [ ] Logs and counters support the experiment definitions.
- [ ] Your report section, contribution, and AI-use record are reviewed.
- [ ] You can trace an actual frame and make a small live protocol-validation change.
