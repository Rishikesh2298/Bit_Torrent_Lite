# Real multiprocess coverage participation procedure

This procedure is authored PREPARE work. Its presence is not an execution result,
an acceptance pass, complete branch/function coverage, or independent review.
The root runner executes it sequentially only when source edits are paused.

Exact selector:

```text
bittorrent_lite/tests/acceptance/test_coverage_lifecycle.py::test_real_worker_guardian_tracker_and_peer_coverage_participation
```

Run through the existing `RecordingSession` diagnostic runner with genuine raw
stdout/stderr, exit status and pytest JUnit. The test creates a second nested
`RecordingSession`, whose worker has an 85-second hard timeout. It stores a fresh
`coverage-lifecycle-<uuid>` directory under the outer command evidence directory
when `ACCEPTANCE_PROCESS_REGISTRY` exists, or under pytest's temporary directory
otherwise. No application process starts during import or collection.

The required opt-in `.pth` hook must already exist in the current disposable
virtual environment and exactly equal `coverage_support.HOOK`. The procedure
does not install or overwrite it. It creates and hashes a new branch coverage
configuration, snapshots the source before launch and verifies the same snapshot
afterward, and retains hook/interpreter hashes and the installed coverage version.
All child interpreters inherit this fresh coverage directory and configuration.
The parent pytest interpreter belongs to its enclosing campaign coverage, not
to the nested five-interpreter population tested here.

The positive case runs an actual worker, recorder guardian, tracker, seeder and
downloader. It uses four full distinct diagnostic pieces and a partial piece,
real loopback HTTP/TCP, actual strict event logs and raw streams. It requires
exact output size, SHA-256 and byte-for-byte equality in both worker and parent,
ordinary peer exits of zero, and no surviving registered process. These fixture
bytes are explicitly diagnostic: source access is not denied, no independent
challenge is claimed, and the result earns no full E2E or measured-run credit.

Expected coverage identities come from OS PID/birth/executable/argv/parent
observations, immutable explicit registration, verified live ancestry and the
guardian readiness record. No coverage record supplies an expected PID. A
separate five-entry expected-interpreter registry includes the guardian without
placing it in its own cleanup registry. The worker, peer and tracker actual
interpreters also belong to the nested cleanup registry. Windows native venv
redirectors remain separate ancestry/ownership records and must not count as
covered interpreters. Unknown ancestry or missing registration fails visibly.

Before starting the tracker, the worker saves a declaration of the tracker-only
abrupt termination using `psutil.Process.kill`. Both peers first stop normally.
The tracker then exits through the owned Swarm kill path: expected Windows code
15 or POSIX `-SIGKILL`, with actual-interpreter and Popen wrapper wait statuses
required to agree. A separate hashed observation records those actual results.
The coverage verifier must classify precisely this tracker as
`INTERRUPTED_NOT_COUNTED`, with no credited lines or arcs and no normal finish.
This avoids treating POSIX tracker SIGTERM's possible graceful shutdown as an
abrupt-termination test. No other missing flush is excused.

The other four interpreters must each provide a real branch database, matching
startup/finish/config/version/source hashes and exact process identity. Selected
executed function-body lines and arcs must include worker metadata generation,
guardian `_watch`, and both peers' runtime `step`; imports alone cannot satisfy
these anchors. These checks establish participation and selected behavior only.
They do not measure every branch or replace the full module-coverage ledger.

Four explicit verifier negative controls run only after the real corpus passes:
missing finish in a retained copy, a real covered interpreter omitted from the
expected registry, duplicate expected identity, and a complete duplicate
startup/finish/database pair in another retained copy. Each must raise the
specific verifier error. The original measured corpus is rehashed and must remain
unchanged. All copied records are labeled verifier controls, never measured
coverage. The procedure does not manufacture positive coverage data.

Evidence includes `inputs-before.json`, the nested command/guardian records,
`supervisor-observations.json`, `expected-interpreters/`,
`expected-population.json`, `swarm/` raw logs and ownership records, tracker
declaration/observation, `coverage/` untouched originals,
`participation-verified.json`, and retained `negative-controls/`. A failed worker
also saves its traceback. Root must retain any failed diagnostic directory,
diagnose the first failure, and rerun the preparation diagnostic after repairs;
none of those diagnostics is an acceptance attempt.
