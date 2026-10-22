# Part 2 — Standalone request pipeline and lifecycle library

## What to build

Build a Python library that manages several outstanding data requests, identifies their responses, expires stalled work, and releases resources correctly. A **piece** is simply a numbered work item; the library neither downloads nor stores its bytes.

Start in an empty folder. This document is the complete specification. No existing project, earlier implementation, other plan, network connection, or external service is needed. Use Python 3.10+ and only the standard library. All types and implementation files belong to this package.

Allocate **20 estimated effort units**, approximately one quarter of the four standalone packages: configuration/models 3, pipeline admission/fairness 5, lifecycle/deadlines 5, competing-request accounting 4, CLI/documentation 3. These are relative estimates, not promised hours. **Testing is reserved for Part 6 and is not included.**

## Deliverable and boundaries

Create this independently usable package:

```text
bittorrent_lite/scheduling/request_pipeline/
    __init__.py
    __main__.py
    models.py
    manager.py
    example.json
    README.md
```

The library accepts explicit connection descriptions and numbered candidates, then returns request records and cleanup outcomes. Its command-line program executes local JSON actions and prints JSON results. It requires no transport adapter or disk-store implementation.

Implement admission, per-connection windows, fair filling, deadlines, exact request matching, ownership accounting, and explicitly authorized duplicate requests. Selection strategy, retry delays, provider reputation, hash checking, disk writes, uploads, sockets, and integration are outside this package. A caller supplies facts such as “this response passed verification”; the package does not call another component to obtain them.

## Complete data model

Define these types locally, using dataclasses and enums:

- `RequestKey(connection_id: int, request_id: int, piece_index: int)`, frozen and hashable.
- `RequestView(key, provider_id: str, queued_at: float, sent_at: float | None, deadline: float | None, verifying: bool)`, frozen; returned records are snapshots.
- `Outcome(kind: str, key: RequestKey, reason: str, at: float)`, frozen. Kinds are `completed`, `invalid`, `expired`, and `canceled`.
- Piece state enum: `MISSING`, `REQUESTED`, `VERIFYING`, `HAVE`.
- Frozen `PipelineConfig(window=4, response_timeout=10.0, send_confirm_timeout=5.0, max_connections=10, max_copies=2)`.

Construct `PipelineManager(num_pieces, *, initially_owned=(), config=None)`. `num_pieces` is a positive integer; valid piece indices are `0 <= index < num_pieces`. The constructor copies and validates initially owned indices. It does not open any file.

Connection IDs are positive integers and cannot be reused during a manager's lifetime. Provider IDs are nonempty strings. Allow only one active connection per provider. Request IDs are assigned globally by the manager, increase from 1, and are never reused. Reject booleans wherever an integer ID/count is required.

`max_connections` limits active connections, not the lifetime number of registrations. Registration raises `ValueError` without changing state if that cap is full, a connection ID was ever registered before, or its provider already has an active connection. Disconnect frees an active slot but never makes its old connection ID reusable.

Each connection stores its provider ID, a copied set of available piece indices, and two explicit input permissions: `interested` and `unchoked`. Both start false. `unchoked=True` means this source permits us to request data. These are supplied values, not a dependency on a permission-policy implementation.

Keep pending records indexed by full key; piece reservations indexed by piece to a set of keys; and a per-connection outstanding count. Queued, sent, and verifying requests all occupy slots. Store owned pieces separately from pending work.

All time arguments are finite, nonnegative monotonic seconds supplied by the caller. Methods using `now` reject time going backward globally. A delayed `confirm_sent` may contain a historical `sent_at`, but it cannot precede that request's enqueue time or exceed its `now`. Validate a call completely before mutating state.

Validate positive integer configuration bounds, window 1–4, max copies 1–2, and positive finite timeouts. Invalid programmer inputs raise `ValueError`; unknown event request keys return a harmless empty/false result. No method sleeps or reads the wall clock.

## Exact public API

```python
register_connection(connection_id, provider_id, *, now) -> None
set_available(connection_id, piece_indices, *, now) -> None
set_permissions(connection_id, *, interested, unchoked, now) -> tuple[Outcome, ...]

reserve(connection_id, piece_index, *, now,
        allow_duplicate=False) -> RequestView | None
fill(candidate_orders, *, now) -> tuple[RequestView, ...]
confirm_sent(key, *, sent_at, now) -> bool
start_verification(key, *, now) -> bool
finish_verification(key, *, valid, now) -> tuple[Outcome, ...]

reject(key, *, now) -> tuple[Outcome, ...]
send_failed(key, *, reason, now) -> tuple[Outcome, ...]
cancel(key, *, reason, now) -> tuple[Outcome, ...]
disconnect(connection_id, *, now) -> tuple[Outcome, ...]
expire(*, now) -> tuple[Outcome, ...]
snapshot() -> dict
```

For connection configuration/reservation, an unknown or inactive connection raises `ValueError`. A repeated disconnect returns an empty tuple. `candidate_orders` is a mapping from active connection IDs to sequences of distinct in-range piece indices, ordered as the caller prefers. A source need not advertise every listed candidate; unavailable indices are simply ineligible.

Outcomes are returned directly to the caller; do not create a hidden unbounded event queue. Request creation returns a record, not evidence that bytes were sent. `None` from reserve means the valid request is presently ineligible or capacity is full.

## Implementation sequence

### 1. Implement admission and fair window filling

A normal reservation requires active source, both permissions true, source availability, an unowned/unreserved piece, and a free source slot. Reserve atomically before returning its RequestView. Mark the piece REQUESTED and charge one slot. With 10 connections and window four there can be at most 40 live requests.

