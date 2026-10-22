# Debargha Bhadra — individual execution plan

**Roll number:** 2405575  
**Project:** CS-30003 P8, BitTorrent-lite, CSE 33  
**Revision:** 22 September 2026 · **Work starts:** 23 September 2026 · **Deadline:** 24 October 2026  
**Ownership:** tracker, discovery client, process harness, experiment collection, and plots

## 1. Your outcome and starting point

Your work makes two statements true: “A peer can discover live candidates in the correct swarm,” and “The team can reproduce its results using recorded configurations and raw evidence.” The tracker is not a file server and must not become a central piece scheduler.

Work through D01–D11. Start with tracker contracts and independent HTTP tests, then provide a usable discovery client to Anik/Prabhat early. Build the experiment harness incrementally after discovery works. You do not need a web interface, database, framework, or cloud service.

Read the [master guide](BitTorrent-Lite-Revised-Project-Guide.md) for shared contracts. This plan assumes no task is complete until you demonstrate it. The supplied AI rules permit explanatory/test/documentation assistance, but you write and understand the core tracker mechanism yourself.

## 2. Position in the overall system

```text
Peer listens on TCP port
          |
          v
Discovery worker --HTTP announce--> Your tracker membership dictionary
          ^                                      |
          +----------peer candidates-------------+
          |
Coordinator -> Anik's connection logic -> peer-to-peer piece transfer

Your experiment harness starts/stops processes and collects logs.
It never supplies file pieces or makes live selection decisions for peers.
```

A tracker response contains candidates, not guarantees. A peer may disappear immediately afterward. Anik handles connection failure; the coordinator continues with other sources.

## 3. Files, tools, and deliverables

Primary files: `src/tracker.py`, `src/tracker_client.py`. Supporting ownership: launch/collection/plot scripts under `experiments/`, tracker tests, `docs/experiment-method.md`, and tracker documentation.

Use Python standard-library HTTP server/client, dictionaries, JSON, monotonic timing, logging, CSV, and `subprocess` for the harness. Use pytest for tests and matplotlib for graphs. pandas and NumPy are unnecessary for the planned summaries.

Expected deliverables:

- Announce contract and documented errors.
- Tracker registration, update, discovery, stopped handling, and expiry.
- Discovery worker with bounded HTTP timeout and retry.
- Reproducible multi-process launcher with unique resources.
- Configuration manifest and event/summary collection.
- Experiment matrix, failure/free-rider setup, raw data, plots, and methodology section.

## 4. Tracker contract to implement

### Endpoint and request

Proposed endpoint: `POST /announce`, JSON body. Required fields:

| Field | Rule |
|---|---|
| `file_id` | Lowercase 64-character SHA-256 hex, from exact metadata bytes |
| `peer_id` | 1–32 ASCII letters/digits/underscore/hyphen; unique running peer |
| `listen_port` | Integer 1–65,535, not a boolean |
| `event` | `started`, `update`, `completed`, or `stopped` |

Use source IPv4 from the HTTP connection for this controlled LAN/localhost project. Do not accept a remote-supplied path or arbitrarily trust an advertised IP. Listening bind address `0.0.0.0` is not a usable peer destination; the recorded connection source is.

Use a small request limit, proposed 4 KiB. Require a valid bounded Content-Length; reject unsupported body transfer encodings in this simple handler. Check content type and valid UTF-8 JSON. No authentication is planned: document the trusted-lab assumption rather than implying IDs cannot be spoofed.

### Successful response

Response JSON contains `interval` (5 seconds) and `peers`, a list of records with `peer_id`, `ip`, and `port`. Return only the same file's live peers and omit the requester. Do not return bitfields, source paths, or piece data.

Suggested errors: 400 malformed/invalid fields, 404 unknown path, 405 unsupported method, 411 missing Content-Length, 413 excessive body, 415 unsupported media/transfer encoding. You may consolidate validation errors as 400 if the team prefers fewer categories, but document and test the chosen behavior consistently. Always produce a bounded response with explicit content length; close after response is simplest.

### Membership dictionary

Key: `(file_id, peer_id)`. Value: source IP, listening port, last-seen monotonic time, optional completed flag.

