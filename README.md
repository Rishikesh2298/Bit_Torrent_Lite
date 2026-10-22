# BitTorrent-Lite

**CS-30003 – Coding Assignment 1 | Project P8 – P2P File Distribution**

A simplified peer-to-peer file distribution system inspired by BitTorrent, built as an educational implementation of core P2P concepts.

---

## Team

| Member | Roll No. | Module |
|---|---|---|
| Rishikesh Kumar | 2405600 | File & Metadata |
| Debargha Bhadra | 2405575 | Tracker & Peer Discovery |
| Anik Dey | 2405558 | Networking & Peer Protocol |
| Prabhat Ranjan Swain | 2405590 | Piece Management & Concurrency |

---

## Features

- [x] File splitting into fixed-size pieces
- [x] SHA-256 per-piece hash verification
- [x] JSON metadata format (.torrent.json)
- [x] HTTP-based tracker and real peer discovery
- [x] Peer wire protocol over TCP
- [x] Handshake with file_id verification
- [x] Bitfield exchange
- [x] Rarest-first piece selection (standalone picker tested)
- [x] Request pipelining with socket-write acknowledgements
- [x] Concurrent multi-peer transfers (six downloaders tested on localhost)
- [x] Peer failure handling and verified-piece restart
- [x] File reconstruction and verification
- [x] Bounded upload service (verified pieces and acknowledged byte accounting)
- [x] Choking/unchoking (acknowledged regular and optimistic upload slots)

---

## Architecture

```text
BitTorrent/
├── bittorrent_lite/
│   ├── storage/          # Rishikesh
│   ├── discovery/        # Debargha
│   ├── networking/       # Anik
│   ├── scheduling/       # Prabhat (including preserved policy packages)
│   ├── application/      # Integration, runtime and CLI
│   ├── common/           # Shared configuration, types, events and interfaces
│   ├── tests/            # Member areas and integration checks
│   ├── experiments/      # Configurations and scripts
│   ├── examples/
│   └── docs/             # Original plans, ownership and technical documents
├── pyproject.toml
├── pytest.ini
├── requirements.txt
├── README.md
└── AI-USE.md
```

See the [documentation index](bittorrent_lite/docs/README.md),
[ownership map](bittorrent_lite/docs/ownership.md), and
[portable setup guide](bittorrent_lite/docs/architecture.md).

For fresh environments, moved folders and teammate devices, use the
[team runbook](bittorrent_lite/docs/integration/TEAM-RUNBOOK.md).
For the college submission and a three-terminal demo, start with
[COLLEGE-SUBMISSION.md](COLLEGE-SUBMISSION.md). The user has limited this handoff
to practical project readiness; the extensive final-acceptance campaign and
27-run performance study have not been completed.

The [college handoff report](bittorrent_lite/docs/integration/college-submission-2026-10-22.md)
records the final selected checks: **797 distinct tests passed**, plus **three
fresh installed-package transfers** from relocated paths containing spaces and
non-ASCII characters. The source is prepared locally for GitHub review; no upload
has been performed.

The real TCP/discovery backend is connected. An earlier complete reorganized
suite passed **784 tests**, including **33 real end-to-end cases**, with no skips.
See the [end-to-end report](bittorrent_lite/docs/integration/end-to-end-validation-2026-10-22.md)
for evidence, preservation checks and limits. Validation used Windows localhost;
cross-laptop/LAN operation has not been tested.
The earlier [unit-stage report](bittorrent_lite/docs/integration/unit-validation-2026-10-22.md)
records its own fixes and interrupted runner-selection mistake. Historical
feature/test claims below refer to the pre-migration work.

---

## Quick Start

### Prerequisites

```bash
# Python 3.10 or newer
python -m pip install -e ".[test,experiments]"
```

### 1. Generate Metadata

```bash
python -m bittorrent_lite.storage.generate_metadata --file path/to/file --output file.torrent.json
```

### 2. Start Tracker

