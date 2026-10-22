# Member-owned layout migration

Date: 22 October 2026. Base: merged main commit
`6ea28b1ea8711e87b637d118699161f297143be6`.
Branch: `refactor/member-owned-layout`.

The previous checkout was on `Prabhat-Peer`. The migration starts from the merged
main revision to retain all four members' merged contributions. Existing history
and branches were not rewritten. No commit or push was made by this migration.

All project folders now live under `BitTorrent/bittorrent_lite/`. Existing Python
definitions and test cases are retained. The [migration map](path-migration.json)
records original paths, new paths and file hashes. Original and final content
may differ because imports, commands, documentation links and path discovery
were updated. Existing multi-file policies remain packages rather than being
flattened into single large files.

Static inspection covers Python syntax, local import targets, original-file
coverage, original function/class retention, local Markdown links and JSON
configuration syntax. It does not execute the application, collect tests, start
servers or prove runtime behavior.

Static symbol inspection also found a pre-existing merged-main export gap:
`piece_manager/choking.py` did not expose the `ChokingManager` that its tests
imported, although `_choking_manager.py` contained the implementation. The new
`scheduling/legacy/choking.py` re-exports that existing class alongside
`ProjectUploadPolicy`. Both implementations are preserved.

**At migration time, tests were pending explicit user authorization.** The later
[unit-stage validation](unit-validation-2026-10-22.md) passed 537 tests and records
its fixes, limitations and interrupted selection error. The subsequently
authorized [integration/system stage](integration-validation-2026-10-22.md)
passed all 200 remaining tests and reran all 537 unit tests successfully.
The subsequently authorized [real end-to-end stage](end-to-end-validation-2026-10-22.md)
connected the backend and passed the full 784-test suite. Historical passing-test
counts elsewhere in the documentation do not validate this reorganized revision.
After authorization, run from the repository root:

```sh
python -m pytest
```

Review failures against the base revision to distinguish existing integration
gaps from migration regressions. The CLI backend was a pre-migration limitation;
it was connected in the later authorized end-to-end stage, separately from the
layout migration itself.
