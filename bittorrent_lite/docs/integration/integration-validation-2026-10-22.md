# Integration and system validation — 22 October 2026

**All 200 authorized integration/system tests passed.** The subsequent unit
regression run passed all **537 unit tests**. Together these account for every
one of the **737 collected tests**, with **0 failures, 0 errors, 0 skips and
0 expected failures in the final runs**. Separate end-to-end testing has not
started and awaits the user's explicit go-ahead.

The combined integration run took **28.47 seconds**; the unit regression took
**13.56 seconds**. These are two separate final runs, not a single 737-test run.
Each reported the same 14 matplotlib/pyparsing deprecation warnings. No reader
thread warning remained in the final networking or integration run.

## Scope and results

| Group | Passed | What was exercised |
|---|---:|---|
| Storage workflows — Rishikesh | 9 | Piece boundaries, metadata identity, verified storage, reconstruction, corrupt and missing pieces |
| Live tracker/client — Debargha | 12 | Local HTTP discovery, request validation, error responses, timeouts, tracker absence and restart |
| Networking — Anik | 66 | Socket framing, handshakes, bitfields/HAVE, interest, choke/unchoke, request/piece, cancel/reject, lifecycle and disconnects |
| Scheduling, recovery and uploads — Prabhat/integration | 83 | Request reservations, backpressure, retries, cancellation, disk verification, upload permissions/accounting, threaded and synchronous transfers |
| Application/runtime integration | 24 | Storage/scheduler transfers through a simulated backend, strategy/window/free-rider combinations, assembly, discovery filtering, shutdown and injected CLI backend |
| Synthetic experiment harness — Debargha | 6 | Baseline, targeted peer termination, occupied port, child crash, readiness timeout, collection and plots |
| **Integration/system total** | **200** | **Every previously deferred test** |
| Unit regression after fixes | 537 | All previously approved unit groups, including import and portability checks |
| **Unique tests covered** | **737** | **Complete collected inventory** |

Collection found 45 nonempty test files. The existing empty
`tests/networking/test_handshake_connection.py` remains preserved; it contains
no test to execute. No test was disabled, deleted, skipped or marked xfail.
Some tests intentionally produce failed experiment manifests to verify error
handling; those expected outcomes are successful tests.

## Failures, fixes and full-group reruns

1. **Tracker attempt 1: first test failed before the HTTP exchange.** Windows
   returned `WinError 10013` because the execution sandbox blocked localhost
   sockets. No application code was changed. The complete 12-test group was
   rerun outside that network restriction and passed. Later socket/process
   groups used the same permitted execution context.
2. **Networking attempt 1: 5 passed, then the first network bitfield test failed.**
   Its handshake used string version `"1.0"`, but the merged protocol parser
   requires the shared integer `PROTOCOL_VERSION = 1`. The inconsistency already
   exists in the base revision; moving files did not introduce it. Five older
   networking test modules now import the shared constant. The mismatch case
   still sends an unsupported version, using `PROTOCOL_VERSION + 1`. Protocol
   rejection was not relaxed and existing test assertions were retained.
3. **The same failure exposed reader cleanup defects.** A parser `ValueError`
   escaped the background reader. Its finalizer only marked the connection
   disconnected, which could leave the actual socket open. In
   `networking/connection.py`, invalid wire messages now end the read loop
   normally, and its finalizer calls the existing `close()` method to release
   the transport and wake the writer. The existing protocol-mismatch test now
   additionally verifies the socket is closed and both workers have exited.
4. **Networking attempt 2 restarted all 66 tests and passed**, without thread
   warnings. Storage, scheduling, runtime and synthetic groups each passed on
   their first attempt. Finally, all 200 integration/system tests ran together,
   followed by the full 537-test unit regression. Both passed.

Every execution used `pytest -x`, so a failure stopped that run immediately.
The runner rejects empty selectors and verifies that collected node IDs match
the exact approved group before any test body runs. Earlier failed logs and XML
results remain available; no evidence was overwritten.

## Paths, preservation and environment

No additional import or file-path failure appeared in this stage. Existing
portability tests passed again, including module commands outside the checkout
and metadata paths containing spaces. The live harness successfully located
the relocated tracker/scripts/configuration and generated artifacts under its
temporary run directories. No machine-specific path was added to source code.
This validates the tested Windows environment, not every operating system or
laptop configuration.

