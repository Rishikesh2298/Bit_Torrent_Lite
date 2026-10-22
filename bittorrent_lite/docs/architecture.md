# Architecture and portable setup

```text
BitTorrent/
  bittorrent_lite/
    __main__.py
    storage/                 # Rishikesh
    discovery/               # Debargha
    networking/              # Anik
    scheduling/              # Prabhat
      legacy/
      request_pipeline/
      recovery/
      upload_service/
      choking_policy/
    application/             # Integration
    common/                  # Shared contracts and configuration
    tests/
      storage/
      discovery/
      networking/
      scheduling/
      integration/
      end_to_end/
    experiments/
      configs/
      scripts/
    examples/
    docs/
      plans/original/
      plans/follow-up/
      rishikesh/
      debargha/
      anik/
      prabhat/
      integration/
  pyproject.toml
  pytest.ini
  requirements.txt
  README.md
  AI-USE.md
  AGENTS.md
  .gitignore
```

Discovery returns candidate peers; networking transports typed messages;
scheduling owns request and upload decisions; storage validates and persists
bytes. Application adapters connect these responsibilities. Moving a file does
not change which layer owns its behavior.

## Install on another laptop

Use Python 3.10 or newer and follow the canonical
[teammate runbook](integration/TEAM-RUNBOOK.md) for fresh environments, core-only
installation, optional extras, verified wheel installation and LAN setup. It
uses explicit interpreter paths, so environment activation and PowerShell
execution-policy changes are unnecessary. Source installation starts in the
folder containing `pyproject.toml` and `bittorrent_lite`.

An editable installation makes `bittorrent_lite` importable independently of the
current working directory. The dependency-only `requirements.txt` remains
available. Runtime modules use the Python standard library; tests and plotting
have separate optional dependencies. No environment or machine-specific Python
executable is committed.

## Commands

Use the installed environment's interpreter for `python` below. These examples
use paths relative to the repository root; use your own absolute data paths
when running from another folder. Experiment scripts require the source tree.

```sh
python -m bittorrent_lite --help
python -m bittorrent_lite.storage.generate_metadata --file input.bin --output input.torrent.json
python -m bittorrent_lite.discovery.tracker_server --port 8000
python -m bittorrent_lite.examples.scheduler_demo
python -m bittorrent_lite.experiments.scripts.make_fixture --size-mib 32 --out bittorrent_lite/experiments/data
python -m bittorrent_lite.experiments.scripts.launcher bittorrent_lite/experiments/configs/base.json
```

The peer CLI uses the real TCP/discovery backend by default. See the
[backend guide](integration/real-network-backend.md) for peer launch commands,
paths, shutdown and experiment integration. The synthetic experiment peer
remains explicitly synthetic and is tested separately from real transfers.

## Path conventions

- Repository discovery uses the nearby `pyproject.toml` marker, not a username,
  drive letter, fixed checkout name or current working directory.
- Experiment fixture/metadata paths in configurations are repository-relative;
  absolute paths remain supported. Config-file arguments and explicit output
  arguments are resolved from the caller's working directory.
- The launcher resolves its output directory before starting child processes,
  uses argument lists and `sys.executable`, and sets each child's working
  directory to the discovered repository root.
- CLI source, metadata and output arguments remain user-controlled; relative
  paths follow the caller's working directory. Paths with spaces should be quoted.
- Experiment tooling runs from a source checkout or editable installation.
  A wheel installation alone is not a portable experiment workspace.
- Generated experiment data/results, caches and virtual environments are
  excluded from Git. Do not copy a virtual environment between laptops.

## Original plan mapping

The guide's `src/` layout was a suggested initial layout. Its responsibilities
map to `storage/`, `discovery/`, `networking/`, `scheduling/` and `application/`.
The original five plans are unchanged under `docs/plans/original/`.
See [ownership](ownership.md) for the complete responsibility split.
