"""
Peer Main — Integration Hub (All members contribute)

This is the entry point for a single peer process.
It wires together all modules and runs the main peer loop.

Responsibilities:
    1. Load metadata from .torrent.json
    2. Initialize PeerState
    3. If seeder: load file pieces into state
    4. Start listening socket (for incoming connections)
    5. Announce to tracker
    6. Get peer list from tracker
    7. Connect to discovered peers
    8. Register message callbacks
    9. Run until download is complete (or indefinitely if seeder)
    10. Assemble file when complete

Usage:
    python -m bittorrent_lite.peer.peer_main \\
        --peer-id peer-001 \\
        --port 9001 \\
        --tracker http://127.0.0.1:8000 \\
        --metadata file.torrent.json \\
        [--seeder --file path/to/source/file]

This is the most complex module. It should be built LAST,
after all component modules are working independently.
"""

import argparse

from bittorrent_lite.config import PEER_HOST, TRACKER_HOST, TRACKER_PORT


def main():
    """
    Entry point for a peer process.

    Parses CLI args, initializes state, and runs the main loop.
    """
    parser = argparse.ArgumentParser(description="BitTorrent-Lite Peer")
    parser.add_argument("--peer-id", required=True, help="Unique peer identifier")
    parser.add_argument("--port", type=int, required=True, help="Listening port")
    parser.add_argument("--tracker", default=f"http://{TRACKER_HOST}:{TRACKER_PORT}",
                        help="Tracker URL")
    parser.add_argument("--metadata", required=True, help="Path to .torrent.json")
    parser.add_argument("--seeder", action="store_true", help="Run as seeder")
    parser.add_argument("--file", help="Source file path (required if --seeder)")
    parser.add_argument("--output-dir", default="downloads",
                        help="Directory for downloaded/reconstructed files")

    args = parser.parse_args()

    # TODO: All members — implement the main peer loop
    # This is the integration hub that connects all modules.
    #
    # Pseudocode:
    # 1. metadata = load_metadata(args.metadata)
    # 2. state = PeerState(args.peer_id, args.port, metadata, is_seeder=args.seeder)
    # 3. if seeder: load pieces from file into state.pieces
    # 4. piece_picker = PiecePicker(metadata.num_pieces)
    # 5. request_manager = RequestManager()
    # 6. start_listener_socket(args.port)
    # 7. announce_to_tracker(args.tracker, state)
    # 8. peers = get_peers(args.tracker, args.peer_id)
    # 9. for peer in peers: connect and start PeerConnection
    # 10. main_loop: wait until complete or interrupted
    # 11. if complete: assemble_file(state.pieces, metadata, output_path)
    print(f"[{args.peer_id}] Peer not yet implemented")


if __name__ == "__main__":
    main()