Compared with the recorded unit-stage snapshot, only **six Python files**
changed: the connection implementation and five networking test files. The
storage, discovery, scheduling and application implementations were unchanged.
An audit against the migration map confirmed all **148 original mapped files**
are still present and all original function/class definitions are retained
(including the previously documented unit-test rename). All **five original
plans** match their preserved SHA-256 hashes. Git history and authorship were
not rewritten; no commit or push was made.

Test environment: Windows, Python 3.12.14, editable local installation, pytest
9.1.1, pytest-timeout 2.4.0, matplotlib 3.10.3, NumPy 2.2.6 and pandas 2.2.3.
The normal per-test timeout was 30 seconds; the experiment module uses its
existing 90-second timeout marker. The dependency warnings were recorded, not
suppressed. They originate from deprecated pyparsing calls in matplotlib.

Branch: `refactor/member-owned-layout`; base: `6ea28b1ea8711e87b637d118699161f297143be6`.
These results describe the **uncommitted restructured working tree**, not the
base commit alone. Source/config snapshot SHA-256:
`2cda9d181d3724353873b1d73d06f86e4e70609d91e2431cc92683f87c386491`.

## Experiment evidence and remaining limits

The final integration run produced seven experiment manifests across the six
tests. Both baseline runs verified the outputs of both simulated downloaders.
The failure scenario terminated only `peer-03` after its configured progress
threshold; the other two outputs verified. Every launched child had an exit
code recorded, including expected error scenarios. A subsequent Windows
process check found no matching project Python test processes left running.

These tests establish component and harness behavior. **They do not establish
a complete CLI-driven BitTorrent swarm.** Runtime integration injects a
simulated backend. Stand-in peers use the real tracker/discovery but simulate
progress and copy the source fixture; their hashes and timings are not evidence
of real peer-to-peer distribution. The existing application CLI still reports
that its network backend is not connected when no factory is supplied. That
pre-existing integration gap was preserved and must be addressed before a
meaningful complete-application end-to-end run. No cross-laptop/LAN transfer,
real experiment matrix or separate end-to-end campaign was run. No line/branch
coverage percentage is claimed.

## Evidence and reproduction

The [machine-readable inventory](integration-validation-inventory.json) lists
all 200 node IDs by group, counts per file, every attempt's XML summary, source
hashes, preservation checks and synthetic manifest paths. The earlier
[unit-stage report](unit-validation-2026-10-22.md) remains a historical record.

Local evidence under the repository's ignored `.validation/` directory:

- [Final 200-test log](../../../.validation/logs/all-integration-attempt-1.log) and [JUnit XML](../../../.validation/results/all-integration-attempt-1.xml).
- [Unit regression log](../../../.validation/logs/all-unit-attempt-2.log) and [JUnit XML](../../../.validation/results/all-unit-attempt-2.xml).
- [Tracker failure log](../../../.validation/logs/tracker-http-attempt-1.log) and [complete rerun](../../../.validation/logs/tracker-http-attempt-2.log).
- [Networking failure log](../../../.validation/logs/network-integration-attempt-1.log) and [complete rerun](../../../.validation/logs/network-integration-attempt-2.log).
- [Guarded integration runner](../../../.validation/integration_stage.py), [collection guard](../../../.validation/integration_gate.py), [evidence auditor](../../../.validation/integration_report_data.py), and [environment versions](../../../.validation/environment.txt).

The local guarded runs can be reproduced from `BitTorrent/` using a fresh
attempt label, so prior evidence is retained:

```powershell
.\.venv\Scripts\python.exe .validation/integration_stage.py all-integration --attempt review
.\.venv\Scripts\python.exe .validation/unit_stage.py all-unit --attempt review
```

Localhost sockets and temporary child processes must be permitted. The ignored
validation tooling/logs are local evidence, not installed project files. On a
fresh checkout, `python -m pytest -x --timeout=30 bittorrent_lite/tests` runs the
repository's collected suite after installing test and experiment dependencies.
It does not add a real backend or launch a separate end-to-end campaign.
