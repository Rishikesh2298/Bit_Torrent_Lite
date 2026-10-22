# bittorrent_lite.scheduling.recovery

A standalone decision library for provider/piece recovery. It decides which provider and piece
combinations may be attempted, orders eligible pieces, and decides when an additional request for a
slow piece is justified. It records failures and successes but never sends requests, reads a clock,
sleeps, starts threads, or touches files or the network.

## Setup

Python 3.10+ and the standard library only. From the repository root or an editable installation:

```bash
python -c "import bittorrent_lite.scheduling.recovery"   # imports perform no I/O
python -m bittorrent_lite.scheduling.recovery            # CLI (JSON lines on stdin)
```

No installation step is required.

## Python usage

```python
from bittorrent_lite.scheduling.recovery import RecoveryPolicy

p = RecoveryPolicy(3, seed=7)
p.failed(now=0, provider="source-A", piece=2, kind="reject")
print(p.rank_candidates(now=1, provider="source-A",
                        candidates=[0, 2], availability=[2, 0, 1]))   # [0]
print(p.rank_candidates(now=2, provider="source-A",
                        candidates=[0, 2], availability=[2, 0, 1]))   # [2, 0]
```

## API

Exported: `RecoveryConfig`, `RecoveryPolicy`, `CapacityError`.

`RecoveryPolicy(num_pieces, config=None, *, seed=0)`
- `num_pieces`: integer 1..65536. Pieces are indices `0..num_pieces-1`. Seed: integer.
- Providers: case-sensitive nonempty strings of at most 128 characters, treated as opaque.
- Booleans are never accepted as integers. Identical config, seed and call sequence give identical results.

`now` (every call): finite, nonnegative int/float of monotonic seconds, not earlier than the last
accepted call (equal is allowed). Rejected input changes no state, timestamp, counter or RNG position.

| Method | Purpose |
|---|---|
| `rank_candidates(*, now, provider, candidates, availability) -> list[int]` | Drop owned pieces, zero-availability pieces, and pairs that are excluded or in cooldown (`now < deadline`; eligible again exactly at the deadline); order the rest by strategy. May return `[]`. |
| `allow_duplicate(*, now, piece, provider, pending, missing_count, no_unreserved_candidates) -> bool` | Whether `provider` may receive a second request for `piece`. |
| `failed(*, now, provider, piece, kind) -> None` | Record one new failure. |
| `succeeded(*, now, provider, piece) -> None` | Mark the piece owned and delete all penalty records for it. |
| `snapshot(*, now) -> dict` | JSON-compatible diagnostics. |

`availability` must be a list of exactly `num_pieces` nonnegative integers; `candidates` a list of
distinct valid indices.

### Failure kinds

| Kind | Effect |
|---|---|
| `response_timeout`, `reject` | Streak +1; cooldown from `retry_delays[streak-1]` (last delay repeats) |
| `invalid_piece` | Exclude provider for that piece until it succeeds |
| `enqueue_failed`, `send_failed`, `send_unconfirmed` | `local_send_cooldown`, streak unchanged |
| `choke`, `disconnect` | Counter only; penalties preserved |

A new deadline is `max(old, now + delay)`; no failure shortens a penalty or clears an exclusion.
Failures or successes for an already-owned piece are no-ops after validation. Unknown kinds raise `ValueError`.

### `allow_duplicate`

Each `pending` entry: `{"request_id", "provider", "piece", "queued_at", "sent_at", "verifying"}`
(exactly these keys, at most two entries, all describing `piece`, distinct `(provider, request_id)`,
`0 <= queued_at <= now`, `sent_at` is `None` or `queued_at <= sent_at <= now`). Returns true only if
endgame is enabled, `max_copies == 2`, the piece is unowned, `1 <= missing_count <= endgame_remaining`,
`no_unreserved_candidates` is true, exactly one request is pending, sent, not verifying and at least
`endgame_min_age` seconds old, and `provider` differs from that request's provider and has no active
cooldown or exclusion for the piece. Otherwise false.

### `RecoveryConfig` (frozen dataclass)

| Field | Default | Rule |
|---|---|---|
| `strategy` | `"rarest-first"` | or `"sequential"`, `"random"` |
| `retry_delays` | `(2.0, 4.0, 10.0)` | nonempty tuple, finite positive, nondecreasing |
| `local_send_cooldown` | `1.0` | finite positive |
| `endgame_enabled` | `True` | boolean |
| `endgame_remaining` | `4` | positive int (may exceed `num_pieces`) |
| `endgame_min_age` | `5.0` | finite positive |
| `max_copies` | `2` | 1 or 2 |
| `max_penalty_providers` | `256` | positive int |
| `max_penalty_entries` | `4096` | positive int |
| `recent_event_limit` | `256` | nonnegative int; 0 disables history |

Strategies: `rarest-first` groups by ascending availability, index order then shuffled within each
group; `sequential` is ascending index; `random` sorts then shuffles. One private `random.Random(seed)`.

### Capacity and errors

At most one penalty record per `(provider, piece)`. Creating a record that would exceed
`max_penalty_entries` or introduce a provider beyond `max_penalty_providers` raises `CapacityError`
(a `RuntimeError`) before any mutation. Updating existing records is always possible; nothing is ever
evicted; `succeeded` frees capacity. Invalid configuration or arguments raise `ValueError`.

### Snapshot

Keys: `config`, `num_pieces`, `owned`, `counters` (per failure kind), `successes`,
`penalty_entry_count`, `penalty_provider_count`, `penalties` (sorted by provider, piece; each with
`streak`, `cooldown_deadline`, `cooldown_remaining` clamped at 0, `excluded`, `reason`, `last_at`;
expired records are kept), `recent_events`, `omitted_events`. Counters work even with history disabled.

## CLI

One JSON object per stdin line. The first must be create; a second create is rejected:

```
{"op":"create","num_pieces":3,"seed":0,"config":{"retry_delays":[2,4,10]}}
{"op":"failed","now":0,"provider":"source-A","piece":2,"kind":"reject"}
{"op":"rank_candidates","now":1,"provider":"source-A","candidates":[0,2],"availability":[2,0,1]}
{"op":"snapshot","now":2}
```

Other ops are the method names above with their named arguments. Each input yields one line:
`{"ok":true,"result":...}` (void methods give `null`) or
`{"ok":false,"error":"ValueError","message":"..."}`. Handled errors: `ValueError` (including JSON
parse errors and bad or missing arguments) and `CapacityError`; other exceptions propagate. Blank lines are skipped.

## Limitations

- Decisions only: no requests, queues, accounting, storage or integrity checks.
- Calls are sequential from one caller; the library is not thread-safe.
- The caller decides whether a failure event is stale or duplicated; each accepted call counts.
- Availability, `missing_count` and `no_unreserved_candidates` are trusted caller facts.
- No reset method: use a new `RecoveryPolicy` for a new session.
