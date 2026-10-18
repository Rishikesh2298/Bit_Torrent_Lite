"""
Create the deterministic experiment fixture and its metadata.

    python -m experiments.make_fixture --size-mib 32 --out experiments/data

Writes <out>/fixture.bin (pseudo-random bytes from a fixed seed, so every
member generates the identical file) and <out>/fixture.torrent.json using
Rishikesh's metadata functions. Prints the file SHA-256 and file_id.
"""

import argparse
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from bittorrent_lite.config import PIECE_SIZE  # noqa: E402
from bittorrent_lite.file_manager.metadata import (  # noqa: E402
    create_metadata, load_metadata, save_metadata,
)


def make_fixture(out_dir: Path, size_bytes: int, seed: int = 30003,
                 piece_size: int = PIECE_SIZE) -> tuple[Path, Path, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    data_path = out_dir / "fixture.bin"
    meta_path = out_dir / "fixture.torrent.json"
    rng = random.Random(seed)
    remaining = size_bytes
    with open(data_path, "wb") as handle:
        while remaining:
            n = min(remaining, 1 << 20)
            handle.write(rng.randbytes(n))
            remaining -= n
    save_metadata(create_metadata(str(data_path), piece_size), str(meta_path))
    metadata, file_id = load_metadata(str(meta_path))
    return data_path, meta_path, file_id


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Create the experiment fixture")
    parser.add_argument("--size-mib", type=float, default=32)
    parser.add_argument("--seed", type=int, default=30003)
    parser.add_argument("--out", default=str(REPO_ROOT / "experiments" / "data"))
    args = parser.parse_args(argv)
    data, meta, file_id = make_fixture(Path(args.out), int(args.size_mib * 1024 * 1024), args.seed)
    metadata, _ = load_metadata(str(meta))
    print(f"fixture:  {data} ({metadata.file_size} bytes, {metadata.num_pieces} pieces)")
    print(f"sha256:   {metadata.file_sha256}")
    print(f"metadata: {meta}")
    print(f"file_id:  {file_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
