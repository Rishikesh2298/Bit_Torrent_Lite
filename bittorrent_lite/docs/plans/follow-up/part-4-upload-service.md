# Part 4 — Standalone bounded upload service

## Independence and deliverable

Build this in an **empty directory** as the Python package `bittorrent_lite.scheduling.upload_service`, using Python 3.10+ and only the standard library. This document is the complete specification. No existing project source, previous implementation, parallel plan, protocol package, transport, or storage adapter is required.

The package turns explicitly permitted whole-piece requests into bounded local output records. It owns request admission, fair scheduling, reading and verifying local pieces, cancellation, output acknowledgements, and byte accounting. A caller supplies permission as a boolean; deciding which peers deserve permission is outside this package. There are no sockets, wire messages, tracker calls, or project integration tasks.

Estimated implementation effort: **20 relative units**, targeting roughly one quarter of the four-part implementation allocation. These are estimates, not a claim of identical elapsed time. Automated bittorrent_lite.tests, integration exercises, and benchmarks are reserved for Part 6 and are not deliverables here.

## Files to produce

Create `pyproject.toml`, `README.md`, and these files under `bittorrent_lite/scheduling/upload_service/`: `__init__.py`, `models.py`, `sources.py`, `service.py`, and `__main__.py`. Export the public types below from `__init__.py`. Use dataclasses and enums with type annotations. Installation must not require third-party runtime packages; the example must run directly from the package's parent directory.

## Piece descriptions and sources

`PieceMeta(index: int, length: int, sha256: str)` is frozen. Indices must be consecutive from zero, lengths must be 1–4,194,304 bytes, and `sha256` must contain exactly 64 hexadecimal characters, normalized to lowercase. `Manifest(pieces: tuple[PieceMeta, ...])` accepts 1–4096 entries and rejects duplicate or missing indices. SHA-256 here checks agreement with a supplied content digest; it does not authenticate a source.

The JSON manifest format is exactly:

```json
{"version": 1, "pieces": [{"index": 0, "length": 32768, "sha256": "<64 hexadecimal characters>"}]}
```

`load_manifest(path: str | Path) -> Manifest` rejects unknown fields, booleans in integer fields, unsupported versions, malformed JSON, and files larger than 1 MiB. It raises `ManifestError`, a `ValueError` subclass, with a useful message.

A piece provider is a callable with the contract `read_piece(index: int) -> bytes`. It returns a complete immutable piece, never a stream. The service verifies both exact length and SHA-256 before releasing the piece. Exceptions, wrong return types, incorrect length, and digest mismatch become asynchronous rejection records. Provider calls must be independent and safe to execute concurrently when workers are enabled. Custom providers must respect the manifest's size bound; Python cannot prevent an arbitrary callable from allocating excessive memory or blocking forever.

Provide both adapters inside this package:

- `MemorySource(manifest: Manifest, pieces: Mapping[int, bytes])`: copy the mapping, require exactly the manifest's indices and correctly sized immutable values, and implement `__call__(index)`. The service still verifies hashes. Its retained input bytes are caller-owned source storage, separate from the service's transient memory budget.
- `DirectorySource(manifest: Manifest, root: str | Path)`: read `piece-000000.bin`, `piece-000001.bin`, and so on. Use only these generated filenames; reject symbolic links and resolved paths outside `root`. Open a fresh binary stream for each call, read at most the declared length plus one byte, and require the exact length. Files must remain immutable while the service runs. No cache or shared stream is needed.

## Public records and defaults

Use frozen records with these exact fields:

```python
UploadRequest(peer_id: str, piece: int)
Admission(accepted: bool, job_id: int | None, reason: str | None)
DataOutput(job_id: int, peer_id: str, piece: int, data: bytes)
RejectOutput(job_id: int, peer_id: str, reason: str)
Snapshot(active_jobs: int, queued_jobs: int, reading_jobs: int,
         output_slots: int, reserved_output_bytes: int,
         reserved_read_bytes: int, sent_bytes: int,
         sent_pieces: int, failed_sends: int, cancelled_jobs: int,
         rejected_requests: int, source_failures: int, closed: bool)
```

