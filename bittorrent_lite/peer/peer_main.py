"""Peer CLI and injectable runtime assembly; socket/discovery backend is a handoff."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import re
import sys

from bittorrent_lite.config import TRACKER_HOST, TRACKER_PORT
from bittorrent_lite.file_manager.metadata import load_metadata
from bittorrent_lite.file_manager.file_store import FileStore
from .runtime import PeerRuntime, RuntimeConfig


def build_parser():
    parser = argparse.ArgumentParser(description="BitTorrent-Lite Peer")
    parser.add_argument("--peer-id", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--tracker", default=f"http://{TRACKER_HOST}:{TRACKER_PORT}")
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--seeder", action="store_true")
    parser.add_argument("--file", help="Required source file for a seeder")
    parser.add_argument("--output-dir", default="downloads")
    parser.add_argument("--strategy", choices=("sequential", "random", "rarest-first"), default="rarest-first")
    parser.add_argument("--window", type=int, choices=range(1, 5), default=4)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--free-rider", action="store_true")
    parser.add_argument("--upload-workers", type=int, choices=(0, 2), default=0)
    parser.add_argument("--shutdown-timeout", type=float, default=5)
    parser.add_argument("--check-config", action="store_true", help="Validate local inputs without starting networking")
    return parser


def configuration(args):
    if (not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", args.peer_id)
            or args.peer_id in (".", "..")):
        raise ValueError("peer ID must be a safe nonempty directory label")
    if not 1 <= args.port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    if args.seeder != bool(args.file):
        raise ValueError("--seeder and --file must be supplied together")
    if args.file and not Path(args.file).is_file():
        raise ValueError("source file does not exist")
    return RuntimeConfig(strategy=args.strategy, window=args.window, seed=args.seed,
                         free_rider=args.free_rider, upload_workers=args.upload_workers,
                         shutdown_timeout=args.shutdown_timeout)


def main(argv=None, *, backend_factory=None):
    args = build_parser().parse_args(argv)
    try:
        config = configuration(args)
        metadata, file_id = load_metadata(args.metadata)
        if (metadata.filename in (".", "..") or
                any(c in metadata.filename for c in ("/", "\\", ":", "\0"))):
            raise ValueError("metadata filename must be a plain filename, not a path")
        if args.check_config:
            print(json.dumps({"peer_id": args.peer_id, "file_id": file_id,
                              "num_pieces": metadata.num_pieces, "config": asdict(config)}))
            return 0
        if backend_factory is None:
            print("Network backend is not connected yet. Use --check-config or supply the team backend to main().", file=sys.stderr)
            return 2
        root = Path(args.output_dir) / args.peer_id
        output = root / metadata.filename
        if args.file and output.resolve() == Path(args.file).resolve():
            raise ValueError("output must not overwrite the seeder source")
        root.mkdir(parents=True, exist_ok=True)
        store = FileStore(metadata, file_id, str(root / "pieces"), args.file)
        backend = backend_factory(args, metadata, file_id)
        runtime = PeerRuntime(args.peer_id, store, output, backend, config=config,
                              emit=lambda record: print(json.dumps(record), flush=True))
        try:
            runtime.run()
        except KeyboardInterrupt:
            pass  # run() always performs owner-thread cleanup
        status = runtime.status()
        return 1 if runtime.shutdown_errors or status["storage_error"] or status["recovery_error"] else 0
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
