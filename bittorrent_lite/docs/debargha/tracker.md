# Tracker and discovery

Owner: Debargha. Code: `bittorrent_lite/discovery/`, including `tracker_client.py`.
Tests: `bittorrent_lite/tests/discovery/test_tracker.py`, `bittorrent_lite/tests/discovery/test_tracker_client.py`.

The tracker tells a peer which other peers are in the same swarm. It never
sees file contents or bitfields and makes no scheduling decisions. A peer
list is a set of candidates: any of them may already be gone.

## Running it

```bash
python -m bittorrent_lite.discovery.tracker_server --host 127.0.0.1 --port 8000
```

## Announce contract

One endpoint: `POST /announce`, `Content-Type: application/json`, body at most
4096 bytes, `Content-Length` required.

| Field | Rule |
|---|---|
| `file_id` | 64 lowercase hex characters: SHA-256 of the exact metadata file bytes (`load_metadata()` returns it) |
| `peer_id` | 1 to 32 ASCII letters, digits, `_` or `-`; unique per running peer |
| `listen_port` | JSON integer 1 to 65535 (not `true`, not `"7002"`); the port the peer actually bound |
| `event` | `started`, `update`, `completed` or `stopped` |

Any other field is rejected. The peer's IP is taken from the HTTP connection,
never from the body (trusted lab network; there is no authentication).

### Example request

```json
{"file_id": "4141e1418f322241c3c15999f683a8aea3f2a4833e425c66b115db6dfd9cef73",
 "peer_id": "peer-02", "listen_port": 7003, "event": "started"}
```

### Success: 200

```json
{"interval": 5,
 "peers": [{"peer_id": "seed-01", "ip": "127.0.0.1", "port": 7001},
           {"peer_id": "peer-01", "ip": "127.0.0.1", "port": 7002}]}
```

`peers` holds only live peers of the same `file_id`, never the requester,
sorted by `peer_id`. `interval` is the seconds until the next announce.

### Stopped

```json
{"file_id": "4141e1…cef73", "peer_id": "peer-02", "listen_port": 7003, "event": "stopped"}
```

Removes the entry; sending it twice is harmless. The response still has the
normal shape.

### Errors

Body is always `{"error": "<message>"}`, and the connection is closed.

| Status | When |
|---|---|
| 400 | Not UTF-8 JSON, not an object, missing/unknown field, invalid value, bad Content-Length, incomplete body |
| 404 | Any path other than `/announce` |
| 405 | `/announce` with a method other than POST |
| 411 | No `Content-Length` |
| 413 | Body over 4096 bytes |
| 415 | `Content-Type` not `application/json`, or any `Transfer-Encoding` |

A client that stalls while sending its request is dropped after 2 seconds;
the server then serves the next request.

## Membership rules

Table key `(file_id, peer_id)`; value: source IP, listen port, last-seen
(monotonic), completed flag.

- `started` / `update`: insert or refresh. An `update` after a tracker
  restart recreates the entry, so a restarted tracker rebuilds its table
  within one announce interval.
- `completed`: insert or refresh and mark completed (kept on later updates).
- `stopped`: remove if present.
- An entry whose age is **at least 20 s** is removed before any response is
  built. There is no background cleanup thread.
- One peer ID has one endpoint per file; a new port or IP replaces the old one.

The server is single-threaded on purpose: every request is a small dictionary
operation, so no locking is needed.

## Discovery worker (for the peer process)

`DiscoveryWorker` keeps HTTP out of the coordinator thread.

```python
import queue
from bittorrent_lite.storage.metadata import load_metadata
from bittorrent_lite.discovery.tracker_client import DiscoveryWorker, PeersDiscovered, TrackerError

metadata, file_id = load_metadata(args.metadata)
listener.bind((host, args.port)); listener.listen()          # bind FIRST
bound_port = listener.getsockname()[1]

events = queue.Queue(maxsize=128)                          # the coordinator's queue
worker = DiscoveryWorker(args.tracker, file_id, args.peer_id, bound_port, events)
worker.start()

# coordinator loop
item = events.get(timeout=0.1)
if isinstance(item, PeersDiscovered):
    for peer in item.peers:          # PeerRecord(peer_id, ip, port); self already removed
        ...                          # connect if not already connected and under the limit
elif isinstance(item, TrackerError):
    ...                              # log only; keep existing connections

worker.mark_completed()              # after final verified assembly
worker.stop()                        # on shutdown; sends a best-effort "stopped"
```

Behaviour:

- Announces `started` at once, then `update` every `interval` seconds (the
  tracker's value clamped to 1 to 60).
- On failure waits 2, 4, then 10 seconds (repeating 10) and resets after a
  success. Each failure posts one `TrackerError` with category `unreachable`,
  `timeout`, `http_status` or `bad_response`. Console warnings are
  rate-limited.
- HTTP timeout 3 s; responses over 64 KiB or with any invalid field are
  rejected whole.
- `mark_completed()` and `announce_now()` cut the current wait short.
- `stop()` returns within about a second even during an outage; the
  `stopped` announce uses a 1 s timeout and its failure is ignored.
- If the coordinator's queue stays full for 1 s the event is dropped
  (counted in `worker.dropped_events`); the next announce brings a fresh list.

## Viva notes

- Why HTTP: simple, inspectable request/response; it still runs over TCP.
- Why source IP plus listen port: the TCP source port of the HTTP call is an
  ephemeral port, not the port the peer listens on.
- Why expiry: a crashed peer never sends `stopped`. Expiry is a timeout
  heuristic, not proof the peer is dead.
- Tracker outage: peers keep their existing connections; only discovery of
  new peers pauses.
