# Fault helpers, version 1

Status: authored PREPARE procedures and tests; not execution evidence. All
diagnostics must run sequentially under the campaign command recorder/guardian.
Use `-x` and fresh JUnit/output paths. Do not combine diagnostic outputs with an
acceptance attempt or advance past an unexpected failure.

The helper is `bittorrent_lite.acceptance_tools.faults`. It uses only the standard
library and binds IPv4 loopback ephemeral ports. A proxy upstream must be an
explicitly owned loopback endpoint. A campaign case must record how that endpoint
was created; the helper does not discover or connect to arbitrary peers.

## Execution partition

| File | Partition | What its evidence can establish |
|---|---|---|
| `test_fault_tools_unit.py` | PREPARE helper validation; Phase03 isolated units | Independent fixture bytes, action validation, exclusive traces, deterministic local I/O failures, owned-path guard and leak/untriggered negative controls |
| `test_wire_validation_regressions.py` | Phase03 isolated codec units | Ten controls require payload0; BITFIELD JSON array has exact integer0/1 values; four request-bearing messages enforce IDs1…2^63−1 |
| `test_fault_tools_socket.py` | PREPARE helper validation; Phase04 socket integration | Real TCP bytes, independent frame decoding, fragmentation/coalescing, delay/trickle/rate control, exact corruption/drop, deadlines, bidirectional relay and owned cleanup |
| `test_fault_tools_storage_integration.py` | PREPARE helper validation; Phase04 filesystem integration | Real FileStore I/O reaches six failure seams; preserved source and existing output; no new owned piece on failed write/replace; bounded handles |

Invoke each named file explicitly, for example the recorder launches
`python -m pytest -x bittorrent_lite/tests/acceptance/test_fault_tools_unit.py`
with its own additional JUnit/coverage/ledger arguments. Running a socket test
under the unit partition is not valid phase ordering. Expand every parameterized
identity using genuine collection before freeze; the accompanying mapping lists
selectors and domains, not observed pass counts.

## Finite socket scripts

Create `FaultTrace(new_path, campaign_case_owner)` outside the peer/proxy context
and close it only after all owned threads exit. Trace paths use exclusive create.
Use a list/tuple of at most4096 actions with total send/receive bytes at most8MiB.
Each listener accepts one client. Peer and proxy have explicit monotonic deadlines,
50ms socket polls, bounded joins and no process-name operations.

- `Send(data, fragments=(...), gap_s=...)` writes the exact declared fragment sizes.
  `Send(frame1 + frame2 + frame3)` supplies coalesced frames; TCP remains free to
  split/merge kernel delivery. Never infer receive boundaries from send calls.
- `Pause(seconds)` delays a script step. One-byte fragments with positive gap
  make a trickle. `bytes_per_second` paces cumulative local writes; it is a
  userspace test constraint with a bounded initial chunk, not a claim of OS packet
  shaping or instantaneous link throughput.
- Timing tests first require the literal `begin-v1` token through `Receive`.
  The client records its origin immediately before sending the token. Both
  immediate and120ms delayed client scheduling after connection are covered;
  socket acceptance cannot start the timed fault before the measuring client.
- `Receive(length, expected=literal_bytes)` checks actual bytes against the
  predeclared oracle. `ExpectEOF()` rejects any extra byte.
- `Drop(reason)` must be the final action. It records the trigger before closing
  the owned socket. EOF/truncation is an expected test outcome only when the case
  explicitly asserts the corresponding product response.
- `Send(..., corrupt_offset=n, xor_mask=mask)` changes exactly one declared byte.
  For payload corruption, calculate the offset from independent literal framing
  and keep the header/length unchanged. The trace records original/changed hashes,
  offset/mask and actual writes; it does not invent verified receipt or rejection.
- `RelayRule` provides independent outbound/inbound chunk, delay, rate, exact
  stream-byte corruption and drop-offset controls. Each direction has a byte
  budget. `proxy.wait()` rejects unused corruption/drop triggers and incomplete
  closure. `peer.wait()` rejects script mismatch, timeout or premature cancellation.

Inspect actual `socket_write`, `socket_read`, `proxy_write` and `proxy_read` rows:
each contains count, hex bytes, SHA-256 and endpoints. A write is a local write
observation; receiver logs and independently hashed stored files are still needed
for complete transfers. `fault_triggered` is not itself proof the target handled
the fault. Preserve peer/proxy traces, product logs and source/partial/output
hashes together. Expected helper-negative tests assert the error explicitly.

## Owned storage injection

`StorageFaults(new_root, trace, [StorageFault(operation, call, after_bytes, errno)])`
creates a previously nonexistent owned directory. Every read/write/replace is
checked against that root. Ancestor symlinks/junctions and existing hard links are
rejected. The namespace must remain private to the case; this is deterministic
test instrumentation, not a hostile-filesystem security boundary.

Normal operations are `read`, `write`, `replace`. Within `adapter.phase("assembly")`
they are `assembly.read`, `assembly.write`, `assembly.replace`. Call numbers are
separate for each operation/phase. Read/write faults can perform a stated prefix
then raise a real `OSError` with `EIO`, `EACCES` or `ENOSPC`. ENOSPC is explicitly
simulated; no disk filling occurs. Replace faults occur before the real replace.

Use `adapter.bind_module(pytest_monkeypatch_context, file_store_module)` to patch
only that module's `open`, `NamedTemporaryFile` and `Path` bindings. It does not
patch global `builtins.open`, `pathlib.Path` or `os.replace`. Build/rebuild the
FileStore after binding when its stored Path objects must use the replace seam.
Ordinary independent hashing still uses the real hashing implementation.

Temporary cleanup performed by FileStore remains scoped to owned paths. The
adapter records the exact bytes before cleanup; original source/pieces/existing
outputs are separately hashed and asserted unchanged. Always call
`adapter.assert_finished()` after streams close; an unused declared fault or an
open adapter handle fails validation. Restore module bindings before returning.

These helpers do not complete the Phase08 provider-recovery or storage-system
campaign by themselves. Those cases must exercise the real scheduler/backend,
assert no false HAVE/COMPLETE, distinguish local storage errors from remote
corruption, verify healthy-source recovery and include command/process evidence.
LAN, supported-OS, human and independent-verifier requirements remain separate.
