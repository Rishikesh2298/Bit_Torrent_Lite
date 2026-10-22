# Preparation repairs — 22 October 2026

These changes were made during the authorized PREPARE stage, before any frozen
acceptance attempt. They are not acceptance results. The author of this record
did not collect or execute tests. Root will record sequential diagnostic runs.
No contributor implementation, original document, prior evidence or history was
removed. Small-piece generic APIs and the existing overwrite/duplicate-key
policies were left unchanged.

The exact four pre-edit source files and their SHA-256 manifest are retained at
`.validation/final-acceptance/preparation-preimages/requirements-audit-b8e72d964f6a4d44a57c5f7effc30d6f/`.
These are preimages, not historical test results or an acceptance source freeze.

| File | Pre-edit SHA-256 | Reason and minimal edit |
|---|---|---|
| `storage/metadata.py` | `7341cbaf075109c96f36d276fd160d871346c94ba53ec014a20b7ceeb1021a27` | R original line85 explicitly limits metadata to256KiB; G line757 requires validation before parsing. Replace unbounded `read()` with `read(MAX_METADATA_BYTES + 1)` and reject length above262144 before hashing/parsing. Preserve exact-byte IDs and generic positive piece sizes. |
| `storage/file_store.py` | `4e58d8ae287a0fe78386b3fc73da2e0a25ed7922e7b4d11f02d6cacca9b9577c` | NC10/SP02 require bounded reads even when a stored piece is replaced with an oversize file. Read expected length+1 instead of unbounded contents; the existing exact-length/hash rejection and affected-bit clearing remain intact. |
| `discovery/tracker_client.py` | `21c08b68e866a6213ad723b6efcfde7d9c399fc4e3ea1cc645eca4e9c89225e0` | SP01 requires controlled rejection of bounded deeply nested JSON. Classify `RecursionError` from JSON decoding as the existing `TrackerRequestError("bad_response", ...)` rather than letting it escape. No broad exception suppression added. |
| `common/run_log.py` | `db4499edc79f11e4674f45f545df7081d803d367b28ecaaf41e009506cd98c29` | EV02 requires destination-change and concurrent logging behavior. Open the replacement destination, switch the stored handle, and close the previous one. Construct the timestamped record inside the existing serialization lock so recorded timestamp order matches physical line order. Nonfatal logging and permissive legacy-reader behavior remain unchanged. |

The operative small diffs are:

```diff
# storage/metadata.py
+MAX_METADATA_BYTES = 256 * 1024
-raw_data = file.read()
+raw_data = file.read(MAX_METADATA_BYTES + 1)
+if len(raw_data) > MAX_METADATA_BYTES:
+    raise ValueError(f"metadata exceeds maximum input size of {MAX_METADATA_BYTES} bytes")

# storage/file_store.py, cached-piece path only
-data = file.read()
+data = file.read(self.metadata.expected_piece_size(index) + 1)

# discovery/tracker_client.py, parse_response only
-except (UnicodeDecodeError, json.JSONDecodeError):
+except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):

# common/run_log.py, _open
-_file = open(path, "a", encoding="utf-8", buffering=1)
+opened = open(path, "a", encoding="utf-8", buffering=1)
+previous = _file
+_file = opened
 _path = path
+if previous is not None:
+    previous.close()
```

The `emit` record construction moved into `with _lock` after a destination is
available. Its field names, values, JSON serialization and exception policy did
not otherwise change.

Regression methods are in
`bittorrent_lite/tests/acceptance/test_storage_contracts.py`,
`test_discovery_contracts.py`, and `test_logging_contracts.py`. In particular:

- `test_metadata_input_byte_limit` and `test_metadata_read_is_bounded_before_json_parse`
- `test_cached_piece_read_is_bounded_even_if_replaced_with_oversize_data`
- `test_bounded_deep_response_has_controlled_rejection`
- `test_changed_event_destination_closes_previous_descriptor`
- `test_concurrent_timestamps_follow_serialized_record_order`

The timestamp regression deliberately lets the second producer acquire the
serialization lock first. It asserts line order and independently supplied
monotonic values; sampling outside the lock produces the inverted timestamps
and fails. This is a local concurrency regression, not real-network evidence.

