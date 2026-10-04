# Prabhat: initial scheduler review and test contracts

Reviewed on 4 October 2026 against main commit `2c290fb` and the six supplied
planning documents. This is a code audit, not evidence of a working swarm.

## What exists

| Owner / area | Evidence in the repository | Current status |
|---|---|---|
| Rishikesh / file management | Splitting, SHA-256, metadata save/load and file ID, verified piece storage, source validation, assembly; unit and storage integration tests | Implemented; 32 existing active tests pass |
| Debargha / tracker and discovery | Tracker state/server and tracker client signatures | Stubs; tracker tests are skipped |
| Anik / protocol and networking | Message dataclasses and header conversion; framing and connection signatures | Partial scaffolding; transport methods are stubs and protocol tests are skipped |
| Prabhat / selection, requests, upload policy | Initial review found picker/request/choking stubs; this branch now implements neighborhood availability and rarest-first selection | Picker unit behavior verified; request lifecycle, coordinator and upload policy remain unfinished |
| Shared peer integration | PeerState container and CLI argument parsing | No implemented peer loop or demonstrated network transfer |
| Experiments | Package directory and README experiment list | No runner, measurements or plots |

The original README checkboxes overstated implementation and have been corrected. Existing file-manager
integration tests exercise storage locally; they do not prove TCP transfer,
downloader redistribution, six-peer concurrency or failure recovery.

## This small contribution: initial piece picker and tests

`tests/test_prabhat_selection_contract.py` adds socket-free fixtures for:

- Initial zero availability and a defensive availability snapshot.
- The plan's A/B/C neighborhood count example: `[2, 2, 2, 1, 1]`.
- Duplicate BITFIELD/HAVE and repeated disconnect accounting.
- Unique-rarest selection, owned/reserved/source exclusion, and no candidates.
- Replacement snapshots, caller-list isolation, seeded random ties and invalid inputs.

All 22 picker cases now pass without skips or expected-failure markers. The
picker stores a private snapshot per neighbor and recomputes counts, so duplicate
advertisements and repeated disconnects cannot inflate or underflow counts.
Selection excludes owned/reserved pieces, ignores zero availability, and chooses
randomly among eligible minimum-rarity indices. Permission and source-window
checks still belong to the future coordinator. This is a P02/P06 subset, not a
complete scheduler or a real transfer.

Temporary in-process fault probes confirmed the tests reject an aliased
availability snapshot, incorrect counts and an unexpected exception; injected
methods were restored and the final suite passed afterward.

## Coordinator contract to agree before P03/P04

These are proposed decisions from the master plan, not completed team handoffs:

- One coordinator owns neighbor state, piece states and reservations; transport
  workers publish events. Map existing directional flags explicitly:
  `am_choking` = we choke remote, `peer_choking` = remote chokes us,
  `am_interested` = our interest, `peer_interested` = remote interest.
- Start with one pending request per connection. Reserve a missing piece before
  enqueueing. Success follows MISSING -> REQUESTED -> VERIFYING -> HAVE only
  after successful storage; rejection/corruption returns it to MISSING.
- Match cleanup and responses by connection ID plus request ID plus piece index.
  Start response deadlines after FRAME_SENT, and ignore stale events.
- Keep outgoing downloads separate from incoming uploads. An I/O error is a
  local failure, not provider corruption. COMPLETE requires final assembly.
- Only consider active, unchoking sources with available request slots. The
  current picker API has no permission/phase input: the coordinator must gate
  calls. Neighborhood rarity includes active neighbors currently choking us.

### Integration repairs and remaining mismatches

- Fixed PeerState to use `NeighborInfo`. Tracker client/state now import the
  existing `PeerRecord` under their legacy `PeerInfo` spelling. Removed choking's
  unused import of nonexistent `OPTIMISTIC_UNCHOKE_INTERVAL`. These are small
  shared-contract repairs; no tracker or transport implementation was added.
- `tests/test_module_imports.py` verifies that all 25 package modules import.
- RequestManager currently keys by piece index and documents a global limit;
  the plan needs connection/request correlation and per-neighbor windows.
  Its prose says final window five, while config/master specify four.
- The picker now counts local neighbor snapshots. The future coordinator must
  register only active neighbors, gate choked/full sources and remove closed
  connections. No global swarm map is used.
- The protocol document describes a binary handshake while message classes use
  JSON headers. Agree framing and validation with Anik before integration.
- Metadata generation CLI now calls the existing metadata functions, reports
  failures through its exit status and refuses to overwrite the source file.

## Next bounded step for Prabhat

Implement the sequential one-request baseline and its fake-event lifecycle
after agreeing interfaces. Do not jump to pipeline four, recovery or upload
policy before that baseline. These tests prepare part of P02; P01/P02 as a
whole, including fake transport/store/clock and permission tests, remain open.

## Verification

Run `python -m pytest tests -q` in an environment with pytest installed.
This review used Python 3.12, pytest 9.1.1 and a writable local temporary folder:
`python -m pytest tests -q --basetemp=env/pytest-temp`.
Unchanged baseline: **32 passed, 56 skipped**. Initial picker/import work:
**79 passed, 56 skipped**. A subsequent repository-wide regression audit found
and fixed defects beyond those baseline tests:

- Reject malformed metadata types/hashes and invalid sizes/indices predictably.
- Recheck cached pieces against disk; verify seeder bytes before serving.
- Clear source advertisements on failed revalidation and publish them only
  after the whole source validates.
- Write pieces and assembled outputs through temporary files; preserve existing
  output on hash/I/O failure and clean temporary files.
- Copy remote bitfield snapshots and reject invalid peer-state indices.
- Make the existing metadata CLI produce a loadable file and report failures.

The expanded tests include all message-object conversions, binary piece-size
boundaries, maximum 64 MiB files, simulated I/O failures, 3,200 randomized
picker transitions and 16 concurrent neighbor writers. `pytest.ini` restricts
default discovery to repository tests, excluding locally installed dependencies.
Final extensive run: **167 passed, 56 skipped, zero failures or errors**.
Python compilation and `git diff --check` also passed.
The 56 original skipped tests are legacy placeholders, including duplicates for
behavior now covered by active tests. Tracker/request lifecycle/transport remain
unfinished. No network integration was run; a passing suite does not mean the
unfinished swarm works.
