# Running from another folder or another computer

Use a copy of the complete current `BitTorrent` source folder, keeping
`bittorrent_lite` inside it. This working tree contains uncommitted changes;
cloning its current Git commit alone does not include those changes. Share the
reviewed source files or a verified build from this working tree. Recreate the
virtual environment on each computer.
Virtual environments contain machine-specific interpreter paths; copying this
computer's `.venv` or `.validation` directory is not a portable installation.

The declared Python minimum is 3.10. Current preparation diagnostics use
Windows and Python 3.12.14. Testing the minimum version, another OS, and teammate
machines remains pending; unknown professor hardware is not a verified platform.
Core operation uses Python's standard library. Test and experiment dependencies
are optional extras. The project file limit is 64 MiB; use the default 64 KiB
pieces for an ordinary demonstration.

## Fresh installation

Open a terminal in the folder containing `pyproject.toml` and `bittorrent_lite`.
On Windows PowerShell:

```powershell
if (Test-Path -LiteralPath .venv) { throw 'Choose a fresh environment directory; preserve the existing one' }
py -3 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -e .
& .\.venv\Scripts\python.exe -m pip check
$Python = (Resolve-Path .\.venv\Scripts\python.exe).Path
```

If `py` is unavailable, use the absolute path to an installed Python 3.10+
interpreter for the first command. An unconfigured Microsoft Store alias is not
an installed interpreter. This method does not require changing PowerShell's
execution policy or activating the environment.

On Linux/macOS, the equivalent commands are:

```sh
test ! -e .venv || exit 1
python3 -m venv .venv
./.venv/bin/python -m pip install -e .
./.venv/bin/python -m pip check
PYTHON="$(pwd)/.venv/bin/python"
```

Check each command's exit code before continuing. Keep a source checkout in
place for an editable install. After moving it, recreate the environment and
reinstall. A wheel installation is independent of the checkout; experiment
scripts still require a source checkout.

The commands above install the core application. For development, install only
the extras you need, from that same source folder. In PowerShell:

```powershell
& $Python -m pip install -e ".[test]"         # Run tests
& $Python -m pip install -e ".[experiments]"  # Collect tables and plot experiments
& $Python -m pip check
```

On Linux/macOS, use `"$PYTHON"` in place of `& $Python`. Either extra can be
installed separately; `.[test,experiments]` installs both. Source installation
may download build tools, and extras may download platform-specific packages.
The pinned acceptance environment and its wheel lock are separate from this
ordinary setup; a lock prepared for Python 3.12 on Windows does not establish
dependency availability on Python 3.10 or another OS.

## Installing a shared core wheel

Obtain the selected `.whl` file and its exact SHA-256 from the sender's verified
build record. Confirm the digest through the separately retained record or the
sender; do not calculate an expected digest from the received file itself.
No artifact or digest is preselected by this runbook. A matching digest checks
the received bytes; it does not certify this device or complete acceptance.

In PowerShell, start in a writable folder with no existing `.wheel-venv`:

```powershell
$Wheel = (Resolve-Path -LiteralPath (Read-Host 'Path to the received wheel')).Path
$ExpectedSha256 = (Read-Host 'SHA-256 from the verified build record').Trim().ToLowerInvariant()
if ($ExpectedSha256 -notmatch '^[0-9a-f]{64}$') { throw 'Expected a recorded SHA-256 digest' }
if ((Get-FileHash -LiteralPath $Wheel -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedSha256) { throw 'Wheel SHA-256 mismatch' }
if (Test-Path -LiteralPath .wheel-venv) { throw 'Choose a fresh environment directory' }
py -3 -m venv .wheel-venv
if ($LASTEXITCODE -ne 0) { throw 'Environment creation failed' }
$Python = (Resolve-Path .\.wheel-venv\Scripts\python.exe).Path
& $Python -m pip install --no-index --no-deps $Wheel
if ($LASTEXITCODE -ne 0) { throw 'Wheel installation failed' }
& $Python -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Installed dependency check failed' }
& $Python -I -X utf8 -m bittorrent_lite --help
if ($LASTEXITCODE -ne 0) { throw 'Installed CLI check failed' }
```

For Linux/macOS, use a fresh environment and the same recorded digest. Set
`WHEEL` to the received wheel's absolute path and `EXPECTED` to that digest:

