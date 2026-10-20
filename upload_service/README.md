# upload_service

A standalone, standard-library-only (Python 3.10+) service that turns explicitly
permitted whole-piece requests into bounded local output records. It owns request
admission, fair scheduling, reading and verifying local pieces, cancellation, output
acknowledgements and byte accounting. It has no sockets, wire messages or tracker
calls; deciding *which peers deserve permission* is the caller's job.

Run the example from this directory (the package's parent):

```
python -m upload_service demo --directory ./upload-demo
```

## Public API

Exported from `upload_service`: `PieceMeta`, `Manifest`, `ManifestError`, `load_manifest`,
`MemorySource`, `DirectorySource`, `UploadConfig`, `UploadRequest`, `Admission`,
`DataOutput`, `RejectOutput`, `Output`, `Snapshot`, `UploadService`, `JobState`.

### Manifest

`PieceMeta(index, length, sha256)` (frozen): consecutive indices from 0, length
1–4,194,304, `sha256` exactly 64 hex characters (normalized to lowercase). `Manifest`
holds 1–4096 pieces in index order; duplicates or gaps raise `ManifestError`
(a `ValueError` subclass). SHA-256 only checks agreement with a supplied digest; it
does **not** authenticate a source.

JSON format:

```json
{"version": 1, "pieces": [{"index": 0, "length": 32768, "sha256": "<64 hex chars>"}]}
```

`load_manifest(path)` rejects unknown fields, booleans in integer fields, unsupported
versions, duplicate keys, malformed JSON, unreadable files and files over 1 MiB, always
with `ManifestError`.

### Sources

A provider is `read_piece(index: int) -> bytes` returning a complete immutable piece.
Calls must be independent and safe to run concurrently when `workers=2`.

* `MemorySource(manifest, pieces)` copies the mapping and requires exactly the manifest
  indices with `bytes` values of the declared size. The retained bytes are
  caller-owned storage, outside the service's transient budget.
* `DirectorySource(manifest, root)` reads `piece-000000.bin`, `piece-000001.bin`, ...
  only. Symlinks and paths resolving outside `root` are rejected; each call opens a
  fresh stream and reads at most `length + 1` bytes; a wrong size raises (reported by
  the service as `source_error`). Files must not change while the service runs.

### Configuration

`UploadConfig` defaults: `max_jobs=40`, `max_jobs_per_peer=4`, `max_output_records=40`,
`max_output_bytes=8388608`, `max_read_bytes=8388608`, `max_piece_length=4194304`,
`workers=0`. Limits are positive integers; `max_jobs_per_peer <= max_jobs`;
`max_piece_length <= 4194304`; `workers` is `0` or `2`. `UploadService(...)` also raises
`ValueError` if the manifest's largest piece exceeds `max_piece_length` or either byte
capacity. `TypeError` is raised for wrong argument types.

### Service methods

All methods must be called from the constructing thread (`RuntimeError` otherwise).
Worker threads only run the provider; they never touch service state.

| Method | Behavior |
|---|---|
| `submit(request, permitted)` | Validates and admits without reading. `permitted` must be a real `bool` (`TypeError` otherwise). Denial reasons: `closed`, `permission_denied`, `invalid_request`, `unknown_piece`, `duplicate`, `peer_limit`, `global_limit` (checked in that order). Denials create no output and increment `rejected_requests`. Job IDs are positive and increasing. |
| `tick(max_dispatch=8)` | Harvests finished reads, then dispatches at most `max_dispatch` jobs. With `workers=0` reads run synchronously inside `tick`; with `workers=2` at most two run concurrently and you must keep calling `tick` to harvest them. |
| `poll_outputs(limit=16)` | Returns undelivered records in creation order and marks them delivered. Does **not** release reservations. |
| `mark_sent(job_id, byte_count)` | For a delivered `DataOutput`: `ok` (releases the job, adds to `sent_bytes`/`sent_pieces`), `invalid_byte_count` (no change), `not_delivered`, or `unknown_job`. |
| `mark_failed(job_id)` | Releases a delivered data record (`failed_sends += 1`) or acknowledges a delivered rejection (no increment). Returns `ok`, `not_delivered`, `unknown_job`. No automatic retry. |
| `cancel(job_id)` | `cancelled`, `too_late` (already delivered), or `unknown_job`. |
| `cancel_peer(peer_id)` | Cancels all cancellable jobs of that peer; returns the number newly cancelled. |
| `snapshot()` | Immutable `Snapshot` of counters. |
| `shutdown(wait=True)` | See below. Repeated calls are harmless. |

`tick` and `poll_outputs` raise `TypeError` for non-integers and `ValueError` for values below 1.

### Records

`UploadRequest(peer_id, piece)`, `Admission(accepted, job_id, reason)`,
`DataOutput(job_id, peer_id, piece, data)`, `RejectOutput(job_id, peer_id, reason)`,
and `Snapshot(...)` are frozen dataclasses. A peer id is a nonempty string of at most 64
characters; `piece` is an integer (never a bool). Each accepted request yields exactly
one `DataOutput` or one `RejectOutput`. Rejection reasons: `source_error`,
`invalid_source_data`, `length_mismatch`, `hash_mismatch`. Exception details go only to
debug logging (logger `upload_service`), never into public records.
`source_failures` counts rejection records produced by failed reads.

## Scheduling and resources

Jobs move `QUEUED -> READING -> READY -> DELIVERED -> released`. Queues are FIFO per
peer, with a rotating deque of peers (one dispatch consumes one peer's turn). When a
peer's head piece is unaffordable the scan moves on to other peers, each examined at
most once per pass; it never busy-spins. Empty peer queues and idle per-peer state are
discarded.

Job limits count every active state (including cancelled reads still running). Before
dispatch a job reserves one output slot plus its full piece length in **both** the output
and read byte budgets; otherwise it stays queued. Reservations overlap while a read runs,
so do not add them to estimate memory. Ownership:

* After verification the *same* `bytes` object becomes the `DataOutput` (no copy); the
  read reservation is released.
* A rejection releases both byte reservations but keeps its slot until acknowledged.
* The slot, output bytes and job stay reserved until `mark_sent`/`mark_failed`. An ignored
  delivered record is never dropped; it simply blocks further admission or dispatch
  once limits fill. The service drops its own reference to delivered bytes; the caller
  holds them.

`Snapshot.output_slots` includes slots reserved by running reads, so completion can
never overflow the outbox. `sent_bytes` counts acknowledged complete pieces only; the
caller must finish the whole record before `mark_sent`, or call `mark_failed`.

## Cancellation

* `QUEUED` or undelivered `READY`: released immediately, `cancelled_jobs += 1`.
* `READING`: flagged and counted once; output is suppressed and all reservations are
  kept until the provider returns (a repeat cancel returns `cancelled` without
  recounting). A new request for the same `(peer, piece)` may be admitted meanwhile.
* `DELIVERED`: `too_late`. Released/completed IDs: `unknown_job`.

## Shutdown

`shutdown` sets `closed`, discards queued, ready and delivered records (each counted as
cancelled exactly once), flags running reads and suppresses their output. Acknowledged
totals are unchanged. Afterwards `submit` returns `closed`, `poll_outputs` returns `()`,
and `mark_sent`/`mark_failed` return `unknown_job`. `tick` only reaps finished reads and
never dispatches.

`wait=True` waits for running provider calls (at most two) and releases reservations.
`wait=False` returns promptly; a later `tick` or `shutdown(wait=True)` reaps them.

**Limitation:** Python threads cannot be forcibly stopped. A provider that blocks forever
cannot be interrupted, `shutdown(wait=True)` will wait for it, and interpreter exit can
also wait. There is no hard shutdown deadline. Custom providers must respect the
manifest's size bound; Python cannot stop an arbitrary callable from over-allocating.
Only `Exception` from providers is caught, never `BaseException`.

## Demo output

```
submit piece 0: accepted=True job_id=1
submit piece 1: accepted=True job_id=2
--- SIMULATED delivery: no network transfer occurs; acknowledgements are local ---
job 1: peer=demo-peer piece=0 bytes=32768 simulated mark_sent -> ok
job 2: peer=demo-peer piece=1 bytes=32768 simulated mark_sent -> ok
snapshot: sent_bytes=65536 sent_pieces=2 active_jobs=0 closed=True
```

The demo refuses an existing non-empty directory, writes two 32,768-byte pieces and a
manifest, reads them through `DirectorySource`, and acknowledges each record locally.
`sent_bytes=65536` and `sent_pieces=2` mean both whole pieces were verified, delivered
as records and acknowledged; no bytes crossed a network.
