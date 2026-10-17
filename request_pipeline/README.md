# request_pipeline

A standalone, standard-library-only (Python 3.10+) library that manages
outstanding numbered data requests: admission, per-connection windows, fair
filling, deadlines, exact request matching, ownership accounting and
explicitly authorized duplicate requests. A *piece* is only a numbered work
item; no bytes are downloaded, stored, hashed or sent here.

All calls belong to one owner thread. No threads, callbacks, sleeps or
wall-clock reads. `now` is a finite, nonnegative, monotonic number supplied by
the caller; going backward raises `ValueError`. Every call validates fully
before mutating state. Invalid programmer input raises `ValueError`; unknown
request keys in event calls return an empty tuple / `False`.

## Types (`models.py`)
- `RequestKey(connection_id, request_id, piece_index)` frozen, hashable.
- `RequestView(key, provider_id, queued_at, sent_at, deadline, verifying)`
  frozen snapshot.
- `Outcome(kind, key, reason, at)`; kind is `completed`, `invalid`, `expired`
  or `canceled`.
- `PieceState`: `MISSING`, `REQUESTED`, `VERIFYING`, `HAVE`.
- `PipelineConfig(window=4, response_timeout=10.0, send_confirm_timeout=5.0,
  max_connections=10, max_copies=2)`; window 1-4, max_copies 1-2, positive
  finite timeouts, positive max_connections. Booleans are rejected as ints.

`PipelineManager(num_pieces, *, initially_owned=(), config=None)`.

## API
- `register_connection(connection_id, provider_id, *, now)`: IDs are positive
  ints, never reusable in the manager's lifetime; one active connection per
  provider; at most `max_connections` active. Violations raise `ValueError`
  with no state change. Permissions start false.
- `set_available(connection_id, piece_indices, *, now)`: replaces a copied
  availability set. Existing requests are not canceled.
- `set_permissions(connection_id, *, interested, unchoked, now)`: booleans.
  If either goes true -> false, unanswered requests on that connection are
  canceled (reason `permission_revoked`); VERIFYING work is kept. Returns the
  cancellations.
- `reserve(connection_id, piece_index, *, now, allow_duplicate=False)`:
  returns a `RequestView` or `None` (ineligible / window full). Needs active
  source, both permissions, availability, unowned piece, free slot, and no
  existing reservation (normal mode). With `allow_duplicate=True` and exactly
  one existing request, a second is allowed only if `max_copies` is 2, the
  provider differs, the piece is not VERIFYING/owned and normal rules pass.
  A third copy is always refused. With no existing request it is normal.
- `fill(candidate_orders, *, now)`: mapping of active connection ID -> distinct
  in-range piece indices in preferred order. Normal reservations only,
  round-robin one candidate per source per round with a rotating source cursor
  (first call starts at the lowest active ID, later calls start after the
  previous starting source). Ineligible candidates are skipped; it terminates
  when all candidates are blocked or windows full. Returns created views.
- `confirm_sent(key, *, sent_at, now) -> bool`: sets `sent_at` and
  `deadline = sent_at + response_timeout` once; repeats do not extend it. While
  VERIFYING it may fill `sent_at` but never sets a deadline. `sent_at` must be
  `<= now` and not before the request's enqueue time.
- `start_verification(key, *, now) -> bool`: true for a live, not-yet-verifying
  request when no other request for that piece is verifying; clears the
  deadline, keeps slot and reservation. Otherwise false, no deletion.
- `finish_verification(key, *, valid, now)`: `valid` must be a real bool. Only
  a VERIFYING record is acted on (else `()`). `True`: piece becomes owned, one
  `completed` outcome (reason `verified`), then all other requests for the piece
  are removed as `canceled` (`another_request_completed`). `False`: that
  request alone is removed as `invalid` (`verification_failed`).
- `reject(key, *, now)` / `send_failed(key, *, reason, now)`: remove an
  unanswered matching request as `canceled` (reason `rejected` / supplied);
  ignored for VERIFYING requests.
- `cancel(key, *, reason, now)`: cancels any matching request, including
  VERIFYING.
- `disconnect(connection_id, *, now)`: cancels all its requests (reason
  `disconnected`), drops its availability, frees the slot and provider; the ID
  stays retired. Repeating returns `()`.
- `expire(*, now)`: removes unsent non-verifying requests aged >=
  `send_confirm_timeout` (`send_unconfirmed`) and sent non-verifying requests
  with `now >= deadline` (`response_timeout`), as `expired` outcomes. No
  replacements are created.
- `snapshot() -> dict`: fresh JSON-compatible data: `num_pieces`, `owned`,
  `piece_state_counts`, `connections` (id, provider, availability,
  permissions), `pending` (flat request records), `outstanding` (per-connection
  counts), `counters` (issued/completed/invalid/expired/canceled) and
  `retired_connection_ids` (count).

Matching always uses all three key fields, so late events for a removed request
never touch its replacement. Removal decrements the source count once and
clears only that key from the piece's reservation set. Piece state is derived:
HAVE if owned, else VERIFYING, else REQUESTED if any reservation survives,
else MISSING.

Memory note: the set of every connection ID ever registered is kept for the
session to prevent reuse, so many reconnects grow memory linearly. No per-event
history is retained.

## Command line
`python -m request_pipeline --input request_pipeline/example.json`

Input: JSON object with `num_pieces`, optional `initially_owned`, optional
config fields, and `actions`. Each action has `op` (an API method name, or
`snapshot`) and that method's named arguments; keys are
`{"connection_id":..,"request_id":..,"piece_index":..}`; for `fill`, source keys
of `candidate_orders` are decimal strings. Output: one JSON object with
`results` (`action` number, `op`, `result` per action) and the final `snapshot`.
Any unknown field/operation or invalid action prints `error: action N: ...` to
stderr, exits 2 and processes no later actions.
