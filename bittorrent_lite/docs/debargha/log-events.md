# Structured run events (needed for experiments)

The experiment harness measures everything from one JSON line per event.
Peers write them with:

```python
from bittorrent_lite.common import run_log
run_log.emit("piece_verified", piece=index, bytes=len(data))
```

`emit()` does nothing unless the launcher set `BTL_EVENT_LOG`, so it is safe to
call anywhere, from any thread. It adds `mono` (time.monotonic()) and `proc`.

## Events the harness needs from the peer (owner in brackets)

| Event | Fields | Emit when | Owner |
|---|---|---|---|
| `listening` | `port` | listening socket bound; **launcher waits for this** | peer_main |
| `piece_verified` | `piece`, `bytes` | a newly received piece passed its hash and was stored | Prabhat (coordinator) |
| `progress` | `pieces`, `total` | after each verified piece (or every few); **failure trigger uses this** | Prabhat |
| `piece_uploaded` | `piece`, `bytes`, `to` | a PIECE payload was completely written to a socket | Anik |
| `hash_failure` | `piece`, `from` | received piece failed verification | Prabhat |
| `complete` | `final_hash_ok` | final file assembled and whole-file hash checked | peer_main / Rishikesh |
| `counters` | `messages_sent`, `requests_sent`, `retries`, `hash_failures`, `uploaded_payload_bytes`, `verified_download_bytes` | at shutdown (last one wins) | Anik + Prabhat |
| `exit` | `reason` | just before the process exits | peer_main |

Already emitted by the discovery worker: `peers_discovered`, `tracker_error`.
Already emitted by the tracker: `tracker_ready`, `tracker_announce`, `tracker_rejected`.

Definitions: count a message once, at the sender, when the whole frame was
written. Uploaded bytes are PIECE payload only (no headers). Verified bytes
exclude duplicates and corrupt pieces.

## What else peer_main needs for the launcher

- Exit cleanly on SIGTERM (the launcher calls `terminate()`), calling
  `worker.stop()` so the tracker gets `stopped`.
- Keep running (seeding) after `complete` until terminated.
- The real CLI writes to `<--output-dir>/<peer-id>/<metadata.filename>`.
  The launcher supplies the common peer-output root and checks each hash
  independently. The preserved synthetic CLI receives its individual peer folder.
- Set `SO_REUSEADDR` on the listening socket (except on Windows) so the next
  run can reuse the port while old connections sit in TIME_WAIT.
- The real CLI accepts `--strategy {rarest-first,random,sequential}`,
  `--window`, `--seed` and `--free-rider`. The launcher maps its historical
  `rarest` label and configures these arguments in `base.json`.

As of 22 October 2026, real peers emit listening, piece_verified, progress,
piece_uploaded, complete, final verified/uploaded byte counters and exit.
Aggregate messages_sent, requests_sent, retries and hash_failures are not yet
instrumented for real peers; the collector leaves them undefined. See the
[backend guide](../integration/real-network-backend.md) for the current contract.