- `started` and `update`: insert or refresh, including after tracker restart.
- `completed`: insert/refresh and mark complete if tracked.
- `stopped`: remove if present; repeated removal is harmless.
- Expired means age **at least 20 seconds**; remove before generating a response.
- One peer ID has at most one current endpoint per file. Refreshing an endpoint replaces the record.
- A duplicate active peer ID is an invalid operational setup; the harness must prevent it. Tracker identity is not authenticated.

Use a single-threaded HTTP server for tiny operations and an ordinary dictionary. Bound request-read time so a stalled client does not hold it forever. Keep file operations and heavy work out of the handler. If you later choose a threaded server, introduce appropriate state synchronization and tests; do not add it without a reason.

## 5. Discovery worker contract

The peer coordinator must not perform blocking HTTP calls. Your worker announces and retries, then posts events to the coordinator's bounded event queue.

Inputs: tracker URL, file ID, peer ID, actual bound listening port, stop signal, and completion/status updates. Outputs: PEERS_DISCOVERED(file ID, peer records) or TRACKER_ERROR(category, time).

Behavior:

1. Start announcing only after the listener binds successfully.
2. Announce at startup and every five seconds after success.
3. Use a three-second HTTP timeout; bound response size, proposed 64 KiB.
4. On failure retry after 2, 4, then at most 10 seconds; reset after success.
5. Validate response structure, interval, identifiers, IPs, and ports before passing records onward. Do not allow a nonsense interval to cause a tight request loop.
6. Report failures without crashing established peer connections.
7. Announce completed status after the coordinator's final verified completion.
8. Make stopped best effort. Network failure must not prevent exiting.

Use an interruptible stop wait instead of a long uninterruptible sleep. Rate-limit repeated console errors; retain structured events. Protect the worker's own tiny status communication using a queue/Event rather than editing scheduler dictionaries.

## 6. Ordered implementation tasks

### D01 — Freeze examples before server code

**When:** 23 September.

Write one valid announce, one successful peer-list response, one stopped event, and error examples. Use placeholder file IDs only in documentation; executable fixtures must use well-formed 64-character hex values. Agree field names with Anik and Prabhat.

**Done when:** both can explain the exact response they will consume.

### D02 — Build and test membership operations

**When:** 24 September. **Dependency:** D01.

Implement dictionary operations separately from HTTP handling so expiry can use a fake clock. Test registration, refresh, file isolation, self-exclusion, endpoint refresh, stop, and expiry boundary. Ensure `update` inserts missing records after a tracker restart.

**Done when:** operations have deterministic tests without live network or real 20-second sleeps.

### D03 — Add HTTP parsing and responses

**When:** 24–25 September. **Dependency:** D02.

Connect the handler to membership operations. Validate before mutation. Test malformed JSON, wrong fields, bad ports, oversize bodies, unexpected paths/methods, and partial request body with deadline. HTTP errors should leave the server usable for the next request.

**Done when:** two test clients announce and each receives the expected other peer.

### D04 — Provide a real discovery worker

**When:** 25–26 September. **Dependency:** D03.

Implement the client and worker behavior above. Deliver validated peer records to Anik's connection flow via Prabhat's coordinator. Use real local listeners as candidates; a fake endpoint proves parsing but not usable discovery.

**Done when:** one peer announces and another reaches its actual listening socket through your response.

### D05 — Demonstrate outage and restart behavior

**When:** 26–29 September.

Start the peer worker with tracker unavailable; later start tracker and observe registration. Stop tracker after connections form and ensure worker failures do not pause actual piece handling. Restart with an empty table and confirm periodic updates restore entries.

**Done when:** retries are bounded, coordinator remains responsive, and shutdown is prompt even during an outage.

### D06 — Build the smallest process launcher

**When:** 27 September–1 October.

Start only tracker, one seeder, and one downloader first. Use `subprocess` with an argument list, not a concatenated shell command. Capture process handles and redirect stdout/stderr to separate run files so unconsumed pipes do not block children.

Allocate distinct ports, IDs, and storage paths. Detect readiness from an explicit signal/log event or successful check; do not assume a fixed sleep proves readiness. Preserve logs on any failure. Stop only recorded child processes; never kill every Python process on the machine.

**Done when:** the team can reproduce G1/G2 from a recorded configuration without hand-editing six files.

### D07 — Scale and add run manifests

**When:** 2–7 October.

