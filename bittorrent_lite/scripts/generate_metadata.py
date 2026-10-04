"""
Generate Metadata CLI

Usage:
    python -m bittorrent_lite.scripts.generate_metadata \
        --file path/to/source/file \
        --output file.torrent.json \
        [--piece-size 524288]
"""

import argparse
from pathlib import Path
from bittorrent_lite.config import PIECE_SIZE
from bittorrent_lite.file_manager.metadata import create_metadata, save_metadata


def main():
    parser = argparse.ArgumentParser(
        description="Generate .torrent.json metadata for a file"
    )
    parser.add_argument("--file", required=True, help="Source file path")
    parser.add_argument("--output", required=True, help="Output .torrent.json path")
    parser.add_argument("--piece-size", type=int, default=PIECE_SIZE,
                        help=f"Piece size in bytes (default: {PIECE_SIZE})")

    args = parser.parse_args()

    try:
        source, output = Path(args.file), Path(args.output)
        if source.resolve() == output.resolve() or (
                source.exists() and output.exists() and source.samefile(output)):
            raise ValueError("metadata output must differ from the source file")
        metadata = create_metadata(args.file, args.piece_size)
        save_metadata(metadata, args.output)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f"Metadata saved: {args.output}")
    print(f"  File: {metadata.filename}")
    print(f"  Size: {metadata.file_size} bytes")
    print(f"  Pieces: {metadata.num_pieces} x {metadata.piece_size} bytes")


if __name__ == "__main__":
    main()
