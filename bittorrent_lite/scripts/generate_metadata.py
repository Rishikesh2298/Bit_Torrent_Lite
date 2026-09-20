"""
Generate Metadata CLI

Usage:
    python -m bittorrent_lite.scripts.generate_metadata \
        --file path/to/source/file \
        --output file.torrent.json \
        [--piece-size 524288]
"""

import argparse
from bittorrent_lite.config import PIECE_SIZE


def main():
    parser = argparse.ArgumentParser(
        description="Generate .torrent.json metadata for a file"
    )
    parser.add_argument("--file", required=True, help="Source file path")
    parser.add_argument("--output", required=True, help="Output .torrent.json path")
    parser.add_argument("--piece-size", type=int, default=PIECE_SIZE,
                        help=f"Piece size in bytes (default: {PIECE_SIZE})")

    args = parser.parse_args()

    # TODO: Wire up to file_manager.metadata once implemented:
    # from bittorrent_lite.file_manager.metadata import create_metadata, save_metadata
    # metadata = create_metadata(args.file, args.piece_size)
    # save_metadata(metadata, args.output)
    # print(f"Metadata saved: {args.output}")
    # print(f"  File: {metadata.file_name}")
    # print(f"  Size: {metadata.file_size} bytes")
    # print(f"  Pieces: {metadata.num_pieces} x {metadata.piece_size} bytes")
    # print(f"  Info hash: {metadata.info_hash}")

    print("generate_metadata not yet implemented")


if __name__ == "__main__":
    main()
