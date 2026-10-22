import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from examples.scheduler_dependencies import InMemoryStore, ManualClock, RecordingTransport, make_file

from bittorrent_lite.scheduler import Coordinator, SchedulerConfig
from bittorrent_lite.scheduler.events import (
    BitfieldReceived,
    ConnectionReady,
    PieceReceived,
    RequestSent,
    UnchokeReceived,
)

NUM_PIECES = 4
PIECE_SIZE = 16


def show(title, transport):
    print(f"\n== {title}")
    for msg in transport.drain():
        print("   out:", msg)


def main():
    pieces, hashes = make_file(NUM_PIECES, PIECE_SIZE)
    clock = ManualClock()
    transport = RecordingTransport()
    store = InMemoryStore(hashes, PIECE_SIZE)
    sched = Coordinator(
        NUM_PIECES, transport, store, clock, SchedulerConfig(request_window=1), rng=random.Random(7)
    )

    sched.handle_event(ConnectionReady(connection_id=1, peer_id="peer-A"))
    show("1. neighbor registered", transport)

    sched.handle_event(BitfieldReceived(1, [True, True, True, False]))
    show("2a. bitfield received (interest is announced, still choked)", transport)

    sched.handle_event(UnchokeReceived(1))
    show("2b/3. unchoked: one request enqueued", transport)
    req = sched.snapshot()["pending"][0]
    print("   pending:", req)

    clock.advance(0.1)
    sched.handle_event(RequestSent(1, req["request_id"], req["piece_index"], clock.now()))
    print("\n== 4. send confirmed")
    print("   pending:", sched.snapshot()["pending"][0])

    clock.advance(0.5)
    sched.handle_event(
        PieceReceived(1, req["request_id"], req["piece_index"], pieces[req["piece_index"]])
    )
    show("5-7. piece verified and stored, HAVE advertised, next request enqueued", transport)

    snap = sched.snapshot()
    print("   owned:", snap["owned"], "/", snap["total"], "states:", snap["piece_states"])
    print("   pending:", snap["pending"])


if __name__ == "__main__":
    main()
