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
- [ ] HTTP-based tracker for peer discovery
- [ ] Peer wire protocol over TCP
- [ ] Handshake with file_id verification
- [ ] Bitfield exchange
- [x] Rarest-first piece selection (standalone picker tested)
- [ ] Request pipelining
- [ ] Concurrent multi-peer transfers (6+ peers)
- [ ] Peer failure handling
- [x] File reconstruction and verification
- [ ] Choking/unchoking (simplified tit-for-tat)

---

## Architecture

```
bittorrent_lite/
├── config.py           # Global configuration
├── logger.py           # Centralized logging
├── types.py            # Shared data types
├── file_manager/       # File splitting, hashing, metadata, assembly
├── tracker/            # HTTP tracker server & state
├── protocol/           # Message definitions & TCP framing
├── peer/               # Peer connections, state, tracker client
└── piece_manager/      # Rarest-first, request tracking, choking
```

---

## Quick Start

### Prerequisites

```bash
python >= 3.10
pip install -r requirements.txt
```

### 1. Generate Metadata

```bash
python -m bittorrent_lite.scripts.generate_metadata --file path/to/file --output file.torrent.json
```

### 2. Start Tracker

Steps 2–4 describe the planned interface. The tracker, transport and peer loop
are currently stubs; end-to-end network transfers are not operational yet.

```bash
python -m bittorrent_lite.tracker.tracker_server --port 8000
```

### 3. Start Seeder

```bash
python -m bittorrent_lite.peer.peer_main \
    --peer-id seeder-001 --port 9000 \
    --tracker http://127.0.0.1:8000 \
    --metadata file.torrent.json \
    --seeder --file path/to/file
```

### 4. Start Peers (in separate terminals)

```bash
python -m bittorrent_lite.peer.peer_main \
    --peer-id peer-001 --port 9001 \
    --tracker http://127.0.0.1:8000 \
    --metadata file.torrent.json
```

---

## Protocol

See [docs/protocol_spec.md](docs/protocol_spec.md) for the full protocol specification.

## Tests

Run `python -m pytest` from the repository root after installing dependencies.
Tests cover the implemented file manager, metadata CLI, message objects,
peer-state container, piece picker and package imports. Legacy placeholder
tests remain skipped; a passing suite does not establish a working swarm.

---

## Experiments

<!-- TODO: Add experiment descriptions and results -->

1. **Distribution time vs swarm size** (2, 4, 6, 8 peers)
2. **Piece selection strategy** (sequential vs random vs rarest-first)
3. **Seeder count** (1 vs 2 seeders)
4. **Free rider** (peer that doesn't upload)
5. **Peer failure** (peer disconnects mid-transfer)

---

## License

Academic project — not intended for production use.
