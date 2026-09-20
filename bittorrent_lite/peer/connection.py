"""
Peer Connection — Anik's Module

Manages a single TCP connection to one remote peer.

Architecture:
    Each PeerConnection spawns two threads:
    - Receiver thread: continuously reads framed messages, dispatches to callbacks
    - Sender thread: pulls messages from an outbound queue, sends them

    This design avoids blocking the main thread and allows concurrent
    send/receive on the same socket.

                    ┌────────────────────┐
                    │   PeerConnection   │
                    │                    │
    send(msg) ──────► outbound_queue     │
                    │     │              │
                    │     ▼              │
                    │  sender_thread ────────► socket.sendall()
                    │                    │
    socket.recv() ──► receiver_thread    │
                    │     │              │
                    │     ▼              │
                    │  callback dispatch │
                    └────────────────────┘

Callbacks:
    The peer_main module registers callback functions for each message type.
    When the receiver thread gets a HAVE message, it calls callbacks["on_have"](conn, msg).
    This keeps connection.py decoupled from piece management logic.

Lifecycle:
    1. PeerConnection is created with an already-connected socket
    2. start() launches sender + receiver threads
    3. send(msg) enqueues messages for transmission
    4. Receiver thread dispatches incoming messages to callbacks
    5. close() shuts down both threads and the socket
"""

import socket
import threading
import queue
from typing import Callable

from bittorrent_lite.peer.peer_state import PeerState


class PeerConnection:
    """
    Manages bidirectional communication with one remote peer.

    Attributes:
        sock: The TCP socket for this connection.
        remote_peer_id: The connected peer's identifier (set after handshake).
        peer_state: Reference to the local peer's shared state.
        callbacks: Dict of message-type -> handler functions.
        _outbound_queue: Thread-safe queue for outgoing messages.
        _running: Flag to signal threads to stop.
    """

    def __init__(self, sock: socket.socket, peer_state: PeerState,
                 callbacks: dict[str, Callable]):
        """
        Initialize a peer connection.

        Args:
            sock: Connected TCP socket.
            peer_state: Shared state for this peer.
            callbacks: Dict mapping event names to handler functions.
                Expected keys: "on_handshake", "on_bitfield", "on_have",
                "on_interested", "on_not_interested", "on_request",
                "on_piece", "on_cancel", "on_choke", "on_unchoke",
                "on_disconnect"
        """
        self.sock = sock
        self.remote_peer_id: str = ""
        self.peer_state = peer_state
        self.callbacks = callbacks
        self._outbound_queue: queue.Queue = queue.Queue()
        self._running = False

    def start(self) -> None:
        """
        Launch sender and receiver threads.

        Both threads run as daemon threads so they don't prevent
        the process from exiting.
        """
        # TODO: Anik — implement this
        raise NotImplementedError

    def send(self, message) -> None:
        """
        Enqueue a message for sending to the remote peer.

        Args:
            message: A Message instance to send.
        """
        # TODO: Anik — implement this
        raise NotImplementedError

    def close(self) -> None:
        """
        Shut down the connection gracefully.

        1. Set _running = False
        2. Close the socket
        3. Threads will exit on their next iteration
        """
        # TODO: Anik — implement this
        raise NotImplementedError

    def _sender_loop(self) -> None:
        """
        Thread target: continuously pull messages from the outbound queue
        and send them through the socket using framing.send_message().
        """
        # TODO: Anik — implement this
        raise NotImplementedError

    def _receiver_loop(self) -> None:
        """
        Thread target: continuously read framed messages from the socket
        and dispatch them to the appropriate callback.
        """
        # TODO: Anik — implement this
        raise NotImplementedError
