# bittorrent_lite.scheduling.choking_policy

A standalone, standard-library-only (Python 3.10+) upload-permission policy. It decides which
connected peers the local client may upload to and emits *permission-change intents*. It never
opens sockets, moves bytes, or sends protocol messages. Run it from the repository root or an editable installation; there are no dependencies.

"Allowed" always means the **local client permits upload to that peer**.

## Quick start

```python
from bittorrent_lite.scheduling.choking_policy import Policy, PeerInfo

p = Policy()
p.connect(PeerInfo("alice", interested=True), 0)
p.record_contribution("alice", 4096, 0)
decision = p.tick(0)              # decision.intents -> allow intent, token "1:1"
p.acknowledge("1:1", True, 0)     # True
```

## Configuration (`Config`, frozen)

| Field | Default | Validation |
| --- | --- | --- |
| `max_peers` | 128 | positive integer |
| `max_slots` | 2 | integer 2 .. `max_peers` |
| `selection_interval` | 5.0 | finite, positive seconds |
| `optimistic_interval` | 15.0 | finite, >= `selection_interval` |
| `contribution_window` | 5 | positive whole seconds |
| `confirmation_timeout` | 10.0 | finite, positive seconds |
| `diagnostic_capacity` | 128 | positive integer |
| `random_seed` | 0 | integer |

One of `max_slots` is reserved for the optimistic peer; the rest are regular. Empty slots are
allowed. Invalid configuration raises `ValueError`.

## Models (all frozen; collections are tuples)

`PeerInfo(peer_id, interested=False)`, `PermissionIntent(token, peer_id, allow, issued_at)`,
`Diagnostic(code, peer_id, at)`, `PeerSnapshot(peer_id, interested, desired, confirmed, reserved,
recent_bytes, allowed_seconds, pending)`, `Snapshot(now, upload_enabled, seeder, closing, closed,
peers, regular, optimistic, diagnostics)`, `Decision(intents, state)`.

## Timing rules

Every call takes `now` (seconds). It must be a finite, nonnegative number (not a bool) and must
not decrease across *any* calls on one instance; equal values are fine. There are no wall clocks,
threads, or sleeps. Before each valid operation, elapsed time is accrued to `allowed_seconds`
for every *confirmed*-allowed peer (desired or pending permission earns nothing).

Contributions are summed in whole-second buckets keyed by `floor(now)`. The score at `now` is the
sum of buckets from `floor(now) - contribution_window + 1` through `floor(now)`.

## Errors

* Invalid argument values or types: `ValueError` (state unchanged).
* Duplicate `connect`: `ValueError`. Unknown peer ID: `KeyError` (except `disconnect`, which is
  harmless for unknown IDs). `connect` above `max_peers`: `OverflowError`.
* `connect`, `record_contribution`, `set_seeder`, `set_upload_enabled` while closing: `RuntimeError`.
* `reset` when not closed: `RuntimeError`.

`peer_id`: nonempty string, at most 128 characters, case-sensitive. `verified_bytes`: integer,
1 .. 16,777,216 (bools rejected).

## API

* `connect(peer, now)` – add a peer (desired/confirmed false, no contribution).
* `disconnect(peer_id, now)` – remove all of its state, selections, reservation and pending intent.
* `set_interested(peer_id, interested, now)` – update interest (allowed while closing).
* `record_contribution(peer_id, verified_bytes, now)` – the caller has verified these bytes.
* `set_seeder(seeder, now)` – seeder mode ranks by ascending `allowed_seconds`, ignoring bytes.
* `set_upload_enabled(enabled, now)` – `False` is the free-rider switch: desired becomes empty and
  denies are issued on the next `tick`; contributions are still recorded. Re-enabling does a fresh
  selection at the next `tick`.
* `tick(now) -> Decision` – the only call that creates intents (returns only new ones).
* `acknowledge(token, applied, now) -> bool` – `False` for unknown/obsolete/repeated tokens
  (recorded as an `unknown_ack` diagnostic). `applied=False` means "did not occur": confirmed
  state is unchanged and the pending slot is cleared so the next `tick` may issue a fresh token.
* `snapshot(now) -> Snapshot` – copy of state; never selects or issues.
* `shutdown(now)` – idempotent; closing mode, every desired permission false.
* `reset(now)` – only when closed; clears peers and diagnostics, restores initial modes and RNG
  seed, increments the epoch, keeps the time origin.

## Selection summary

Eligible = connected and interested. Selection is recomputed on the first tick, when
`now >= next_selection`, when `now >= next_optimistic`, or after a change in membership, interest,
upload mode or seeder mode; missed intervals are never replayed. Regular slots (`max_slots - 1`)
rank by descending recent bytes then ascending `allowed_seconds` (seeder: ascending
`allowed_seconds`). The optimistic peer is retained until rotation; at vacancy/rotation it is
chosen outside the regular set, preferring never-granted peers (earliest connection), else the
earliest last successful grant, excluding the previous optimistic peer if another candidate exists.
Exact ties are broken by a seeded `random.Random` over the lexicographically sorted tied IDs; a
draw is consumed only when a tie must be resolved. Absent candidates leave slots empty.

## Reservations and tokens

A slot is *reserved* if permission is confirmed or an allow is pending; reserved slots never
exceed `max_slots`. Each `tick` first issues denies (sorted IDs) for confirmed peers no longer
desired, then allows (sorted IDs) for desired unconfirmed peers while capacity remains. A pending
deny still holds its slot. One pending intent per peer. Tokens are `epoch:counter`, starting at
`1:1`. Intents past `confirmation_timeout` produce one `confirmation_overdue` diagnostic each and
stay pending (accepting their original acknowledgment). Diagnostic codes: `confirmation_overdue`,
`command_not_applied`, `unknown_ack`, held in a bounded deque.

`closed` becomes true once closing and every peer is confirmed denied with nothing pending.

## JSON-lines interface

`python -m bittorrent_lite.scheduling.choking_policy` reads one JSON object per stdin line and writes one response per line.
`config` (fields above) is optional and valid only as the first line. All other operations require
`now`; operation and argument names match the methods (`connect` takes
`"peer": {"peer_id": ..., "interested": ...}`).

* `tick` -> `{"intents": [...], "state": {...}}`
* `snapshot` -> `{"state": {...}}`
* `acknowledge` -> `{"accepted": true|false}`
* everything else -> `{"ok": true}`
* failures -> `{"ok":false,"error":{"type":"ValueError","message":"..."}}`; reading continues.
  Unknown operations, extra/missing keys and malformed types are rejected.

EOF exits quietly without fabricating acknowledgments.

### Example

```json
{"op":"connect","peer":{"peer_id":"alice","interested":true},"now":0}
{"op":"record_contribution","peer_id":"alice","verified_bytes":4096,"now":0}
{"op":"tick","now":0}
{"op":"acknowledge","token":"1:1","applied":true,"now":0}
{"op":"set_upload_enabled","enabled":false,"now":1}
{"op":"tick","now":1}
```

The first tick yields `[{"token":"1:1","peer_id":"alice","allow":true,"issued_at":0.0}]`, with
Alice regular, `optimistic` null, `recent_bytes` 4096, reserved but unconfirmed. The acknowledgment
returns `{"accepted":true}`. The second tick issues `1:2` with `allow:false`, `issued_at:1.0`;
confirmed permission stays true until that deny is acknowledged.
