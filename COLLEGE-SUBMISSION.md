# College submission and quick demo

Keep the complete `BitTorrent` source folder with `bittorrent_lite` inside it.
The five original plans remain in `bittorrent_lite/docs/plans/original/`, and
contributors' implementations and documents are retained. Share the current
source files: cloning an older Git commit does not include uncommitted changes.
Recreate a virtual environment on each computer instead of copying `.venv`.

The project declares **Python 3.10 or newer** and has no external core runtime
dependencies. Preparation diagnostics used Windows with Python 3.12.14;
macOS/Linux, the minimum Python version, and teammate devices are not claimed
as tested here. The commands below follow the repository's supported CLI.

## Install from the source folder

Open a terminal in `BitTorrent`, where `pyproject.toml` is located. Use a fresh
environment directory; preserve any existing environment. Stop if a command
fails before continuing.

Windows PowerShell:

```powershell
if (Test-Path -LiteralPath .venv-submission) { throw 'Choose a fresh environment name and use it below' }
py -3 -X utf8 -m venv .venv-submission
& .\.venv-submission\Scripts\python.exe -X utf8 -m pip install -e .
& .\.venv-submission\Scripts\python.exe -X utf8 -m pip check
```

If `py` is unavailable, use an installed Python 3.10+ interpreter for the first
command. Activation and execution-policy changes are unnecessary.

macOS/Linux:

```sh
test ! -e .venv-submission || exit 1
python3 -m venv .venv-submission || exit 1
./.venv-submission/bin/python -m pip install -e . || exit 1
./.venv-submission/bin/python -m pip check || exit 1
```

The initial install may download build tools. Keep the source folder in place
for this editable installation; recreate the environment after moving it.

## One tracker, one seeder, one downloader

Put your chosen nonempty test file in the source folder as `demo-input.bin`
(maximum 64 MiB). Use a fresh `demo-downloads` directory for a fresh demo.
Generate metadata once, using the normal 64 KiB piece size:

```powershell
# Windows PowerShell
& .\.venv-submission\Scripts\python.exe -X utf8 -m bittorrent_lite.storage.generate_metadata --file "demo-input.bin" --output "demo.torrent.json" --piece-size 65536
```

```sh
# macOS/Linux
./.venv-submission/bin/python -X utf8 -m bittorrent_lite.storage.generate_metadata --file "demo-input.bin" --output "demo.torrent.json" --piece-size 65536
```

Open **three terminals**, each in the same `BitTorrent` folder. Start the tracker
first, then the seeder, then the downloader. Run one numbered command per terminal.

Windows PowerShell:

```powershell
# 1. Tracker
& .\.venv-submission\Scripts\python.exe -X utf8 -m bittorrent_lite.discovery.tracker_server --host 127.0.0.1 --port 8000
# 2. Seeder
& .\.venv-submission\Scripts\python.exe -X utf8 -m bittorrent_lite --peer-id seed-01 --host 127.0.0.1 --port 9001 --tracker http://127.0.0.1:8000 --metadata "demo.torrent.json" --seeder --file "demo-input.bin" --output-dir "demo-downloads"
# 3. Downloader
& .\.venv-submission\Scripts\python.exe -X utf8 -m bittorrent_lite --peer-id peer-01 --host 127.0.0.1 --port 9002 --tracker http://127.0.0.1:8000 --metadata "demo.torrent.json" --output-dir "demo-downloads"
```

macOS/Linux:

```sh
# 1. Tracker
./.venv-submission/bin/python -X utf8 -m bittorrent_lite.discovery.tracker_server --host 127.0.0.1 --port 8000
# 2. Seeder
./.venv-submission/bin/python -X utf8 -m bittorrent_lite --peer-id seed-01 --host 127.0.0.1 --port 9001 --tracker http://127.0.0.1:8000 --metadata "demo.torrent.json" --seeder --file "demo-input.bin" --output-dir "demo-downloads"
# 3. Downloader
./.venv-submission/bin/python -X utf8 -m bittorrent_lite --peer-id peer-01 --host 127.0.0.1 --port 9002 --tracker http://127.0.0.1:8000 --metadata "demo.torrent.json" --output-dir "demo-downloads"
```

The downloaded file is `demo-downloads/peer-01/demo-input.bin`. After completion,
compare it with the input. In a fourth PowerShell terminal:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath "demo-input.bin", "demo-downloads/peer-01/demo-input.bin"
```

The two hashes must match. On macOS/Linux, an exact byte comparison is:

```sh
cmp "demo-input.bin" "demo-downloads/peer-01/demo-input.bin"
```

`cmp` returns zero with no output when the files match. A completed peer keeps
running to seed. Stop the two peers with Ctrl+C, then stop the tracker with Ctrl+C.

## Teammates on the same LAN

Each teammate installs the same source version locally. Give every peer the
**same saved `demo.torrent.json` file**; only seeders need the original source
file. Paths may differ between computers.

- On the tracker computer, change its command to `--host 0.0.0.0`.
- On each peer, change `--host 127.0.0.1` to `--host 0.0.0.0` and change the
  tracker URL to the tracker's reachable LAN IPv4 address, for example
  `http://192.168.1.20:8000`. Replace the example with the actual address.
- Use a unique peer ID per peer and distinct listening ports for processes on
  the same computer. Keep the tracker and seeder running during the transfer.
- Permit the chosen TCP ports on the trusted/private LAN through normal
  firewall settings. Guest/campus Wi-Fi isolation or a VPN can prevent peers
  from connecting. `127.0.0.1` refers to the current computer; `0.0.0.0` is a
  listening address, not a tracker URL destination.

## Submission status and supporting documents

The [final handoff report](bittorrent_lite/docs/integration/college-submission-2026-10-22.md)
contains the verified results and links to compact test evidence. This working
repository is prepared for GitHub review; no commit or upload has been performed.

This is a practical submission handoff. The **27-run measured experiment study
and cross-device testing have not been completed**. The full final acceptance
campaign is not claimed complete. Do not present planned experiment figures,
team reviews, human signoffs, or demo attendance as completed results.

Keep [README.md](README.md), [AI-USE.md](AI-USE.md), the original plans, and the
component documentation with the source. The
[team runbook](bittorrent_lite/docs/integration/TEAM-RUNBOOK.md) has more setup
details; [ownership](bittorrent_lite/docs/ownership.md) and
[architecture](bittorrent_lite/docs/architecture.md) explain responsibilities
and design. The preserved final acceptance plan is a separate, more extensive
plan; it is not an additional completion gate for this submission-only handoff.
