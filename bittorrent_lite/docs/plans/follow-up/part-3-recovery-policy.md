# Part 3 — Independent recovery and piece-selection policy

## Objective and independence

Build a standalone Python library named `bittorrent_lite.scheduling.recovery` that decides which provider and piece combinations may be attempted, orders eligible pieces, and decides when an additional request for a slow piece is justified. It records failures and successes but never sends requests or changes a request queue.

Start in an empty directory. This document supplies the complete requirements. No existing project, previous implementation, other development plan, repository source, network connection, or third-party package is needed. Use Python 3.10 or later and the standard library only. Inputs are ordinary Python values supplied directly by the caller; providers and pieces can be represented by invented local identifiers.

The deliverable is a usable decision library and command-line interface. Actual downloads, request accounting, sockets, file verification, upload permissions, and application integration are outside its scope. Formal testing and benchmarks are reserved for **Part 6** and are excluded here.

Budget **20 estimated development-effort units**, approximately one quarter of the intended development allocation. These estimates are a planning aid, not a guarantee of equal elapsed time.

| Work | Units |
|---|---:|
| Public API, configuration, and input validation | 4 |
| Retry ledger, exclusions, cleanup, and capacity limits | 6 |
| Three selection strategies | 3 |
| Additional-request eligibility | 3 |
| Diagnostics, CLI, and usage documentation | 4 |
| **Total** | **20** |

## Files to deliver

Create this directory structure inside the empty working directory:

```text
bittorrent_lite/scheduling/recovery/
    __init__.py
    __main__.py
    config.py
    policy.py
    selection.py
README.md
```

Export `RecoveryConfig`, `RecoveryPolicy`, and `CapacityError` from `bittorrent_lite.scheduling.recovery`. Imports must perform no I/O. Execute the CLI with `python -m bittorrent_lite.scheduling.recovery`; installation and a packaging tool are unnecessary.

## Public values and API

A **piece** is an integer index from zero through `num_pieces - 1`. A **provider** is a case-sensitive, nonempty string of at most 128 characters. A provider retains the same identity across repeated attempts. IDs are opaque: never interpret them as addresses or filenames. Booleans are not accepted as integers.

```python
RecoveryPolicy(num_pieces: int, config=None, *, seed: int = 0)

rank_candidates(*, now: float, provider: str,
                candidates: list[int], availability: list[int]) -> list[int]
allow_duplicate(*, now: float, piece: int, provider: str,
                pending: list[dict], missing_count: int,
                no_unreserved_candidates: bool) -> bool
failed(*, now: float, provider: str, piece: int, kind: str) -> None
succeeded(*, now: float, provider: str, piece: int) -> None
snapshot(*, now: float) -> dict
```

Validate `num_pieces` as an integer in `1..65536`; this bounds the remembered owned-piece set. Use one private `random.Random(seed)` instance. Accept an integer seed excluding booleans. Identical configuration, seed, and method-call sequence must produce identical decisions and diagnostics.

Every `now` is explicitly supplied monotonic elapsed seconds, represented by an integer or float excluding booleans. It must be finite, nonnegative, and no earlier than the last accepted call's time. Equal timestamps are allowed. Never read the system clock, sleep, or start a timer thread. A successful call records its timestamp; rejected input changes no state, timestamp, counters, or RNG position. A snapshot changes only that last accepted timestamp.

All public calls are made sequentially by one caller; the library creates no threads. Copy retained inputs and return fresh collections. No caller needs to implement an interface or supply another object.

Use `ValueError` for invalid configuration or arguments and `CapacityError`, a subclass of `RuntimeError`, when retaining a new penalty would exceed a configured capacity. Validate the entire input before mutation. Do not silently coerce strings, booleans, negative values, NaN, or infinity.

## Configuration

Implement `RecoveryConfig` as a frozen dataclass:

| Field | Default | Validation |
|---|---|---|
| `strategy` | `"rarest-first"` | Also accepts `"sequential"` or `"random"` |
| `retry_delays` | `(2.0, 4.0, 10.0)` | Nonempty tuple of finite positive nondecreasing seconds |
| `local_send_cooldown` | `1.0` | Finite positive seconds |
| `endgame_enabled` | `True` | Actual boolean |
| `endgame_remaining` | `4` | Positive integer |
| `endgame_min_age` | `5.0` | Finite positive seconds |
| `max_copies` | `2` | Integer 1 or 2 |
| `max_penalty_providers` | `256` | Positive integer |
| `max_penalty_entries` | `4096` | Positive integer |
| `recent_event_limit` | `256` | Nonnegative integer; zero disables history |

These are local defaults, requiring no configuration imports. `endgame_remaining` may exceed `num_pieces`; it is simply a threshold. Aggregate counters remain available when detailed history is disabled.

## Failure ledger and completion

Store at most one penalty record per `(provider, piece)`. A record contains retryable-failure streak, cooldown deadline, exclusion flag, latest reason, and latest timestamp. Failure kinds have these exact meanings:

| Kind | Effect |
|---|---|
| `response_timeout`, `reject` | Increment the retryable streak; apply delay 2, then 4, then 10 seconds, repeating the last delay |
| `invalid_piece` | Exclude this provider for this piece until the piece succeeds |
| `enqueue_failed`, `send_failed`, `send_unconfirmed` | Apply the one-second local-send cooldown without changing retryable streak |
| `choke`, `disconnect` | Increment the corresponding counter only; preserve existing penalties |

