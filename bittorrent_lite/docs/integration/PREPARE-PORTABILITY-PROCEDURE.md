# Offline packaging and installed standalone diagnostic procedure

This procedure implements part of FINAL-ACCEPTANCE-TEST-PLAN.md Phases 01 and 05.
It is preparation tooling, not a READY decision or a replacement for SY12, the
module/requirement ledgers, another-host/OS cases, or complete standalone API tests.
No result is claimed by the presence of this document or its helper.

## Preconditions and frozen inputs

Use an existing absolute interpreter whose origin, version and executable bytes
were recorded. The supervisor environment must contain the pinned `psutil`
dependency required by the command recorder. The process guardian and its
descendant-registration limitations must be validated separately. The helper
reports its remaining process-observation limit; a packaging result cannot
override that campaign gate.

Prepare a local wheelhouse and a UTF-8 JSON lock without a BOM, duplicate keys or
nonfinite numbers. The exact schema is:

```json
{
  "schema": 1,
  "python_version": "3.12.14",
  "wheels": [
    {
      "file": "build-1.6.1-py3-none-any.whl",
      "name": "build",
      "version": "1.6.1",
      "sha256": "REPLACE_WITH_THE_ACTUAL_64_LOWERCASE_HEX_DIGEST"
    }
  ]
}
```

The example is deliberately incomplete and will be rejected. Use the actual
interpreter patch version and actual hashes. Include one wheel for every locked
distribution and its transitive requirements. Required names are `pip`, `build`,
`setuptools`, `wheel`, `packaging`, and `pyproject-hooks`. On this Windows host,
the selected build dependencies also require `colorama`. Do not infer closure
from this prose: the helper runs actual `pip check`, compares the complete
installed distribution/version set to the lock, and stops on mismatch. It reads
each wheel's METADATA and verifies distribution identity and file SHA-256.
Missing wheels/tools remain BLOCKED. Malformed/tampered locks fail.

Pause source edits before invoking either stage. The helper freezes all files
returned by `inventory.source_files`, including untracked contributor content,
using that inventory's explicit exclusions. It copies the source into a fresh
directory containing spaces and Unicode, verifies every copied file, and checks
the original source snapshot again at the end. It never builds in the original
checkout and never deletes previous outputs. An output directory inside the
checkout must be under `.validation`; otherwise place it outside the inventory.

## Phase 01 packaging/import stage

From the repository root, with variables set to verified paths on this host:

```powershell
& $Python -m bittorrent_lite.acceptance_tools.portability packaging `
  --repo $RepositoryRoot --out $FreshPackagingRoot --python $Python `
  --wheelhouse $Wheelhouse --wheel-lock $WheelLock
```

API: `run_packaging(repo, out, python, wheelhouse, wheel_lock) -> report`.

Every child command uses `RecordingSession`: real raw streams, start/end times,
exit status, interpreter hash, process ownership and guardian results. The helper
stops at the first unexpected failure. Do not reuse an output directory. Do not
treat focused preparation diagnostics as acceptance credit.

The stage creates three fresh virtual environments in paths containing spaces
and Unicode. It installs the hash-locked wheel set offline with `--no-index`,
`--no-deps`, `--only-binary=:all:` and `--require-hashes`, then checks dependencies
and exact installed versions. The build uses `python -I -m build --no-isolation
--wheel --sdist`. It requires exactly one wheel and one source distribution.
The wheel and sdist bytes must contain every inventoried non-test package Python
file, including preserved legacy modules and acceptance helpers, plus all three
declared JSON resources. Archive traversal, links and duplicate files fail.

