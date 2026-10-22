"""``python -m upload_service demo --directory ./upload-demo``"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from . import (
    DataOutput,
    DirectorySource,
    UploadRequest,
    UploadService,
    load_manifest,
)


def _demo(directory: Path) -> int:
    if directory.exists() and (not directory.is_dir() or any(directory.iterdir())):
        print(f"error: {directory} exists and is not an empty directory", file=sys.stderr)
        return 1
    directory.mkdir(parents=True, exist_ok=True)

    pieces = [bytes(range(256)) * 128, bytes(reversed(range(256))) * 128]
    entries = []
    for index, data in enumerate(pieces):
        (directory / f"piece-{index:06d}.bin").write_bytes(data)
        entries.append({"index": index, "length": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(json.dumps({"version": 1, "pieces": entries}), encoding="utf-8")

    manifest = load_manifest(manifest_path)
    service = UploadService(manifest, DirectorySource(manifest, directory))
    for piece in (0, 1):
        admission = service.submit(UploadRequest("demo-peer", piece), permitted=True)
        print(f"submit piece {piece}: accepted={admission.accepted} job_id={admission.job_id}")
    service.tick()

    print("--- SIMULATED delivery: no network transfer occurs; acknowledgements are local ---")
    for output in service.poll_outputs():
        if isinstance(output, DataOutput):
            result = service.mark_sent(output.job_id, len(output.data))
            print(
                f"job {output.job_id}: peer={output.peer_id} piece={output.piece} "
                f"bytes={len(output.data)} simulated mark_sent -> {result}"
            )
        else:
            print(f"job {output.job_id}: rejected ({output.reason})")
            service.mark_failed(output.job_id)
    service.shutdown()
    snap = service.snapshot()
    print(
        f"snapshot: sent_bytes={snap.sent_bytes} sent_pieces={snap.sent_pieces} "
        f"active_jobs={snap.active_jobs} closed={snap.closed}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m upload_service")
    sub = parser.add_subparsers(dest="command")
    demo = sub.add_parser("demo", help="run the local, simulated-delivery example")
    demo.add_argument("--directory", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == "demo":
        return _demo(args.directory)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