`Output = DataOutput | RejectOutput`. A valid peer identifier is a nonempty string of at most 64 characters. `piece` is an integer, never a boolean, and must identify one manifest entry. Each accepted request produces exactly one whole-piece output or one rejection record.

`UploadConfig` defaults: `max_jobs=40`, `max_jobs_per_peer=4`, `max_output_records=40`, `max_output_bytes=8388608`, `max_read_bytes=8388608`, `max_piece_length=4194304`, and `workers=0`. Allow `workers` only as `0` or `2`. All limits are positive integers; per-peer jobs cannot exceed global jobs. Require `max_piece_length <= 4194304`, and reject a manifest whose largest piece exceeds this configured limit. Both output and read byte capacities must accommodate the largest manifest piece. Invalid configuration raises `ValueError` at construction.

## Exact service API

Construct `UploadService(manifest, source, config=UploadConfig())`, where `source` satisfies the callable contract above. All public methods belong to the thread that constructed the service. Calling them from another thread raises `RuntimeError`. Only source calls run on workers; workers never mutate queues, counters, or public state.

- `submit(request: UploadRequest, permitted: bool) -> Admission`: validate and admit immediately without reading data. Require a real boolean permission input. Deny unauthorized requests even when they would otherwise be valid. Return a new positive, monotonically increasing job ID on acceptance. Deduplicate active `(peer_id, piece)` tuples. Denial reasons are `permission_denied`, `invalid_request`, `unknown_piece`, `duplicate`, `peer_limit`, `global_limit`, or `closed`. Denied requests create no output record and consume no queue space. Increment `rejected_requests` once per denial.
- `tick(max_dispatch: int = 8) -> None`: harvest completed reads, then dispatch at most this many jobs. Require a positive integer. With zero workers, reads execute synchronously inside this method. With two workers, permit at most two concurrent reads using `ThreadPoolExecutor`; do not build an unbounded executor queue.
- `poll_outputs(limit: int = 16) -> tuple[Output, ...]`: return up to `limit` previously undelivered output records in creation order, marking them delivered. Require a positive integer. Polling does not acknowledge records or release their resource reservations.
- `mark_sent(job_id: int, byte_count: int) -> str`: accept only a delivered `DataOutput` and require `byte_count == len(data)`. On success return `ok`, increment `sent_bytes` and `sent_pieces`, and release the job. Wrong counts return `invalid_byte_count` without changing anything. Other noneligible IDs return `not_delivered` or `unknown_job`.
- `mark_failed(job_id: int) -> str`: release a delivered data record and increment `failed_sends`; also use this method to acknowledge a delivered rejection record, without incrementing `failed_sends`. Return `ok`, `not_delivered`, or `unknown_job`. It does not automatically retry.
- `cancel(job_id: int) -> str`: return `cancelled`, `too_late`, or `unknown_job`, as defined below.
- `cancel_peer(peer_id: str) -> int`: cancel all cancellable jobs for that peer and return the count. The caller can use this explicit operation when permission changes or a peer departs.
- `snapshot() -> Snapshot`: return an immutable, internally consistent current snapshot.
- `shutdown(wait: bool = True) -> None`: close the service as described below; repeated calls are harmless.

Record accounting reflects acknowledged, complete pieces only. Admission, reading, polling, and failed sends do not increase `sent_bytes`. Partial writes belong to a caller's transport implementation; this package does not provide one. The caller must finish the full record before `mark_sent`, or use `mark_failed`.

## Scheduling, states, and resource limits

Use FIFO queues within peers and a rotating deque of peers for round-robin dispatch. One dispatch consumes one peer's turn. Remove empty peer queues and discard per-peer state when that peer has no active jobs. Scan each eligible peer at most once per scheduling pass when resources are unavailable; never busy-spin. Continue past a temporarily unaffordable read when another peer's smaller piece fits.

