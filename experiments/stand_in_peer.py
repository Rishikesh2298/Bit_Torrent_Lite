"""
Stand-in peer for testing the harness before peer_main works.

It does the real discovery part (binds a listening socket, runs the real
DiscoveryWorker against the real tracker) but SIMULATES the download: it
emits piece_verified/progress events at a fixed rate and copies the source
file into its output directory at the end. Every event it emits carries
"synthetic": true, and configs that use it must set "synthetic": true so the
run is labelled "<environment>-synthetic". Never report these numbers as
results; they only validate the launcher, collector and plots.

Accepts the same arguments as peer_main plus:
    --simulate-source PATH   file to copy as the "downloaded" output
    --pieces-per-s N         simulated download rate (default 20)
    --upload-slots N         0 makes it report zero uploaded bytes
"""

import argparse
import queue
import shutil
import signal
import socket
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from bittorrent_lite import run_log  # noqa: E402
from bittorrent_lite.file_manager.metadata import load_metadata  # noqa: E402
from bittorrent_lite.peer.tracker_client import DiscoveryWorker, PeersDiscovered  # noqa: E402

_stop = False


def _on_term(signum, frame):
    global _stop
    _stop = True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Synthetic stand-in peer")
    parser.add_argument("--peer-id", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--tracker", required=True)
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--seeder", action="store_true")
    parser.add_argument("--file")
    parser.add_argument("--strategy", default="rarest")
    parser.add_argument("--upload-slots", type=int, default=2)
    parser.add_argument("--simulate-source")
    parser.add_argument("--pieces-per-s", type=float, default=20.0)
    parser.add_argument("--exit-after-s", type=float, default=None,
                        help="crash deliberately after N seconds (tests)")
    args = parser.parse_args(argv)

    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)

    metadata, file_id = load_metadata(args.metadata)
    total = metadata.num_pieces

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sys.platform != "win32":
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", args.port))
    listener.listen()
    bound = listener.getsockname()[1]
    run_log.emit("listening", port=bound, role="seeder" if args.seeder else "downloader",
                 synthetic=True)

    events = queue.Queue(maxsize=128)
    worker = DiscoveryWorker(args.tracker, file_id, args.peer_id, bound, events)
    worker.start()

    pieces = total if args.seeder else 0
    if args.seeder:
        worker.mark_completed()
    started = time.monotonic()
    next_piece_at = started
    interval = 1.0 / args.pieces_per_s
    uploaded = 0
    known_peers = 0
    done = args.seeder

    while not _stop:
        if args.exit_after_s is not None and time.monotonic() - started >= args.exit_after_s:
            return 3
        try:
            item = events.get(timeout=0.02)
            if isinstance(item, PeersDiscovered):
                known_peers = len(item.peers)
        except queue.Empty:
            pass
        if done or known_peers == 0:
            continue
        now = time.monotonic()
        while pieces < total and now >= next_piece_at:
            size = metadata.expected_piece_size(pieces)
            run_log.emit("piece_verified", piece=pieces, bytes=size, synthetic=True)
            pieces += 1
            next_piece_at += interval
            if pieces % max(1, total // 20) == 0 or pieces == total:
                run_log.emit("progress", pieces=pieces, total=total, synthetic=True)
            if args.upload_slots > 0:
                uploaded += size // 2
        if pieces == total:
            out_dir = Path(args.output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            if args.simulate_source:
                shutil.copyfile(args.simulate_source, out_dir / metadata.filename)
            run_log.emit("complete", final_hash_ok=True, synthetic=True)
            worker.mark_completed()
            done = True

    run_log.emit("counters", messages_sent=pieces * 2, requests_sent=0 if args.seeder else pieces,
                 retries=0, hash_failures=0, uploaded_payload_bytes=uploaded,
                 verified_download_bytes=0 if args.seeder else sum(
                     metadata.expected_piece_size(i) for i in range(pieces)),
                 synthetic=True)
    worker.stop()
    listener.close()
    run_log.emit("exit", reason="stopped", synthetic=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
