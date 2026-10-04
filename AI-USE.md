# AI Usage Documentation

## Project: P8 – P2P File Distribution (BitTorrent-Lite)
## Course: CS-30003 – Coding Assignment 1

---

## AI Tool Used

- **Tool:** Google Antigravity (Claude-based coding assistant)
- **Additional tool:** OpenAI Codex (repository review, picker assistance and regression fixes)
- **Period:** September–October 2026

---

## How AI Was Used

### ✅ Permitted Uses

| Category | Description |
|---|---|
| **Architecture & Design** | AI helped design the modular architecture, module interfaces, and data structures |
| **Concept Explanation** | AI explained networking concepts (TCP framing, rarest-first, choking, bitfields) |
| **Project Scaffolding** | AI generated boilerplate: directory structure, `config.py`, `logger.py`, `types.py`, `.gitignore`, `requirements.txt` |
| **Interface Stubs** | AI generated function signatures and docstrings as module contracts |
| **Documentation Templates** | AI generated `protocol_spec.md`, `README.md`, `AI-USE.md` templates |
| **Test Generation** | AI helped write unit tests and integration test harnesses |
| **Debugging** | AI reviewed team-written code, identified bugs, and explained fixes |
| **Experiment Scripts** | AI helped write experiment runner scripts and plotting code |
| **Code Review** | AI reviewed implementations for correctness, edge cases, and style |

### ❌ Not Used For

| Category | Description |
|---|---|
| **Core Protocol Implementation** | All peer wire protocol code (handshake, bitfield, HAVE, REQUEST, PIECE, CANCEL) was written by team members |
| **Tracker Implementation** | The tracker server and state management were implemented by team members |
| **Choking/Unchoking** | The choking strategy was implemented by team members |
| **Peer State Machine** | The peer connection state machine was implemented by team members |
| **Message Framing** | TCP framing (partial reads, length-prefixed messages) was implemented by team members |

---

## Detailed Log

<!-- Add entries as the project progresses -->

| Date | Member | What AI Helped With | Category |
|---|---|---|---|
| 2026-09-15 | All | Architecture design, module interfaces, project scaffolding | Design & Boilerplate |
| 2026-10-04 | Prabhat | OpenAI Codex audited progress, assisted the initial neighborhood availability and rarest-first picker implementation, wrote contract/import tests, repaired stale shared-type imports and an unused missing-constant import, and documented remaining work. This includes AI assistance with core selection code; Prabhat must review, understand and check course rules before submission. | Implementation Assistance, Testing, Integration Review & Documentation |
| 2026-10-04 | Prabhat | At the user's request for extensive repository testing, Codex reproduced and fixed validation, stale piece-state, source verification, output preservation and peer-state defects; wired the existing metadata CLI to implemented functions; added boundary, fault-injection, randomized and concurrent tests; corrected README status. | Debugging, Regression Testing & Documentation |
| | | | |

---

## Team Declaration

We confirm that:
1. The initial piece-picker implementation received OpenAI Codex assistance on 4 October 2026, as recorded above. The team must review authorship and permitted AI use before submission; the earlier all-team-written claim does not apply to this selection code.
2. AI was used only for permitted purposes as described above.
3. Every team member understands the complete system and can explain/modify any part.

**Team P8:**
- Rishikesh Kumar (2405600)
- Debargha Bhadra (2405575)
- Prabhat Ranjan Swain (2405590)
- Anik Dey (2405558)
