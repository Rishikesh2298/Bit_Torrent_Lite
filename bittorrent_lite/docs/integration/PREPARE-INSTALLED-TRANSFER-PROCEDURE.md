# Installed core transfer diagnostic

The `installed-transfer` stage proves actual local TCP execution from both the
wheel and sdist installations produced by a successful packaging diagnostic.
It is a separate preparation stage; imports, help text and standalone simulated
demos do not provide its execution credit. Every result remains diagnostic,
`acceptance_ready: false`, with no source-isolation claim.

## Prerequisites and command

Finish source repairs and helper tests first. Freeze all source edits, rerun
`portability packaging` into a fresh evidence directory, and require its PASS.
The installed-transfer stage rejects any current source snapshot that differs
from that packaging run. Historical packaging environments cannot be reused
after a source change. Existing `packaging` and `standalone` commands retain
their previous behavior.

From a pinned editable preparation environment with recorder/test dependencies,
run the following through an enclosing `RecordingSession` with a fresh output
directory under retained preparation evidence:

```text
<preparation-python> -m bittorrent_lite.acceptance_tools.portability installed-transfer
  --packaging-root <fresh-successful-packaging-directory>
  --out <fresh-installed-transfer-directory>
```

An absent inherited `ACCEPTANCE_PROCESS_REGISTRY` blocks this stage before child
launch. Each installation's worker runs under another recorded command/guardian
with a 300-second timeout; an outer timeout of at least 750 seconds leaves room
for both finite worker budgets, import probes and recorded cleanup. Actual small
transfers may finish much sooner. Unexpected command, protocol, bytes, identity,
exit or evidence failure stops the sequence; later cases are NOT RUN. Preserve
all failed directories and restart preparation from a fresh source freeze and
new packaging/transfer directories after a repair.

## What is exercised

Each installation runs real tracker, seeder and downloader subprocesses at three
fixed file sizes: 1 byte, 65536 bytes and 524411 bytes (a short final piece). These
six transfers use fresh directories whose names contain spaces and Unicode and
which contain no importable project package. The source-only supervisor imports
the E2E support from the frozen checkout, but the product command is exactly an
explicitly verified installed interpreter with `-I -X utf8 -m <product-module>`.
`-I` excludes cwd/user-site/PYTHONPATH; `-X utf8` remains necessary on Windows
because isolated mode ignores `PYTHONIOENCODING` and `PYTHONUTF8` environment
settings. No arbitrary replacement shell command is accepted.

Before and after each environment's transfers, a recorded installed interpreter
probe verifies its prefix, module origins, exported compatibility names,
entrypoints and package resources against the frozen source hashes. Installed
tests must remain absent. The supervisor also rehashes actual installed files
and the selected executable; an executable hash change blocks a child launch.

All child stdout/stderr and dedicated strict JSONL streams are retained. Process
records distinguish native Windows venv launchers from the independently observed
actual interpreter, including creation time and verified ancestry. Strict log
sequence/PID checks use that observed identity. Peer stop requires exact exit 0;
Windows tracker teardown uses the explicitly declared psutil API and exact exit
15. Cleanup targets only owned processes and rejects unknown/mismatched exit
statuses. POSIX tracker handling retains its declared graceful/SIGTERM rule.

The oracle requires one genuine completed downloader, exactly one ownership
commit per piece, a matching received PIECE and source send with the same request
identity, byte count and reversed TCP endpoints. Every retained committed piece
is compared with the independent source slice. The assembled output is checked
for exact size, independently calculated SHA-256 and byte-for-byte equality.
Initial seeder completion events retain their existing product meaning and are
not misclassified as a downloader transfer. These checks do not claim the source
file was inaccessible to the downloader's OS account.

## Evidence and checks

The stage writes `report.json`, source snapshots, recorded probes/worker commands
under `commands/`, and separate `wheel transfer worker Ω` / `sdist transfer
worker Ω` directories. Worker reports link the six per-swarm
`installed-transfer-proof.json` files. Each swarm retains source/metadata,
downloads/pieces, raw logs, process launches/actions/results and ownership
records. Worker evidence is inventoried by exact path, size and SHA-256; the
parent rejects changed, missing, extra or redirected artifacts.

Run `tests/acceptance/test_installed_transfer.py` along with the existing
portability and E2E support/interpreter helper suites as recorded PREPARE unit
tests. Their process doubles and artificial rows are helper controls only and
are never substituted for live transfer evidence. The installed-transfer worker
is intentionally source-only and cannot run as a module from the installed
product wheel, whose distribution excludes tests.

This stage does not complete the full acceptance campaign, two-owner LAN/OS
portability, all max-size/fault cases, stress grid, coverage ledger, source denial
or independent final verification. Those remain separately mapped requirements.
