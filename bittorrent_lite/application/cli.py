"""Peer CLI with real TCP/discovery and an injectable backend for component tests."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import sys
import signal
import threading

from bittorrent_lite.common.config import TRACKER_HOST
from bittorrent_lite.common.config import TRACKER_PORT
from bittorrent_lite.common import run_log
from bittorrent_lite.storage.metadata import load_metadata
from bittorrent_lite.storage.file_store import FileStore
from bittorrent_lite.application.runtime import PeerRuntime
from bittorrent_lite.application.runtime import RuntimeConfig


def build_parser():
    parser = argparse.ArgumentParser(description="BitTorrent-Lite Peer")
    parser.add_argument("--peer-id", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--host", default="0.0.0.0", help="Local IPv4 interface to listen on")
    parser.add_argument("--stop-file", help="Gracefully stop when this file exists (for process supervisors)")
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
    parser.add_argument("--resource-metrics", action="store_true",
                        help="Sample process resources once per second (requires the acceptance extra)")
    return parser


def configuration(args):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", args.peer_id):
        raise ValueError("peer ID must use 1-32 letters, digits, underscores or hyphens")
    if not 1 <= args.port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    if args.seeder != bool(args.file):
        raise ValueError("--seeder and --file must be supplied together")
    if args.file and not Path(args.file).is_file():
        raise ValueError("source file does not exist")
    return RuntimeConfig(strategy=args.strategy, window=args.window, seed=args.seed,
                         free_rider=args.free_rider, upload_workers=args.upload_workers,
                         shutdown_timeout=args.shutdown_timeout)


def validate_local_paths(args, metadata, file_id):
    """Use a portable output basename and prevent seeder source aliasing."""
    name = metadata.filename
    reserved = {'CON', 'PRN', 'AUX', 'NUL',
                *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}
    if (name in ('.', '..') or name.endswith((' ', '.'))
            or name.split('.', 1)[0].upper() in reserved
            or any(ord(c) < 32 or c in '<>:"/\\|?*' for c in name)):
        raise ValueError('metadata filename must be a portable plain filename, not a path or device name')
    root = Path(args.output_dir) / args.peer_id
    output = root / name
    if args.file:
        source = Path(args.file)
        if (output.resolve() == source.resolve()
                or (output.exists() and os.path.samefile(output, source))):
            raise ValueError('output must not overwrite the seeder source')
        # Source-mode FileStore performs no directory creation.
        FileStore(metadata, file_id, str(root / 'pieces'), str(source)).validate_source()
    return root, output


def main(argv=None, *, backend_factory=None):
    args = build_parser().parse_args(argv)
    try:
        config = configuration(args)
        metadata, file_id = load_metadata(args.metadata)
        from bittorrent_lite.application.network_backend import validate_network_inputs
        validate_network_inputs(args, metadata)
        root, output = validate_local_paths(args, metadata, file_id)
        resource_sampler = None
        if args.resource_metrics:
            try:
                from bittorrent_lite.acceptance_tools.resources import process_sample
                process_sample()
            except (ImportError, OSError) as exc:
                raise ValueError("resource metrics unavailable; install the acceptance extra") from exc
            resource_sampler = process_sample
        if args.check_config:
            print(json.dumps({"peer_id": args.peer_id, "file_id": file_id,
                              "num_pieces": metadata.num_pieces, "config": asdict(config)}))
            return 0
        if backend_factory is None:
            from bittorrent_lite.application.network_backend import NetworkBackend
            backend_factory = NetworkBackend
        root.mkdir(parents=True, exist_ok=True)
        store = FileStore(metadata, file_id, str(root / "pieces"), args.file)
        backend = backend_factory(args, metadata, file_id)
        def record_event(record):
            print(json.dumps(record), flush=True)
            event = record['event']
            if event == 'START':
                run_log.emit('listening', port=args.port)
            elif event == 'COMPLETE':
                run_log.emit('complete', final_hash_ok=True)
            elif event == 'STOPPED':
                run_log.emit('counters', verified_download_bytes=record['verified_download_bytes'],
                             uploaded_payload_bytes=record['uploaded_payload_bytes'])
                run_log.emit('exit', reason='error' if record['errors'] or record['storage_error']
                             or record['recovery_error'] else 'stopped')
            else:
                run_log.emit(event.lower(), **{k: v for k, v in record.items() if k != 'event'})
        runtime = PeerRuntime(args.peer_id, store, output, backend, config=config, emit=record_event,
                              resource_sampler=resource_sampler)
        previous_handlers = {}
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGINT, signal.SIGTERM):
                previous_handlers[sig] = signal.signal(sig, lambda *_: runtime.request_stop())
        try:
            if args.stop_file:
                stop_file = Path(args.stop_file).resolve()
                runtime.run(stop_when=stop_file.exists)
            else:
                runtime.run()
        except KeyboardInterrupt:
            pass  # run() always performs owner-thread cleanup
        finally:
            for sig, handler in previous_handlers.items():
                signal.signal(sig, handler)
        status = runtime.status()
        return 1 if runtime.shutdown_errors or status["storage_error"] or status["recovery_error"] else 0
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
