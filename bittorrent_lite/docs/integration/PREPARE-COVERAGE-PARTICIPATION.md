# Subprocess coverage participation contract

This preparation helper does not establish campaign readiness or behavioral
coverage completeness. Its execution and all negative controls must be recorded
by the coordinator before acceptance. No test outcome is claimed here.

`coverage_support.install_hook(environment, workspace)` adds a new opt-in `.pth`
hook only to an explicitly named workspace virtual environment; an existing hook
is never overwritten. `write_config(path, source)` creates a new branch coverage
configuration with tests omitted and no production-file or pragma exclusions.
Freeze the hook, configuration, dependency version and source before running.

Set `BTL_COVERAGE_ROOT` to a fresh directory reserved solely for this attempt's
coverage files, and `COVERAGE_PROCESS_START` to the frozen configuration. Each
executing interpreter writes a schema-v2 start record and a distinct database.
Normal termination writes a finish record after saving coverage. Collector
errors remain explicit; startup errors exit 86 because Python otherwise only
prints a `.pth` exception and continues.

The verifier API is:

```python
inspect_participation(
    coverage_root,
    expected_processes=registered_interpreters,
    config=frozen_config_path,
    config_sha256=frozen_config_digest,
    expected_sources=absolute_source_path_to_frozen_sha256,
    coverage_version=pinned_coverage_version,
    expected_terminations=(),
)
```

Build `expected_processes` from the independent guardian/process registry,
including every executing Python child that the campaign requires, not from the
coverage records being verified. Identity is the OS PID, creation time and OS
executable. On Windows, a venv's native redirector process and its real Python
descendant have different PIDs and executables. Retain both in the process ledger,
explicitly classify the redirector as a native wrapper, and require coverage for
the actual interpreter. A guardian that inherits instrumentation is also a
participant; its `guardian_ready` record provides its actual process identity.
Never exclude an unexplained missing interpreter by filename or a heuristic.

Source paths must come from the frozen complete production Python inventory.
The verifier rehashes those files and the configuration, rejects unknown or
duplicate interpreter identities, duplicate/reused databases, changed versions,
unfrozen measured sources, path redirections and unmatched records. Every normal
start must have its matching finish and genuine branch database. It reads the
database and returns actual line and arc sets. It does not infer executed
functions from imports, create a function-coverage percentage, or waive the full
module/requirement/branch ledger. The caller must separately reconcile the full
expected source inventory and its unexecuted lines/branches with combined
coverage and behavioral tests from this attempt only.

## Predeclared forced termination

A deliberate abrupt termination may leave coverage unflushed. The verifier must
not treat that data as saved coverage or silently discard it. The exception needs
an expected interpreter entry with `case_id` and `coverage_role`, plus this item
in `expected_terminations`:

```json
{
  "identity": {"pid": 123, "creation_time": 123.5, "executable": "ABSOLUTE_OS_EXECUTABLE"},
  "declaration": {"path": "ABSOLUTE_INTERNAL_RECORD_PATH", "sha256": "ACTUAL_SHA256"},
  "observation": {"path": "ABSOLUTE_INTERNAL_RECORD_PATH", "sha256": "ACTUAL_SHA256"}
}
```

Placeholders are not valid records. The declaration must have schema
`btl-coverage-termination-plan-v1`, nonempty `case_id` and `process_role`,
`termination_kind: "forced"`, and `declared_at_monotonic` before the interpreter's
coverage start. It belongs to the frozen pre-run fault declaration. The separately
recorded supervisor observation must have schema
`btl-coverage-termination-observation-v1`, matching case/role/identity,
`termination_kind: "forced"`, `exit_confirmed: true`, an actual integer
`exit_code`, and `observed_at_monotonic` at or after that start. Supply the actual
independently retained file hashes, not hashes recomputed from altered evidence.

The observation must come from the validated process supervisor and its owned
process termination, not an application guess. This verifier checks the supplied
records and bindings; it cannot establish the independence or truth of their
author. The final independent verifier must corroborate these files against the
raw command/process records and predeclared fault conditions, including live
target, required progress and surviving population where applicable.

Such an interpreter still requires its startup record. A collector error or a
normal finish cannot be relabeled as an abrupt loss. The result is
`INTERRUPTED_NOT_COUNTED`, with retained partial database/SQLite-sidecar hashes
and empty credited line/arc sets. It must never be passed to the normal combine
step. Required metrics lost at termination require a separately validated
observer or remain BLOCKED under the controlling plan. Resource samples alone
cannot replace exact final transfer counters.

`tests/acceptance/test_coverage_support.py` contains verifier fixtures and a real
recorded child smoke test. Unit coverage databases in negative controls are
clearly labeled fixtures; they are not application execution evidence. The real
child test independently reconciles the child and guardian identities, checks an
executed branch in `common.paths.project_root`, and rejects a missing flush.
