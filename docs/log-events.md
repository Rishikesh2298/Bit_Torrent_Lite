# Structured run events (needed for experiments)

The experiment harness measures everything from one JSON line per event.
Peers write them with:

```python
from bittorrent_lite import run_log
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
- Write the finished file to `<--output-dir>/<metadata.filename>`; the
  launcher checks its SHA-256 independently.
- Set `SO_REUSEADDR` on the listening socket (except on Windows) so the next
  run can reuse the port while old connections sit in TIME_WAIT.
- For the selection and free-rider experiments: accept `--strategy
  {rarest,random,sequential}` and `--upload-slots N`, then set
  `strategy_args` / `free_rider_args` in `experiments/configs/base.json`.