State progression is `QUEUED -> READING -> READY -> DELIVERED -> released`. A failed read produces a `RejectOutput` in `READY` with reason `source_error`, `invalid_source_data`, `length_mismatch`, or `hash_mismatch`. Keep exception details in optional debug logging, without including filesystem contents in public records.

Global and per-peer job limits include every active state. Before dispatch, reserve one output slot and the entire declared piece length in each of the output and read byte budgets. If a limit would be exceeded, leave the job queued. Include reserved slots for running reads in `output_slots`, so future completion cannot overflow the outbox. The output reservation holds capacity for the eventual record; it does not represent a second allocated payload. After verification, transfer the same immutable bytes object to `DataOutput`, release the read reservation, and enqueue the output. Never copy the piece solely to change ownership. For rejection, release both byte reservations but retain its record slot until acknowledgement.

The provider's temporary oversize-detection byte and ordinary Python metadata are outside these logical byte counters. Read and output reservations overlap while a read is running; do not add them together as an estimate of allocated payload memory. With no unnecessary copies, every active payload is already covered by its output-byte reservation, including reads in progress. An ignored delivered record keeps its slot, bytes, and job reservation, naturally stopping further admission or dispatch when limits are reached. Never silently drop it.

Cancellation of `QUEUED` or undelivered `READY` work releases it immediately. Cancellation of `READING` work sets a cancelled flag, increments `cancelled_jobs` once, suppresses its eventual output, and retains the job and all reservations until the provider returns. A second cancellation of this flagged job returns `cancelled` without recounting. Cancellation of `DELIVERED` work returns `too_late`: bytes already handed to a caller cannot be recalled. Completed or released IDs return `unknown_job`; no unbounded terminal-job history is retained.

## Shutdown and errors

`shutdown` sets `closed`, discards queued/ready outputs, invalidates delivered handles, and suppresses outputs from running reads. Previously acknowledged byte totals remain unchanged. Subsequent submissions return `closed`, polling returns an empty tuple, and acknowledgements return `unknown_job`. `tick` may still reap cancelled worker results but must never dispatch new work.

With `wait=True`, finish running provider calls and release reservations before returning. With `wait=False`, return promptly while at most two calls finish; later `tick` or a repeated `shutdown(wait=True)` reaps them. A blocked custom provider cannot be forcibly stopped safely by Python threads, and interpreter exit can wait for it. Document this limitation; do not promise a hard shutdown deadline. Count discarded active jobs as cancelled exactly once. Catch ordinary provider exceptions, not `BaseException` process-control signals.

## Runnable local example

Implement `python -m bittorrent_lite.scheduling.upload_service demo --directory ./upload-demo`. Refuse an existing nonempty directory. Create two separate 32,768-byte pieces using `bytes(range(256)) * 128` and `bytes(reversed(range(256))) * 128`, compute their SHA-256 digests, and write `piece-000000.bin`, `piece-000001.bin`, and a manifest with both entries. Instantiate the directory source and service, submit `UploadRequest("demo-peer", 0)` and `UploadRequest("demo-peer", 1)` with `permitted=True`, call `tick`, print output metadata, and acknowledge each whole-piece record locally with `mark_sent`. Finish with `shutdown` and a snapshot showing 65,536 acknowledged bytes and two sent pieces. Clearly label these as simulated delivery acknowledgements. This is a usage example, not a network transfer or test suite.

## Implementation allocation and completion

1. Records, manifest loader, configuration validation, and both source adapters — 5 units.
2. Admission, active-job tracking, fair queues, and resource reservations — 5 units.
3. Read execution, optional workers, output lifecycle, and accounting — 5 units.
4. Cancellation, shutdown, command-line example, packaging, and API documentation — 5 units.

Completion means the package implements every public contract above, documents errors and resource ownership, and includes the runnable example and its expected output meaning. No other repository needs to exist to develop or use it. Deliver package code and README only; production integration, choking policy, real sending, automated bittorrent_lite.tests, and benchmarks are outside this plan.
