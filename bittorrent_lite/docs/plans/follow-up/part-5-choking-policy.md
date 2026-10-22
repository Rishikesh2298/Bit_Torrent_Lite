# Part 5 — Standalone upload-permission policy

## Purpose and independence

Build a new Python 3.10+ standard-library-only package named `bittorrent_lite.scheduling.choking_policy` in an empty folder. It decides which connected peers may receive uploads from the local client. It produces permission-change intents; it never opens sockets, transfers bytes, reads files from another application, or sends protocol messages.

This document supplies the entire development contract. No repository checkout, previous implementation, sibling plan, or existing project types are prerequisites. All input is supplied through this package's API or its local JSON-lines command-line interface. Implement only this package and its documentation. Wiring it into an application is outside this assignment.

Budget: **20 relative effort units**, approximately one quarter of the proposed independently implementable development work. These are planning weights, not hours or guaranteed equal implementation times. Testing, benchmarks, and bittorrent_lite.experiments belong to **Part 6** and are excluded here.

## Definitions and configuration

“Allowed” always means **the local client permits upload to that remote peer**. Remote permission for us to download is unrelated. An interested peer says it currently wants data from us. A contribution event means that the caller has already verified that the local client received useful bytes from that peer; this package performs no integrity verification.

Use a frozen `Config` dataclass with these defaults:

| Field | Default | Validation |
| --- | --- | --- |
| `max_peers` | 128 | positive integer |
| `max_slots` | 2 | integer from 2 through `max_peers` |
| `selection_interval` | 5.0 | finite, positive seconds |
| `optimistic_interval` | 15.0 | finite and at least `selection_interval` |
| `contribution_window` | 5 | positive whole seconds |
| `confirmation_timeout` | 10.0 | finite, positive seconds |
| `diagnostic_capacity` | 128 | positive integer |
| `random_seed` | 0 | integer |

Reserve **one** of `max_slots` for optimistic selection; the remaining slots are regular selections. Thus the default is one regular plus one optimistic peer, never two regular peers plus an extra optimistic peer. Empty slots are permitted.

Every operation takes a caller-supplied `now: float` in seconds. Values must be finite, nonnegative, and nondecreasing across all operations on an instance. Equal timestamps are allowed. No wall clock, sleeps, timer threads, or background work are permitted. All calls are synchronous and single-threaded.

## Package-owned models and API

Define the following public frozen dataclasses; collections in returned models must be tuples:

```python
PeerInfo(peer_id: str, interested: bool = False)
PermissionIntent(token: str, peer_id: str, allow: bool, issued_at: float)
Diagnostic(code: str, peer_id: str | None, at: float)
PeerSnapshot(peer_id: str, interested: bool, desired: bool,
             confirmed: bool, reserved: bool, recent_bytes: int,
             allowed_seconds: float, pending: PermissionIntent | None)
Snapshot(now: float, upload_enabled: bool, seeder: bool, closing: bool,
         closed: bool, peers: tuple[PeerSnapshot, ...],
         regular: tuple[str, ...], optimistic: str | None,
         diagnostics: tuple[Diagnostic, ...])
Decision(intents: tuple[PermissionIntent, ...], state: Snapshot)
```

Implement `Policy(config: Config = Config())` with these exact methods:

```python
connect(peer: PeerInfo, now: float) -> None
disconnect(peer_id: str, now: float) -> None
set_interested(peer_id: str, interested: bool, now: float) -> None
record_contribution(peer_id: str, verified_bytes: int, now: float) -> None
set_seeder(seeder: bool, now: float) -> None
set_upload_enabled(enabled: bool, now: float) -> None
tick(now: float) -> Decision
acknowledge(token: str, applied: bool, now: float) -> bool
snapshot(now: float) -> Snapshot
shutdown(now: float) -> None
reset(now: float) -> None
```