All cases, including additional non-repair boundary tests, have explicit
subclause mappings in
`bittorrent_lite/tests/acceptance/case_mapping_storage_discovery_common.json`.
That file records static expected node identities only; fresh collection and
actual setup/call/teardown outcomes are still required.

## Runtime telemetry preparation

The exact pre-edit copies and manifest for these three files are retained in
`.validation/final-acceptance/preparation-preimages/runtime-telemetry-c2153b4be3064ad0b7dedecd0fae3344/`.
No tests were collected or executed by the author of this change.

| File | Pre-edit SHA-256 | Reason and scope |
|---|---|---|
| `application/runtime.py` | `0f8555ccd05786d9db51d17aca368e0fb406ab1213c78d8fa5e997540a8b098b` | Status previously appeared only on state changes. Emit approximately every second as well, including actual connected-peer and pending-request counts. Add an optional once-per-second resource sampler with explicit unavailable/error records and finite nonnegative numeric validation. Move successful piece provenance to the bridge's exact commit boundary. |
| `application/adapters.py` | `da92bec9967bde9f6d2379367aeba868f703a14a36202a761fa1feebcaf66051` | Observe actual storage verification calls and committed ownership after each received piece. Report cid/rid/piece/source/bytes; distinguish length, hash, local I/O and unclassified false results. Emit owner-thread scheduler state after event handling and each runtime tick, including request windows, upload jobs, reservations and confirmed/pending permission states. No coordinator policy changed. |
| `networking/runtime_connection.py` | `a8a92f6af91c277f00950e7ba026cc3ac4a6f60f5c932d3127ba0ba39259d320` | Wrap the actual frame socket calls with byte observers. Emit complete-write records for all 11 message types only after sendall succeeds; incomplete writes retain an unknown byte count. Receive records count actual returned bytes, with a separate semantic-rejection record. Include cid/rid/piece/payload length/peer/endpoints and writer queue samples. Standalone PeerConnection remains unchanged. |

Event schema and proof boundaries:

- `frame_sent`: exact `frame_bytes` from completed socket calls, `payload_bytes`,
  `message_type`, nullable `connection_id`, `request_id`, `piece`, confirmed
  `remote`, expected identity and local/remote endpoints. It is emitted before
  the existing scheduler completion callback. Enqueue and withdrawal never
  generate this event.
- `frame_send_failed`: `frame_bytes: null`, `partial_bytes_known: false` and
  exception type. A failed sendall never exposes how many bytes reached the
  peer; complete-frame totals must not claim these unknown bytes are zero.
- `frame_received`: complete decoded frame and exact bytes returned by recv.
  Session validation happens next; `frame_rejected` explicitly records semantic
  rejection. `frame_receive_failed.received_bytes` counts only returned bytes
  and carries no complete-frame claim.
- `PIECE_VERIFICATION` distinguishes `stored`, `length_mismatch`,
  `hash_mismatch`, `local_io_error`, and `store_rejected_unclassified`.
  Only the before/after transition to owned produces `PIECE_VERIFIED` with
  source/request provenance. A duplicate/stale response with no storage call
  produces `PIECE_IGNORED`, never another verified-byte credit.
- `SCHEDULER_SNAPSHOT` is emitted after each owner-thread event/tick. Its
  neighbors, pending requests, upload service and choke policy are the actual
  coordinator snapshot. Queue lengths are point observations. Their maximum
  must not be claimed as a continuously observed high-water mark.
- `STATUS` reports actual state at about one-second intervals and state changes.
  `RESOURCE_SAMPLE` uses only an injected provider's valid numeric metrics.
  Absent/failed/invalid providers emit `RESOURCE_SAMPLE_UNAVAILABLE` or
  `RESOURCE_SAMPLE_ERROR`. Real process metrics still need the actual provider
  and independent acceptance validation; fake-clock tests are not OS evidence.