Use configured delays instead of literal values in the implementation. A newly applied deadline is the maximum of the old deadline and `now + delay`; a short failure cannot shorten an existing penalty. No failure clears an exclusion. Repeated attempts retain their streak after cooldown expiry. Unknown kinds are invalid.

Only the caller knows whether an event is stale or duplicated. Each accepted `failed` call for an unfinished piece represents one new failure and increments its counter. Request IDs are deliberately not tracked here. Calls concerning an already successful piece become no-ops after argument validation.

`succeeded` means that the caller has already accepted the piece. Mark it owned, delete every provider's penalty record for that piece, and count one success. Repeated success calls for that piece are no-ops. Do not perform storage or integrity checks. Start a new `RecoveryPolicy` instance for a new session; provide no method that silently forgets penalties on reconnect.

Count distinct providers that currently have penalty records against `max_penalty_providers`. Capacity applies only when creating a new record/provider; updating an existing record remains possible. On capacity failure, raise before any mutation. Never evict an exclusion, cooldown, or streak to make space. Success cleanup frees capacity. This makes limits explicit and avoids depending on an external admission controller.

## Candidate selection

`availability` must contain exactly `num_pieces` nonnegative integers. Its value at a piece index is the supplied count of providers advertising that piece. `candidates` must be a list of distinct valid indices offered by the named provider. No connection state is inferred.

Remove owned pieces, pieces with zero availability, and provider/piece pairs whose exclusion is set or whose cooldown satisfies `now < deadline`. Eligibility resumes exactly at the deadline. Order the survivors as follows:

- `rarest-first`: group by ascending positive availability; start each group in index order, shuffle it using the private RNG, then concatenate groups.
- `sequential`: increasing piece index.
- `random`: sort by index first, then shuffle with the private RNG.

Return an ordered subset without duplicates. Never change the input arrays, the availability counts, failure streaks, or deadlines. An empty result is valid; it must not weaken exclusions. A caller can obtain another provider's decision simply by calling the same method with that provider's identifier and candidate list.

## Additional-request decision

Each `pending` entry is a plain dictionary with exactly these keys:

```python
{"request_id": 12, "provider": "source-A", "piece": 3,
 "queued_at": 2.0, "sent_at": 2.2, "verifying": False}
```

Validate positive integer request IDs, valid providers and piece indices, actual boolean `verifying`, and finite timestamps with `0 <= queued_at <= now`. `sent_at` is either `None` or satisfies `queued_at <= sent_at <= now`. Every entry must describe the requested piece; identities `(provider, request_id)` must be distinct. Accept at most two entries. Reject malformed input instead of returning an encouraging decision.

Validate `missing_count` as an integer from zero through `num_pieces` and `no_unreserved_candidates` as an actual boolean. Both are caller-provided facts; the library cannot reconstruct them from a partial snapshot.

Return true only when all these conditions hold:

1. Endgame is enabled, `max_copies == 2`, and the piece is not owned.
2. `1 <= missing_count <= endgame_remaining` and `no_unreserved_candidates` is true.
3. Exactly one request is pending; it is sent, is not verifying, and has been sent for at least `endgame_min_age` seconds.
4. The proposed provider differs from its provider and has no active cooldown or exclusion for this piece.

Otherwise return false without creating a request. No pending request means ordinary work; two requests mean the cap has been reached. The caller supplies a candidate that actually offers the piece and can accept work. This method is a decision on supplied facts, not permission to bypass those facts.

## Diagnostics and CLI

`snapshot` returns JSON-compatible configuration, owned indices, counters by failure kind, success count, current entry/provider counts, all retained penalty records, and bounded recent events. Records include remaining cooldown seconds clamped to zero. Sort records by provider then piece. Preserve expired records because their streaks still matter. Include an omitted-history counter; never include payload bytes.

The CLI reads JSON lines from standard input. Its first line constructs the policy using `{"op":"create","num_pieces":3,"seed":0}` and optional `config`. Subsequent lines use one public method name as `op` and that method's named arguments. Emit one JSON result line for every input: `{"ok":true,"result":...}` or `{"ok":false,"error":"ValueError","message":"..."}`. Void methods return null. Convert JSON `retry_delays` arrays to tuples at the CLI boundary. Catch only documented input/capacity errors and JSON parse errors; do not hide unexpected programming exceptions. Do not accept a second create operation.

Document this runnable local API example:

```python
from bittorrent_lite.scheduling.recovery import RecoveryPolicy

p = RecoveryPolicy(3, seed=7)
p.failed(now=0, provider="source-A", piece=2, kind="reject")
print(p.rank_candidates(now=1, provider="source-A",
                       candidates=[0, 2], availability=[2, 0, 1]))
print(p.rank_candidates(now=2, provider="source-A",
                       candidates=[0, 2], availability=[2, 0, 1]))
```

The first output is `[0]`; the second is `[2, 0]`. These values require no files, servers, or project context.

## Implementation order and completion

Implement immutable configuration and complete validation first, then the bounded penalty ledger and success cleanup, selection helpers, duplicate eligibility, and finally snapshot/CLI serialization. Keep decision functions small and retain one authoritative ledger.

Delivery is complete when every documented method, configuration field, capacity rule, and CLI operation is implemented; all imports resolve within this package or the standard library; and the README contains setup, exact APIs, error behavior, both CLI and Python usage, and limitations. No later integration task is necessary to use the delivered library. Do not include test files, assertion-based fixtures, benchmark scripts, testing instructions, or claims of completed testing.