Extend to six downloaders and one/two seeders. Confirm the listener cap supports the largest planned topology. Verify unique peer directories and an empty tracker table for each run. Record Python version, operating system, file hash, Git revision, random seed, limits, IDs, ports, and selected strategy.

**Done when:** required scale runs finish or fail with an explicit reason, clean child shutdown, and complete logs.

### D08 — Add controlled failure/free-rider scenarios

**When:** 8–15 October.

Failure: terminate only a designated downloader after its progress event reaches 25%, retaining a complete seeder. Record trigger time and target. If the trigger is never reached before timeout, label the scenario not executed/failed; do not pretend a failure was injected.

Free rider: launch one downloader with the agreed zero-upload-slot mode. Confirm uploaded PIECE payload is zero, rather than merely assuming the flag worked. The other five downloaders remain cooperative.

**Done when:** each scenario changes one intended condition and logs show the actual injected behavior.

### D09 — Pilot measurement definitions

**When:** 16–17 October.

Pick one startup timing method with the team. Simplest is a consistently timed launch sequence including startup; a release barrier is useful only if implemented reliably. Do not mix methods in one graph. Run all experiment types once, verify units/counters, and identify runs too short to interpret.

If introducing an upload cap, it must be shared per peer across its connections, implemented/tested with Anik/Prabhat and applied consistently. It is application-level shaping, not a claim about physical network bandwidth. Avoid this addition unless the pilot justifies it.

**Done when:** the matrix can be run unchanged and each CSV field has one unambiguous meaning.

### D10 — Run the matrix and create graphs

**When:** 18–21 October.

Use nine distinct configurations with at least three repeats: four swarm sizes (L=2,4,6,8; S=1), two extra selection strategies at L=6 (baseline rarest-first plus random and sequential), S=2 at L=6, one free-rider condition, and one failure condition. Identical baseline observations may serve multiple comparisons only if configuration/revision/timing match.

Keep a raw observation table; plot mean with variation and retain failures. Rishikesh independently verifies outputs. Discuss selection/policy effects with Prabhat and counter anomalies with Anik.

**Done when:** each figure can be regenerated from saved raw data and matches its caption.

### D11 — Document and rehearse

**When:** 22–24 October.

Write tracker design, experiment method, measurements, and results sections. Rehearse starting the swarm from a clean setup. Explain one tracker outage, one measurement limitation, and one result that did not match an initial expectation.

## 7. Measurement definitions you must preserve

Let L be initially empty downloaders and S initial complete seeders. Total peer population is L+S; tracker excluded.

| Measurement | Definition |
|---|---|
| Per-peer completion | Final verified output time minus that peer's chosen start |
| Distribution time | Latest required final verification minus common run start |
| Useful per-peer throughput | Source bytes / per-peer completion seconds |
| Aggregate useful throughput | L × source bytes / distribution seconds, only for all-L completed runs |
| Message count | Completed application frames counted at sender |
| Uploaded payload | Completed PIECE payload bytes, excluding header/control |
| Verified downloaded bytes | Newly accepted and stored piece bytes, without duplicates/corruption |
| Availability | Per-piece count of live owners, reconstructed offline from logs |

For killed-peer runs, report survivors as a different completion population. Compare the same survivor subset in baseline and failure runs where appropriate. Do not use the full-L aggregate formula for a run where one intended downloader was killed and did not finish.

Keep local elapsed timing monotonic. Do not subtract unrelated hosts' monotonic values. Run the core matrix on one machine first and call it localhost results. For LAN timing use a controller-based origin/notifications and disclose timing uncertainty.

## 8. Proposed result schema and validation

### Run-level CSV

`run_id`, `revision`, `environment`, `file_sha256`, `file_bytes`, `piece_bytes`, `L`, `S`, `strategy`, `window`, `upload_slots`, `upload_cap`, `seed`, `startup_method`, `scenario`, `expected_completers`, `actual_completers`, `duration_s`, `status`, `failure_reason`.

### Peer-level CSV

`run_id`, `peer_id`, `role_at_start`, `completion_s`, `final_hash_ok`, `verified_download_bytes`, `uploaded_payload_bytes`, `messages_sent`, `requests_sent`, `retries`, `hash_failures`, `exit_reason`.