`tests/acceptance/test_runtime_telemetry.py` contains 38 statically expected
cases mapped in `case_mapping_runtime_telemetry.json`. The 24 transport cases
use a controlled in-memory socket and are unit procedures. The remaining 14
use actual scheduler/storage/runtime composition with a fake backend and are
integration procedures. They provide no live TCP or multi-host acceptance
credit. Root must collect and execute them sequentially before freezing.

## E2E support preparation

The pre-edit `tests/end_to_end/support.py` is preserved at
`.validation/final-acceptance/preparation-preimages/e2e-support-bb7f80b2618c4e9f91122a46083af106/support.py`,
SHA-256 `2f5353d1aa5cbb6236cd7f3cc18bccae6bc56976597913dca283d71205325fc4`.
The original E2E test procedures/assertions and tracker CLI are unchanged.

The helper previously repeated one 64 KiB block, mixed JSON and console text in
a `.jsonl` stdout file, silently ignored all JSON errors, did not register
children and ignored most already-exited nonzero child results. PREPARE changes:

- Generate bounded deterministic, distinct full pieces; retain seed, whole-file
  digest and every piece digest in `fixture.json`. This is explicitly a
  **diagnostic** fixture with `acceptance_eligible: false`, no fresh challenge
  and `source_isolation_verified: false`. Existing source files are never
  overwritten. Creating such a fixture is not independent challenge issuance.
- Capture binary raw `.stdout`/`.stderr` streams and assign a separate
  `.events.jsonl`, `BTL_PROC_ID` and `BTL_RUN_ID` per child. Register the actual
  child PID/creation identity immediately after Popen when
  `ACCEPTANCE_PROCESS_REGISTRY` is set, passing its cooperative stop file.
  A registration failure remains fatal and retains the child for cleanup.
- Preserve the uppercase public CLI `events()` API used by existing tests.
  Only precisely formatted known console lines are excluded. Every malformed
  complete JSON line fails. Dedicated `structured_events()` is canonical for
  metrics and validates duplicate keys, finite numbers, proc identity and
  nondecreasing monotonic time. A concurrent incomplete tail is temporarily
  excluded; an ordinary final tail fails. A declared completed kill may leave
  a raw preserved tail, whose offset, length and reason are recorded.
- Record kill intent and completion with PID, registered identity and UTC/
  monotonic times. Validate expected platform kill codes. Verify all ordinary
  children exit zero, and all ordinary peers have exactly one clean STOPPED and
  structured stopped-exit record. Capture already-exited failures too.
- Appendix C.1 retains tracker host/port-only CLI. Tracker teardown is declared
  before spawn and recorded separately: Windows TerminateProcess code1, POSIX
  handled SIGTERM code0 or signal exit -15. This is cleanup evidence, never an
  ordinary peer success. Forced peer cleanup remains a failure.
- Completion checks exact byte size, bounded-stream SHA-256 and a bounded
  bytewise comparison when the source pathname is available. A missing or
  renamed source does not establish access denial. The helper never writes
  download payload bytes and cannot grant redistribution acceptance credit.

`tests/acceptance/test_e2e_support_contracts.py` has 22 statically expected unit
cases, mapped in `case_mapping_e2e_support.json`. Every process/port action is
mocked. The author did not collect or execute these tests or launch a child.
Root must validate actual process registration, termination, dedicated streams
and independent hashes before acceptance use. Actual process resource sampling
remains the separate root-owned CLI integration.

## Additional executor preparation repairs (2026-10-22)

All references below are **preparation diagnostics**, stored under
`BitTorrent/.validation/final-acceptance/preparation-20261022-01/diagnostics`.
None is a frozen acceptance attempt, an independent review, or permission to
combine results into an acceptance pass. Original plans and historical evidence
were preserved. Failed command directories and raw streams remain intact.

- `networking/framing.py` now rejects nonzero control-message payloads,
  non-integer wire BITFIELD entries and request IDs outside 1..2^63−1 before
  sending or consuming payload bytes. Deep header JSON produces a controlled
  ValueError. Generic standalone message constructors remain unchanged.
  Diagnostic016 reproduced malformed INTERESTED acceptance; 017 and 022
  exercised the repair and literal wire vectors.
