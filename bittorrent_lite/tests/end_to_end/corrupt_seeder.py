"""Test-only separate-process seeder: corrupt payload at the real send boundary.

Source validation, upload policy, framing, socket I/O and the downloader remain
the production implementations. The original plans explicitly request this
uploader-side fault hook. It is never enabled by the normal peer entrypoint.
"""
import argparse
import hashlib
from pathlib import Path
import threading

from bittorrent_lite.acceptance_tools.faults import FaultTrace, corrupt_byte
from bittorrent_lite.application.cli import build_parser, main as peer_main
from bittorrent_lite.networking import messages as messages
from bittorrent_lite.networking import runtime_connection


def corrupting_sender(original_send, trace):
    def send(sock, message):
        if not isinstance(message, messages.Piece):
            return original_send(sock, message)
        # Mutate after the uploader's source/hash checks. Keep the actual
        # request ID, index, length and metadata; alter exactly one payload byte.
        changed = corrupt_byte(message.payload, 0, 1)
        outgoing = messages.Piece(message.request_id, message.piece_index, changed)
        trace.emit('payload_corruption_planned', request_id=message.request_id,
                   piece=message.piece_index, offset=0, xor_mask=1,
                   original_sha256=hashlib.sha256(message.payload).hexdigest())
        original_send(sock, outgoing)
        # This row follows a successful real sendall, not a planned send.
        trace.bytes('corrupt_payload_sent', changed, request_id=message.request_id,
                    piece=message.piece_index, offset=0, xor_mask=1,
                    original_sha256=hashlib.sha256(message.payload).hexdigest())
    return send


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--fault-trace', type=Path, required=True)
    options, peer_argv = parser.parse_known_args(argv)
    peer_options = build_parser().parse_args(peer_argv)
    if not peer_options.seeder or not peer_options.file or not peer_options.stop_file:
        parser.error('test fault requires a seeder source and an owned stop file')
    stop = Path(peer_options.stop_file).resolve()
    if stop.exists() or stop.parent != options.fault_trace.resolve().parent:
        parser.error('stop file must be initially absent beside the fresh fault trace')
    expired = threading.Event()
    with FaultTrace(options.fault_trace, 'original-plan-live-corruption') as trace:
        def expire():
            expired.set()
            trace.emit('fault_process_deadline', limit_s=120)
            stop.touch(exist_ok=True)
        watchdog = threading.Timer(120, expire)
        watchdog.daemon = True
        original_send = runtime_connection.send_message
        runtime_connection.send_message = corrupting_sender(original_send, trace)
        watchdog.start()
        try:
            code = peer_main(peer_argv)
        finally:
            watchdog.cancel()
            watchdog.join(2)
            runtime_connection.send_message = original_send
        return 3 if expired.is_set() else code


if __name__ == '__main__':
    raise SystemExit(main())