`fill` performs normal reservations only. Maintain a rotating source cursor across calls, starting from sorted active IDs on the first call. Attempt one candidate per source per round, then repeat while progress is possible. Within a source use the provided candidate order. Skip ineligible candidates, never change their ranking, and stop when every remaining candidate is blocked or all windows are full. It must terminate without waiting for new input.

Availability replacement copies caller data and affects future reservations; do not cancel an existing request solely because an advertisement changes. If either permission changes from true to false, cancel unanswered requests on that connection, retaining work already VERIFYING. This operation returns those cancellation outcomes.

### 2. Implement deadlines and exact matching

The initial state is queued with no response deadline. `confirm_sent` sets sent time and `deadline = sent_at + response_timeout` once. Repeated confirmations do not extend the deadline. While VERIFYING, a first valid confirmation may fill `sent_at` but must not restore a deadline.

`expire(now)` removes unsent, non-verifying requests whose queue age is at least five seconds, with reason `send_unconfirmed`. It removes sent, non-verifying requests at or beyond their response deadline, with reason `response_timeout`. Use configured values rather than literals. It returns expiration outcomes without creating replacement requests.

Always match all three key fields. A late rejection, response notification, send failure, or timeout for a removed request cannot affect its replacement. Removal decrements the source count once and clears only that key from the piece reservation set.

### 3. Support explicit competing requests safely

`allow_duplicate=True` permits a second reservation only when a piece already has one pending request, the configured cap allows two, the source/provider differs, the piece is not owned or VERIFYING, and ordinary source capacity/permission rules pass. With no existing reservation, treat it as a normal reservation. A third copy is always refused.

This flag is a complete explicit input; the manager does not need an endgame or recovery policy to function. It does not decide when redundancy is worthwhile.

`start_verification` accepts a matching live response even if send confirmation has not arrived. Permit only one verifying request per piece. Keep its reservation and source slot; clear its deadline. A concurrent candidate's verification attempt returns false without deleting its pending record.

Starting verification again for the same already-verifying request also returns false. `finish_verification` for an existing request that is not in VERIFYING returns an empty tuple without changing its state; unknown keys behave the same way.

`finish_verification(valid=True)` requires the matching verifying record. Mark the piece HAVE, return one completed outcome for the winner, and cancel/remove all other requests for that piece with reason `another_request_completed`. Ownership changes once. `valid=False` removes only that request with an invalid outcome; another pending request keeps the piece REQUESTED, otherwise it becomes MISSING.

The `valid` value must be an actual boolean. It represents a trusted caller-reported result; this package does not perform integrity checking or assume a particular hash algorithm. If verification was canceled or disconnected earlier, its late result is ignored.

### 4. Complete cleanup and state invariants

`reject` and `send_failed` remove an unanswered matching request and return a canceled outcome with the supplied/stable reason. Ignore either event for a request already VERIFYING. `cancel` explicitly cancels any matching state, including verification. Disconnect cancels all requests for that connection, removes its availability, and prevents reuse of its ID.

After every mutation derive a piece's aggregate state in this order: HAVE if owned; otherwise VERIFYING if a verifying record exists; otherwise REQUESTED if any reservation survives; otherwise MISSING. Removing one competing request must never erase another's reservation or decrement another source's count.

All manager calls belong to one owner thread. The library creates no threads and makes no callbacks while changing state. This keeps it independently usable without locks, executors, or a surrounding event loop implementation.

### 5. Expose bounded, useful output

`snapshot()` returns fresh JSON-compatible records: owned indices; piece-state counts; connection identity, availability and permissions; pending RequestViews; outstanding counts; and cumulative issued/completed/invalid/expired/canceled counts. Serialize keys as explicit fields in records, not tuple dictionary keys. Do not return live sets/dataclasses or retain per-event history. Keep retired connection IDs for reuse prevention; document this session-lifetime set rather than claiming unlimited reconnects use constant memory.

## Standalone command and input

Provide `python -m bittorrent_lite.scheduling.request_pipeline --input bittorrent_lite/scheduling/request_pipeline/example.json`. The input is a JSON object with `num_pieces`, optional `initially_owned`, optional config fields, and `actions`. Each action uses one API method name in `op` plus its named arguments. Request keys are objects with the three integer fields. Reject unknown fields/operations with an action number and exit code 2; process no later actions.

The supplied example must be fully local:

```json
{
  "num_pieces": 3,
  "actions": [
    {"op":"register_connection","connection_id":1,"provider_id":"source-A","now":0},
    {"op":"set_available","connection_id":1,"piece_indices":[0,1,2],"now":0},
    {"op":"set_permissions","connection_id":1,"interested":true,"unchoked":true,"now":0},
    {"op":"reserve","connection_id":1,"piece_index":0,"now":0},
    {"op":"confirm_sent","key":{"connection_id":1,"request_id":1,"piece_index":0},"sent_at":1,"now":1},
    {"op":"expire","now":11}
  ]
}
```

Print each action's result and the final snapshot. For `fill`, JSON source keys are decimal strings converted strictly to positive integers. This CLI is an ordinary way to use the library, with no assertions, test runner, socket, or external data required.

## Completion criteria

Deliver the complete importable package, runnable CLI, example input, and README explaining every API and output. There must be no unresolved placeholder, missing adapter, project import, or requirement to consult other code. The delivered behavior includes four-slot filling, exact timeout/cancellation accounting, explicit bounded duplicates, and correct winner ownership.

Do not add unit/integration bittorrent_lite.tests, test matrices, benchmarks, swarm experiments, or project wiring to this work. Those activities are outside this standalone plan; testing remains Part 6.