Each artifact is installed into its separate fresh environment using
`--no-index --no-deps --no-build-isolation`. Imports run with `-I` from an unrelated
directory; `PYTHONPATH`, `PYTHONHOME`, ambient pytest/coverage variables and pip
configuration are removed. Every product module's `__file__` must be within the
selected environment and its bytes must match the frozen source. Declared
`__all__` names must resolve. Packaged JSON resources are opened with
`importlib.resources`, independently hashed, and their installed locations are
recorded. The compatibility `session.Handshake is messages.Handshake` identity,
console entrypoint mappings and exclusion of installed tests are checked.

The stage actually invokes `--help` for the package CLI, application CLI,
metadata generator, tracker, request pipeline and upload service, and both
installed console scripts. Recovery and choking use JSONL stdin and are not
given invented help flags.

Experiment scripts require a source checkout. They remain packaged-byte checks
with explicit NOT RUN source-only invocation entries. Acceptance-tool imports
also have separate dependency/validation procedures and are excluded from the
product import probe. These exclusions are written to `installed-spec.json`;
they must remain mapped in the full campaign ledgers. Product imports prove
availability and origin, not all behavioral contracts.

Pip network discovery is disabled. This is not an OS network sandbox: the trusted
frozen build backend itself executes Python. Generated virtual-environment
configuration necessarily contains host paths; it lives only under this
attempt's evidence. No persisted project configuration is rewritten with an
absolute user path.

## Phase 05 standalone stage

Run only after the campaign's unit and integration gates, using the same frozen
revision as its successful packaging stage:

```powershell
& $Python -m bittorrent_lite.acceptance_tools.portability standalone `
  --packaging-root $FreshPackagingRoot --out $FreshStandaloneRoot
```

API: `run_standalone(packaging_root, out) -> report`.

Both installed artifacts have their origins/resources checked again, then run:

- The real packaged request-pipeline example: request identity, send confirmation,
  expiry reason/time and zero final pending/outstanding requests are asserted.
- Recovery JSONL: create, snapshot, deliberately invalid operation, snapshot.
  The single expected error must be structured, subsequent processing must
  succeed and state must remain equal. Exit zero alone is insufficient.
- Choking-policy JSONL: configure, connect, snapshot, invalid operation, snapshot,
  shutdown. Its different documented response schemas are checked separately.
- Upload-service demo in a fresh Unicode/space directory: both actual piece files
  and manifest hashes are checked, along with 65,536 acknowledged bytes, two sent
  pieces, no active jobs and a closed service. This is explicitly simulated local
  delivery and receives no real-network evidence credit.
- Scheduler demo: actual request/HAVE tuples, sent flag and deadline corresponding
  to the example's send-confirmation timestamp,
  completed ownership and a distinct next request are checked.

These smoke procedures supplement the complete standalone/legacy unit and
negative-contract suites. They do not replace every API operation, fault case,
legacy comparison, real peer, or source-checkout experiment invocation.

## Results and verification

Each stage writes fresh `report.json`, `source-before.json`, `source-after.json`
and command subdirectories. Packaging also writes the exact wheel lock,
installed specification, archives and wheel/sdist origin reports. Command
records retain the recorder's `semantic_oracle_status: NOT RUN`; this helper's
separate per-command `semantic_status` records which stated oracle it actually
evaluated. The independent final verifier must inspect both raw records and
semantic evidence; this helper cannot provide independent sign-off on itself.

CLI exits are 0 for this narrow diagnostic PASS, 1 for FAIL and 2 for BLOCKED.
`acceptance_ready` is always false. Missing host resources, additional OS/laptop
results, source isolation, complete mapping and human review remain independent
gates. During an acceptance attempt any unexpected failure requires the full
stop/repair/new-freeze/new-attempt restart rule in the controlling plan, including
rerunning these stages in the appropriate ordered phases.

Pure preparation controls are in `tests/acceptance/test_portability.py`. They
exercise lock tampering, missing resources, injected environment settings,
preservation, archive/member handling, origin mismatch and semantic-oracle
negative controls. Their fixtures are not claimed execution evidence. Only the
campaign coordinator runs those tests and the actual diagnostic stages.
