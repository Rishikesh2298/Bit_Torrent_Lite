# Versioned Phase 05 standalone operation procedure

Status: PLANNED; no execution evidence is asserted by this procedure.

Run only after preparation, unit and integration gates. The frozen recorder and
guardian must use absolute selected-environment Python, explicit repository cwd,
fresh per-command directories, a 10-second deadline, and exit oracle zero for
each command. Retain exact stdin/input bytes, raw stdout/stderr, real process
identity/timestamps/exit, fixture hashes and frozen snapshot hashes. No sockets
or real transfers are expected here; this is the standalone/synthetic lane.

1. Execute `[python, '-m', 'bittorrent_lite.scheduling.request_pipeline', '--input',
   absolute_fixture_path]`, using `fixtures/pipeline-all-operations.json`.
   Parse the complete stdout as one JSON object and independently check every
   action and the final state against `assert_pipeline_output` in
   `test_standalone_cli_contracts.py`. All 14 operations occur. Six issued
   requests end as one completed, one expired and four canceled; owned is `[0]`,
   pending and active connections are empty. Require empty stderr.
2. Execute `[python, '-m', 'bittorrent_lite.scheduling.recovery']`, supplying the
   exact bytes of `fixtures/recovery-all-operations.jsonl` on stdin. Require
   exactly eight JSON responses. Line 4 is a predeclared invalid failure kind:
   `ok:false`, `error:ValueError`, nonempty message. All others require `ok:true`.
   Use `assert_recovery_output` for each semantic value and final state.
3. Execute `[python, '-m', 'bittorrent_lite.scheduling.choking_policy']` with the
   exact bytes of `fixtures/choking-all-operations.jsonl` on stdin. Require
   exactly 21 JSON responses. Line 6 is a predeclared nonboolean seeder input:
   `ok:false`, nested `error.type:ValueError`; line 7 proves time/state did not
   advance. Every other line uses its documented operation-specific success
   schema. Use `assert_choking_output` for all responses, acknowledgment values,
   shutdown/reset transition and old-token rejection.

These expected validation errors are successful negative cases only when their
exact oracles match. Unexpected errors, extra/missing/malformed rows, traceback,
timeout, process leak, or a missing fixture are campaign faults. Stop immediately
and follow the controlling plan's complete-restart rule. Never replace raw
responses with the expected values in this document or the assertion helpers.

The in-process pytest cases validate handlers and fixtures only; they do not
substitute for the three recorded external commands. Upload demo, scheduler
example, packaging, and additional parser/path cases have separate procedures.