- `storage/metadata.py` converts bounded deeply nested JSON parser recursion
  failure to a readable validation error. `application/network_backend.py`
  exposes side-effect-free local network-input validation. `application/cli.py`
  uses it before `--check-config` can succeed, checks portable output basenames,
  source/output aliases including hard links, source integrity and requested
  resource sampler availability before output construction. Generic small-piece
  storage APIs were retained. Preimages are in
  `.validation/final-acceptance/preparation-preimages/local-input-validation-20261022`.
  Diagnostic031 exposed an insufficiently deep test fixture; the assertion was
  retained and the parser-boundary fixture corrected. Diagnostic032 passed 70
  local-input and existing runtime cases.
- The recorder guardian now tolerates a process naturally exiting during
  descendant discovery while preserving actual access errors, and rejects PID
  reuse between cached enumeration and fresh identity lookup. Diagnostics010
  and 012 retain the original failed guardian records despite child exit zero;
  later passing records do not rewrite those failures.
- The installed scheduler-demo verifier was corrected to the actual `sent`
  and `deadline` schema, using the exact retained diagnostic030 output as a
  regression fixture. A missing `sent_at` was a verifier mistake, not a product
  failure. Packaging and standalone checks must still be repeated together on
  the final unchanged source revision.
- `tests/end_to_end/support.py` verifies both tracker readiness telemetry and
  an actual HTTP stopped announce, preserving request/response bytes without
  adding a tracker member. Diagnostic034 completed the file transfer but failed
  strict UTF-8 decoding of the Windows code-page ellipsis in a console message.
  The launcher now explicitly sets `PYTHONIOENCODING=utf-8` and `PYTHONUTF8=1`;
  strict decoding is retained. Diagnostic035 passed 71 helper cases and
  diagnostic036 passed three real TCP smoke transfers. These use diagnostic
  fixtures on one shared account, not source-isolated challenge evidence.
- Independent literal partition oracles cover 1/P−1/P/P+1/2P sizes. Equal-rarity
  tests use equal availability and a finite frozen seed domain. Failed piece
  verification explicitly leaves zero ownership and sends no HAVE. Overflow
  JSON numbers such as `1e999` are rejected by the evidence parser.
  Diagnostic037 passed 106 cases.
- `common/run_log.py` retains ordinary optional nonfatal logging, with a new
  explicit `BTL_LOG_STRICT=1` mode for supervised evidence. Strict mode requires
  a fresh file, records sequential `log_sequence` plus actual `log_pid`, flushes
  each record, and raises on open/serialization/short-write/flush failure.
  The strict verifier can require an independently observed interpreter PID
  and contiguous records. This detects missing interior records; it cannot
  reconstruct an event lost between an actual operation and an abrupt kill.
  Preimage SHA-256 is
  `dfd61781535925b03591a0f00dcc7b0dc22dcd8c33fad175ef74b420300b6545`
  at `.validation/final-acceptance/preparation-preimages/strict-log-20261022/run_log.py`.
  Diagnostic039 passed 66 strict/legacy logging and evidence cases. Strict live
  transfer behavior needs its own fresh execution after this change.