Leave undefined completion values empty, not zero. A failed process is not an instant download. Record timeout/failure statuses instead of dropping rows. Check expected row count, nonnegative counters, unique `(run_id,peer_id)`, and agreement between completion status and final hash evidence.

## 9. Tests and operational checks

| ID | Scenario | Expected result |
|---|---|---|
| D-T01 | Register two peers same file | Each sees the other, not itself |
| D-T02 | Same peer refresh | One record, updated timestamp |
| D-T03 | Two file IDs | No cross-swarm discovery |
| D-T04 | Age 19.9 s versus 20 s | Live before boundary; expired at boundary |
| D-T05 | Stopped repeated | Removal remains harmless |
| D-T06 | Invalid body/port/types | Error, no invalid table mutation |
| D-T07 | Slow/incomplete HTTP body | Handler returns/fails within bound; server recovers |
| D-T08 | Tracker absent/restarted | Bounded retry, eventual re-registration |
| D-T09 | Stop discovery during retry | Prompt clean worker exit |
| D-T10 | Child crashes in launcher | Logs preserved and owned children cleaned up |
| D-T11 | Port already in use | Clear launch error, no false readiness |
| D-T12 | Failed run in analysis | Counted as failure, not silently omitted |

Master equivalents: T01–T03 and system Y01/Y02/Y04/Y05. Your harness also helps collect I01/I02 evidence, but the owners of peer behavior must review those results.

## 10. Handoffs and fallback work

| Partner | You provide | You receive |
|---|---|---|
| Anik | Validated peer endpoints, tracker behavior, listener launch logs | Readiness, connect outcomes, protocol counters |
| Prabhat | Discovery events, scenario configuration, run timing | Completion, progress, policy/free-rider status |
| Rishikesh | Per-peer output paths and run IDs | Source fixture, metadata, independent output verification |

If peer code is not ready, test tracker with fake clients, build manifest/CSV parsing against documented sample logs, and prepare plots with clearly labeled synthetic data. Remove synthetic results from actual findings; they only validate your analysis tooling.

## 11. Debugging and viva preparation

Common faults: advertising before bind succeeds; storing port strings without validation; failing to re-register after restart; timestamp based on wall clock changes; blocking HTTP in the coordinator; mixed old run directories; process pipes filling; counting both sent and received messages; silently discarding failures.

| Viva question | Key explanation |
|---|---|
| Why a tracker? | Supplies candidate peers without manual pairwise configuration |
| Does it distribute the file? | No; content travels directly between peers |
| Why HTTP? | Simple inspectable request/response for membership; underlying transport is TCP |
| What work is yours versus the library's? | HTTP parsing is library support; membership, validation, expiry, discovery are our mechanism |
| Why expire entries? | Crashed peers may never announce stopped |
| Is expiry proof of death? | No; it is a timeout-based heuristic |
| Why source IP plus listen port? | The TCP source port of an HTTP call is not the peer's listening port |
| What if tracker restarts? | Updates recreate in-memory membership; established peer connections need not stop |
| Why not a database? | Small short-lived membership table; periodic announces rebuild it |
| Can a free rider still finish? | Yes; report observed behavior, not a guaranteed punishment |
| Why repeat runs? | Scheduling and network timing vary; one observation is weak evidence |
| What does localhost measure? | This implementation on shared local resources, not WAN scalability |

Live exercises: change expiry to ten seconds and demonstrate it with a fake clock; reject a malformed port; add one extra peer to the launcher without port collisions; explain a failed-run row and recalculate one throughput value manually.

## 12. Final sign-off

- [ ] Tracker membership/expiry and HTTP validation tests pass.
- [ ] Discovery worker cannot block coordinator progress.
- [ ] Existing transfers survive tracker outage in evidence.
- [ ] Launcher owns and cleans only its child processes.
- [ ] Six-downloader and two-seeder runs are reproducible.
- [ ] Actual failure/free-rider behaviors are confirmed in logs.
- [ ] Raw observations, failure counts, units, and graph scripts are preserved.
- [ ] Rishikesh's independent hash checks agree with completion records.
- [ ] Your report sections and AI-use entries are complete.
- [ ] You can run and explain your contribution during viva.

Selective reference: [Python HTTP server documentation](https://docs.python.org/3/library/http.server.html). Use its HTTP support while keeping the tracker algorithm your own. This is a controlled teaching service, not a production internet tracker.