```sh
test ! -e .wheel-venv || exit 1
python3 -m venv .wheel-venv || exit 1
PYTHON="$(pwd)/.wheel-venv/bin/python"
"$PYTHON" -I -c 'import hashlib, pathlib, re, sys; expected=sys.argv[2].lower(); valid=re.fullmatch("[0-9a-f]{64}", expected) and hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest()==expected; raise SystemExit(0 if valid else "Wheel SHA-256 mismatch")' "$WHEEL" "$EXPECTED" || exit 1
"$PYTHON" -m pip install --no-index --no-deps "$WHEEL" || exit 1
"$PYTHON" -m pip check || exit 1
"$PYTHON" -I -X utf8 -m bittorrent_lite --help || exit 1
```

Core has no external runtime dependencies, so this wheel installation can be
offline once Python and the wheel are available. Tests are excluded from the
wheel. Keep the complete reviewed source folder for original plans, other
documentation, tests and source-only experiment scripts; the wheel does not
replace the project submission. Recreate each recipient's environment locally.

## File paths and a local transfer

Quote file paths. Relative input/output paths refer to the terminal's current
directory. Installed `python -m bittorrent_lite` and console entrypoints do not
require the current directory to be the repository. Use absolute user-selected
data paths when switching terminals or directories. No source file path needs
to match between different computers.

In PowerShell, set the following to your own paths. Generate metadata once and
give every peer those exact metadata bytes; do not regenerate it independently
with a different filename or formatting.

```powershell
$Source = (Resolve-Path '.\your input.bin').Path
$Metadata = Join-Path (Get-Location) 'transfer.torrent.json'
$Downloads = Join-Path (Get-Location) 'downloads'
& $Python -m bittorrent_lite.storage.generate_metadata --file $Source --output $Metadata
& $Python -m bittorrent_lite --peer-id seed-01 --port 9001 --metadata $Metadata --seeder --file $Source --output-dir $Downloads --check-config
```

After successful validation, use three terminals with the same installed
interpreter and corresponding path variables:

```powershell
& $Python -m bittorrent_lite.discovery.tracker_server --host 127.0.0.1 --port 8000
& $Python -m bittorrent_lite --peer-id seed-01 --port 9001 --tracker http://127.0.0.1:8000 --metadata $Metadata --seeder --file $Source --output-dir $Downloads
& $Python -m bittorrent_lite --peer-id peer-01 --port 9002 --tracker http://127.0.0.1:8000 --metadata $Metadata --output-dir $Downloads
```

Outputs are `<Downloads>/<peer-id>/<metadata.filename>`. A completed peer stays
running to seed. Stop peers with Ctrl+C, or pass a distinct initially absent
`--stop-file` and create it to request graceful shutdown. POSIX SIGTERM also
requests graceful peer shutdown. Windows process termination APIs forcibly stop
the process; supervisors should use the stop file for ordinary cleanup. Stop a
manually launched tracker with Ctrl+C after the peers. Peer IDs must be unique
and contain 1–32 letters, digits, underscores or hyphens. Use different listening
ports for processes on the same device. Preserve logs and outputs when reporting
a failure.

## Teammate devices and external acceptance resources

For a LAN transfer, run the tracker with `--host 0.0.0.0`, and replace
`127.0.0.1` in every peer's `--tracker` value with the tracker's reachable IPv4
address. Loopback refers to the current device. Use a network that permits
device-to-device TCP traffic and permit the chosen tracker/peer ports in the
host firewall. Do not disable the firewall generally. A VPN, guest Wi-Fi or
campus client-isolation policy can prevent connectivity despite correct paths.

The final acceptance plan requires:

- At least two separately owned laptops for actual cross-device transfers and
  source-isolated redistribution. Receivers receive metadata but no source file.
- Windows and the additional supported Linux/macOS environment, plus the
  declared minimum Python version. Record what was actually tested.
- A reviewer/human who supplies a fresh token after the final source freeze,
  independently retains seals, receives read-only evidence and reruns the
  required suite/transfer/redistribution/fault checks.
- The actual assignment rubric and genuine team review/demo/viva/contribution
  records. These cannot be produced by automated tests or inferred from dates.
- Time and resources for the entire campaign, including at least eight hours
  for the prescribed 16-configuration stress grid, all 27 measurements, and
  full restarts after an unexpected acceptance failure.

These commands are an operational runbook, not completed acceptance evidence.
Teammates can run them on their devices; final acceptance additionally needs
the frozen recorder, challenge, case ledgers and phase sequence in the
[controlling plan](FINAL-ACCEPTANCE-TEST-PLAN.md). No professor specifications or
human approvals have been invented.