`peer_id` must be a nonempty string of at most 128 characters. IDs are opaque, case-sensitive labels. Duplicate connections raise `ValueError`; unknown IDs raise `KeyError`, except repeated disconnects are harmless. Connecting above capacity raises `OverflowError`. Booleans must be actual booleans; byte counts must be positive integers, excluding booleans, no greater than 16,777,216 per event. Invalid arguments leave state unchanged.

New peers start with desired and confirmed permission false, zero contribution, and no pending command. Uploading starts enabled; seeder mode starts false. Only `tick` creates intents. Other methods update state, and callers invoke `tick` immediately afterward when they need decisions. `acknowledge` returns false for an unrecognized or obsolete token without changing peer state.

## Selection and accounting algorithm

1. Before each valid operation, accrue elapsed time to `allowed_seconds` for every confirmed-allowed peer. Store only an accumulated number and the last accounting timestamp. A successful allow acknowledgment records the peer's latest grant time. Do not credit desired or unconfirmed permission as service.
2. Aggregate contributions into whole-second buckets, keyed by `floor(now)`. At time `now`, retain only buckets from `floor(now) - contribution_window + 1` through `floor(now)`, inclusive. Their sum is the score. This explicitly uses bucket-aligned windows, not exact event-age windows. Store no individual byte events; each peer retains at most `contribution_window` buckets.
3. Eligible peers are connected and interested. If uploading is disabled or shutdown has started, desired selection is empty. Otherwise recompute regular selections on the first tick, when `now >= next_selection`, or when membership, interest, upload mode, or seeder mode changes. Set `next_selection = now + selection_interval` after recomputation; never replay missed intervals.
4. Retain a still-eligible optimistic incumbent until its rotation deadline. Exclude that incumbent from regular selection. In downloader mode rank regular candidates by descending recent bytes, then ascending accumulated allowed seconds. In seeder mode ignore contribution scores and rank by ascending allowed seconds. This lets seeders distribute service without requiring contributions they no longer need.
5. Resolve exact rank ties by sorting the tied IDs lexicographically and choosing with a private `random.Random(config.random_seed)` instance. Remove each chosen peer before selecting another. Consume random draws only when a tied choice actually needs resolution, never during snapshots or contribution recording.
6. At the first selection, an optimistic vacancy, an ineligible incumbent, or `now >= next_optimistic`, choose one eligible peer outside the regular set. Prefer peers never successfully granted permission; within that class prefer earliest connection time. Otherwise prefer the earliest last successful grant time. Resolve remaining ties with the same sorted-list seeded random choice. On scheduled rotation exclude the previous optimistic peer if another candidate exists. Set `next_optimistic = now + optimistic_interval` whenever this choice is reconsidered, even if the candidate set is empty.
7. When rotation is due, compute regular selection without reserving the old optimistic incumbent, then choose the new optimistic peer. Do not silently fill an absent optimistic candidate with an additional regular selection. Fewer eligible peers therefore use fewer slots.

Grant latency can reduce actual service and delays affect fairness. This is a deterministic local policy, not a guarantee about network throughput or malicious peers. The free-rider switch is exactly `set_upload_enabled(False, now)`: it requests denial for everyone while still permitting contribution recording. Reenabling performs a fresh selection at the next tick.

## Safe permission transitions and acknowledgments

Track desired permission separately from confirmed permission. A slot is **reserved** if permission is confirmed true **or** an allow intent is pending. The number of reserved slots must never exceed `max_slots`.

On each tick, first issue denies for confirmed-allowed peers no longer desired, in sorted ID order. Then issue allows for desired peers with confirmed permission false, in sorted ID order, only while unreserved capacity remains. A pending deny still occupies its slot until acknowledged. A peer may have only one pending intent. Return only newly issued intents, never the same command on every tick.

Generate tokens as `epoch:counter`, beginning with `1:1` and increasing the counter per intent. On a matching successful acknowledgment, set confirmed permission to the intent's `allow` value and clear pending state. On a matching `applied=False`, leave confirmed permission unchanged and clear pending state; the next tick may issue a fresh token. Thus `False` explicitly means the operation did not occur, not “outcome unknown.” Repeated acknowledgments and old tokens are ignored.

