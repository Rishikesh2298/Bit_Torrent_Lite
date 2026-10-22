# Unit-stage validation — 22 October 2026

**Final result: 537 passed, 0 failed, 0 errors, 0 skipped and 0 xfailed.**
The final combined run took 13.70 seconds and reported 14 third-party warnings.
The unit gate passes; this does not establish a working complete system/swarm.

Full collection discovered **737 tests** in 45 nonempty test files. An additional
existing empty `test_handshake_connection.py` was preserved. Collection imports
test modules but does not execute their bodies. **200 tests remain deferred.**

## Environment and scope

Windows; Python 3.12.14; fresh local `.venv`; editable project installation;
pytest 9.1.1; pytest-timeout 2.4.0; 30-second per-test timeout. Plot/import
dependencies: matplotlib 3.10.3, NumPy 2.2.6 and pandas 2.2.3.
`pip check` reported **No broken requirements found**.

Branch: `refactor/member-owned-layout`, based on main `6ea28b1`.
The tested working tree includes uncommitted restructuring and test fixes;
testing the base commit alone will not reproduce this result. Source/config
snapshot SHA-256: `592d5c7a0d2e3e60ecf160de27a59ec5ac95bccbe54288689d67f54e34a2d093`.

The unit stage includes isolated algorithms, validation, filesystem operations,
fake-announce workers, standalone policy/metadata CLIs, and imports. It includes
threads inside isolated components, but defers live HTTP, socket/peer-network
integration, combined runtime transfers and multi-process experiments. Tests are
classified by execution behavior, not folder name. Some isolated tests live in
`tests/integration/`. No line/branch coverage percentage is claimed.

## Results

| Group | Passed | Tested responsibilities |
|---|---:|---|
| Storage — Rishikesh | 57 | Splitting, hashing, metadata, piece boundaries, both stores, verification and assembly errors |
| Discovery — Debargha | 47 | Membership, isolation, expiry, validation, fake-announce retries, shutdown and bounded queues |
| Networking logic — Anik | 24 | Message round trips, malformed handshakes, bitfields and direct piece-handler behavior |
| Scheduling/uploads — Prabhat and preserved legacy modules | 224 | Pickers, reservations, request windows, recovery, choking, upload admission/cancellation/accounting and standalone policy CLIs |
| Shared regressions/imports/portability | 168 | 88 existing regression cases, 75 package-module imports and 5 new portable-path/CLI checks |
| Application configuration/compatibility | 17 | Runtime configuration, CLI validation without networking, safe output paths and both choking exports |
| **Total** | **537** | **All passed together after fixes** |

Every collected test belongs to exactly one unit group or the deferred stage.
The final 537 passing node IDs exactly match the unit allowlist. No tests have
skip, skipif or xfail markers. Deferred cases are not counted as pytest skips.

## Failures and fixes

1. **Malformed-handshake fixture:** networking attempt 1 stopped after 10 passes.
   `test_handshake_wrong_protocol` constructed `Handshake(None, ...)` outside its
   expected-error assertion. Constructor validation therefore fired before the
   parser was reached. The same fixture/constructor behavior exists in merged
   main. The fixture now mutates a valid raw header to exercise each invalid
   wire version. All four original invalid values remain. Four constructor-type
   rejection cases were added. Production validation was not relaxed.
   **Full networking rerun: 24 passed.**
2. **Conflicting export assertion:** application attempt 1 stopped after 10
   passes because a test required `ChokingManager` to be absent, while the legacy
   choking tests require it. The restructuring had restored that existing class
   alongside `ProjectUploadPolicy` to preserve both implementations. The renamed
   compatibility test now checks both class identities and their export list.
   No implementation was removed or replaced.
   **Full application rerun: 17 passed.**

After both corrections, the entire approved unit set was rerun from the start:
**537 passed**. This validation stage did not change production algorithms.

## Accidental stage-boundary violation

Application attempt 2 contained a trailing blank selector. Pytest interpreted
it as selecting the full suite. Five portability tests passed and the first
synthetic experiment, `test_baseline_run_completes_and_records`, started before
the command was interrupted. **This crossed the user's approval boundary. It
was a runner error, and the attempt is not an accepted validation result.**

Process inspection afterward found no remaining Python processes matching the
interrupted runner, pytest or project commands. Its log is retained. Two guards
were then added: reject blank selectors, and abort at collection unless selected
node IDs exactly equal the approved group allowlist. Application attempt 3 ran
only its 17 tests; the final combined run ran exactly 537. No subsequent
integration/system test was executed.

## Import/path and preservation findings

- All **75 package-module imports passed**, including relocated production and
  experiment modules. No unresolved production import/path failure appeared.
- Root discovery passed after changing to an unrelated working directory.
- Peer CLI help, application CLI help and tracker help passed outside the
  checkout with `PYTHONPATH` removed. No servers are started by these help calls.
- Metadata generation passed with paths containing spaces outside the checkout,
  preserving source bytes and the expected SHA-256.
- All **148 original mapped files** remain. Static comparison confirms original
  function/class definitions remain, accounting for the documented test rename.
  All five original plans retain their recorded hashes. No Git history rewrite,
  commit or push was performed.
- These are Windows checks, not proof of Linux/macOS execution or relocation
  onto a different physical laptop.

Environment setup initially encountered an unwritable sandbox temporary
directory; using `.validation/temp` resolved it. The default package source
could not supply NumPy, and an unpinned plotting download stalled. The public
index and compatible versions above completed installation. These resolved setup
issues are separate from the two test failures.

The 14 final warnings are matplotlib/pyparsing deprecations during the plot
module import. They were reported, not suppressed. No application error was
reported, but future dependency upgrades should revisit them.

## Awaiting the next go-ahead

| Deferred group | Cases |
|---|---:|
| Live tracker HTTP/discovery integration | 12 |
| Synthetic experiment harness/process tests | 6 |
| Storage workflow and combined scheduler/recovery/upload/runtime integration | 116 |
| Socket framing, connections, handshakes and peer-network transfers | 66 |
| **Total** | **200** |

One synthetic experiment was accidentally started and interrupted as described
above; all 200 still require an approved run. The exact cases and per-file counts
are in the [inventory](unit-validation-inventory.json). End-to-end acceptance
beyond repository tests is separate work. The existing peer CLI still requires
its team network backend factory for real networking.

## Evidence

- [Final combined log](../../../.validation/logs/all-unit-attempt-1.log)
- [Final JUnit XML](../../../.validation/results/all-unit-attempt-1.xml)
- [Networking failure](../../../.validation/logs/networking-attempt-1.log) and [rerun](../../../.validation/logs/networking-attempt-2.log)
- [Application failure](../../../.validation/logs/application-attempt-1.log), [interrupted attempt](../../../.validation/logs/application-attempt-2.log) and [rerun](../../../.validation/logs/application-attempt-3.log)
- [Environment snapshot](../../../.validation/environment.txt)
- [All IDs, attempt records, deferred cases and source hashes](unit-validation-inventory.json)

Local `.validation/` evidence and `.venv/` are ignored by Git. This report and
the JSON inventory are project documentation. The editable `pip freeze` record
identifies the Git base, not the uncommitted tested source; use the recorded
source hashes and this working tree for reproduction.

**Stopped at the completed unit gate. Integration, complete-system and end-to-end
execution require the user's explicit go-ahead.**