The CLI uses the real TCP/discovery backend. Start the tracker and each peer in
separate terminals. See the [backend guide](bittorrent_lite/docs/integration/real-network-backend.md)
for portable paths, graceful shutdown and experiment configuration.

```bash
python -m bittorrent_lite.discovery.tracker_server --port 8000
```

### 3. Start Seeder

```bash
python -m bittorrent_lite.application.cli \
    --peer-id seeder-001 --port 9000 \
    --tracker http://127.0.0.1:8000 \
    --metadata file.torrent.json \
    --seeder --file path/to/file
```

### 4. Start Peers (in separate terminals)

```bash
python -m bittorrent_lite.application.cli \
    --peer-id peer-001 --port 9001 \
    --tracker http://127.0.0.1:8000 \
    --metadata file.torrent.json
```

---

## Protocol

See the [current JSON wire protocol](bittorrent_lite/docs/integration/CURRENT-WIRE-PROTOCOL.md).
The [original protocol draft](bittorrent_lite/docs/anik/protocol_spec.md) remains
preserved as historical design material.

## Tests

Prabhat's Part 1 scheduler is integrated under `bittorrent_lite.scheduling`.
Part 2's standalone `bittorrent_lite.scheduling.request_pipeline` package now owns its request lifecycle,
with four requests per connection by default and fair rarest-first allocation.
See [Part 2 integration](bittorrent_lite/docs/prabhat/request-pipeline.md) for behavior and validation.
Part 3's `bittorrent_lite.scheduling.recovery` now supplies retry backoff, provider exclusions,
selection strategies and cancellation. The project defaults prohibit endgame
duplicates, as required by the original plan.
See [recovery integration](bittorrent_lite/docs/prabhat/recovery-policy.md) for configuration and limits.
The combined Part 4 adds `bittorrent_lite.scheduling.upload_service` and `bittorrent_lite.scheduling.choking_policy`, connected through
`SchedulerBridge.create_coordinator(store)`. See [uploads and choking](bittorrent_lite/docs/prabhat/upload-and-choking.md)
for setup, transport acknowledgement requirements, tests and remaining limits.
The project uses five-second interval scoring and stable rotating upload slots.
See [original-plan alignment](bittorrent_lite/docs/integration/original-plan-alignment.md) for current
behavior, transport handoff requirements, and remaining team integration.
Run `python -m bittorrent_lite.examples.scheduler_demo` for the single-request example.
See [scheduler integration](bittorrent_lite/docs/prabhat/scheduler.md) for protocol/storage adapters,
interfaces, limitations, and test coverage. The CLI supports `--check-config`,
strategy/window/seed/free-rider controls, a real backend by default and an
optional injected backend factory for component tests.

Run `python -m pytest` from the repository root after installing dependencies.
Tests cover the implemented file manager, metadata CLI, message objects,
peer-state container, piece picker and package imports. The 56 legacy placeholders
now execute real checks. Tracker state is implemented; historical test evidence is recorded separately;
see [test audit](bittorrent_lite/docs/integration/test-audit.md).
Message-object tests do not establish working TCP framing or a working swarm.

---

## Experiments

Harness, measurement definitions and commands: [bittorrent_lite/docs/debargha/experiment-method.md](bittorrent_lite/docs/debargha/experiment-method.md).
Events peers must log for measurements: [bittorrent_lite/docs/debargha/log-events.md](bittorrent_lite/docs/debargha/log-events.md).
Tracker contract: [bittorrent_lite/docs/debargha/tracker.md](bittorrent_lite/docs/debargha/tracker.md).

1. **Distribution time vs swarm size** (2, 4, 6, 8 peers)
2. **Piece selection strategy** (sequential vs random vs rarest-first)
3. **Seeder count** (1 vs 2 seeders)
4. **Free rider** (peer that doesn't upload)
5. **Peer failure** (peer disconnects mid-transfer)

---

## License

Academic project — not intended for production use.