If desired permission changes while an allow is pending, retain its reservation and token. After its success acknowledgment the next tick issues a deny if still required. Do not reuse its capacity prematurely. Pending intents exceeding the confirmation timeout produce one `confirmation_overdue` diagnostic each, remain pending, and accept their original acknowledgment. Never guess that a timed-out allow failed or that a deny succeeded.

Disconnect is the caller's assertion that the connection has ended: remove all its accounting, selections, reservation, and pending state. Reconnection with the same ID creates fresh state; monotonically increasing intent tokens prevent old acknowledgments from affecting it.

## Lifecycle, bounds, and diagnostics

Use a bounded diagnostic deque, dropping the oldest entry at capacity. Record only `confirmation_overdue`, `command_not_applied`, and `unknown_ack`; avoid traffic logs and raw contribution events. Snapshots copy current state, sort peers and regular IDs, prune expired buckets, and never select peers or issue commands.

`shutdown` is idempotent: enter closing mode and set every desired permission false. Continue accepting ticks, acknowledgments, and disconnects. Reject connect, contribution, and configuration-changing calls while closing. Become closed only when every peer is confirmed denied and no intents remain pending; an unresolved allow keeps shutdown incomplete. `reset` is allowed only when closed, clears all peers and diagnostics, restores initial modes and RNG seed, increments the epoch, and retains the caller's monotonic time origin. Pending work cannot be erased through reset.

Memory is proportional to `max_peers * contribution_window` plus bounded diagnostics. Public collections expose copies. No callable adapter, project import, transport callback, or application-specific configuration is needed.

## Local JSON-lines interface

Provide `python -m bittorrent_lite.scheduling.choking_policy`. Each stdin line is one JSON object; each stdout line is one JSON response. `config` is an optional first-only operation accepting the configuration fields above; otherwise use defaults. All other operations require `now`. Operation names and argument names match the public methods; `connect` uses `peer: {"peer_id": ..., "interested": ...}`. `tick` returns `intents` and `state`; `snapshot` returns `state`; acknowledgment returns `accepted`; other successes return `{"ok":true}`. Dataclasses serialize with the declared field names, tuples as arrays. Reject unknown operations, extra keys, and malformed types with `{"ok":false,"error":{"type":"ValueError","message":"..."}}`, then continue reading. EOF simply exits; it does not fabricate acknowledgments.

```json
{"op":"connect","peer":{"peer_id":"alice","interested":true},"now":0}
{"op":"record_contribution","peer_id":"alice","verified_bytes":4096,"now":0}
{"op":"tick","now":0}
{"op":"acknowledge","token":"1:1","applied":true,"now":0}
{"op":"set_upload_enabled","enabled":false,"now":1}
{"op":"tick","now":1}
```

The first tick's intent array is exactly `[{"token":"1:1","peer_id":"alice","allow":true,"issued_at":0.0}]`; Alice is regular, optimistic is null, recent bytes are 4096, and permission is reserved but unconfirmed. Acknowledgment returns `{"accepted":true}`. The second tick issues token `1:2` with `allow:false` and `issued_at:1.0`; confirmed permission remains true until its acknowledgment. Full tick responses also contain every declared snapshot field.

## Implementation sequence and handoff

1. Models, validation, monotonic clock handling, and contribution buckets — **4 units**.
2. Regular and optimistic selection, fairness, seeded ties, and mode changes — **6 units**.
3. Slot reservation, intent acknowledgments, disconnects, and shutdown/reset — **6 units**.
4. JSON-lines interface, bounded diagnostics, and public API documentation — **4 units**.

Deliver `bittorrent_lite/scheduling/choking_policy/__init__.py`, `models.py`, `policy.py`, `__main__.py`, and `README.md`. Export the public API from `__init__.py`; document every method, error, timing rule, JSON operation, and the example above in the README. The handoff is complete when these behaviors are implemented and the package is usable directly from its containing folder without dependencies or another codebase. Do not add test files, test execution tasks, benchmark scripts, experiments, repository integration, or changes to other packages.