- Diagnostic040 passed 272 preserved storage/common/scheduling/message-object
  cases. Diagnostic041 passed 29 new literal framing/session/concurrency cases.
  Diagnostic042 stopped at the first unexpected result: after 312 passes,
  Matplotlib 3.10.3 called deprecated pyparsing 3.3.3 `oneOf`. Warnings stayed
  fatal. The exact Matplotlib 3.10.7 wheel was downloaded and installed in the
  disposable environment (043/044), and the project experiment minimum was
  raised to 3.10.7. This uses the
  [upstream compatibility repair](https://github.com/matplotlib/matplotlib/issues/30617),
  not a warning filter or a test deletion. The old wheel remains preserved.
- Diagnostic045 confirmed the repaired plotting import, then stopped at a
  newly authored test's incorrect `FileStore.get_piece` call after 59 passes.
  Changing the call to its documented `read_piece` API retained the exact byte
  assertion. Diagnostic046 passed all 69 plotting/wire/telemetry cases,
  including same-length bad-hash recovery from a healthy alternate provider.

- Tracker HTTP parsing now rejects non-ASCII and oversized decimal Content-Length
  before integer conversion and converts excessively nested JSON into a controlled
  400 response. Diagnostic048 passed 111 parser, HTTP and preserved tracker/client
  cases. Diagnostic047 passed 81 recorder/measured controls, including rejecting
  changed process identities before explicit registry publication.
- Diagnostic049 passed 45 stress controls, then stopped when the new measured
  lifecycle helper incorrectly sent GET to the tracker's POST announce endpoint.
  The helper now sends the exact stopped-announce JSON contract and retains actual
  request/response bytes and hashes. The endpoint behavior and response assertions
  were not weakened; its focused controls passed in diagnostic054.
- The standalone request-pipeline CLI now returns its existing error exit code 2
  for malformed UTF-8 and excessive JSON nesting. Recovery JSONL now reports a
  structured RecursionError and continues with the same policy state. Diagnostic050
  passed 110 new and preserved standalone cases. Original source preimages remain
  under `preparation-20261022-01/preparation-preimages/standalone-json-20261022`.
- Stress waits now enforce the deadline both before and after polling and predicate
  evaluation. Diagnostic051 passed 49 helper cases, including four fake-clock
  regressions. Those unit controls are not a stress workload result.
- Diagnostic052 stopped after 114 passes because an existing experiment test left
  its tracker JSONL file open. The test now reads it in a UTF-8 context manager,
  preserving every assertion and warnings-as-errors. Diagnostic053 reran the
  complete networking, discovery and integration directories: 511 passed.
  Synthetic stand-in experiment tests remain labeled synthetic and receive no
  real-network measurement credit.

- Diagnostic055 exercised a finite supervisor crash with a separate live guardian.
  The supervisor exited with its predeclared code 17; its worker, grandchild and
  guardian exited zero, with retained OS identities and raw evidence. This is
  guardian-helper evidence, not the original launcher's complete crash case.
- Swarm helpers now distinguish Windows virtual-environment redirectors from the
  actual interpreter using live OS ancestry, arguments and creation times. Both
  identities are registered and checked during cleanup. A locally created registry
  is explicitly labeled as having no external guardian. Windows teardown records
  the API actually used: psutil's forced termination is expected to return 15,
  whereas the Popen fallback declares 1. The exact statuses are checked rather than
  accepted as an arbitrary nonzero exit. Diagnostic062 passed 88 controls and
  diagnostic063 passed three real strict-log transfers with exact output bytes.
- Diagnostic065 completed a real transfer but rejected initial-seeder readiness
  as if it were a downloaded completion. The verifier now preserves the existing
  product event meaning and independently checks full initial source ownership,
  exact assembled bytes and zero newly downloaded byte/request credit. Seeders
  remain excluded from downloader completion/timing totals. Diagnostic066 passed
  89 controls and diagnostic069 passed the repaired real transfer lifecycle.
- Diagnostic067 observed the original launcher's finite target-kill path stop its
  actual interpreter while leaving an independently owned control alive. No
  speculative launcher repair was made. This probe does not prove cleanup after
  the original supervisor crashes. Its later assertion strengthening requires
  a fresh execution.
- Diagnostic068 passed 132 installed-transfer, portability, interpreter-ownership
  and stress-helper controls. Real wheel/sdist transfers remain a separate stage;
  these controls do not supply their execution evidence.
- Diagnostic070 stopped at a coverage-recorder defect after the real transfer:
  startup retained `sys.argv` by reference, and Python's module execution rewrote
  element zero before the shutdown record. Startup now copies the list. The
  regression deliberately mutates the original list and checks unchanged startup
  identity in the finish record. Strict identity equality remains required.
  Preimages are retained in `preparation-preimages/coverage-argv-070`; the repair
  and complete five-interpreter procedure still require fresh diagnostic runs.

The complete acceptance restart count remains zero because preparation has not
opened an acceptance attempt. A subsequent acceptance failure requires a new
attempt from Phase00; these diagnostic reruns cannot substitute for that rule.
