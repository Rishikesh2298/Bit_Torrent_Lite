import socket
import threading
import queue

from bittorrent_lite.peer.peer_state import PeerState
from bittorrent_lite.protocol.framing import send_message, recv_message
from bittorrent_lite.protocol.messages import (
    Message,
    Handshake,
    BitfieldMsg,
    Have,
    Interested,
    NotInterested,
    Choke,
    Unchoke,
    Request,
    Piece,
    Cancel,
    Reject,
)


class PeerConnection:
    """
    Manages one TCP connection to one remote peer.

    One sender thread performs all socket writes.
    One receiver thread performs all socket reads.

    Received messages are dispatched through callbacks.
    """

    def __init__(
        self,
        sock: socket.socket,
        peer_state: PeerState = None,
        callbacks: dict = None,
    ):
        self.sock = sock
        self.peer_state = peer_state
        self.callbacks = callbacks or {}

        self.remote_peer_id = ""

        self._outbound_queue = queue.Queue()

        self._running = False

        self._sender_thread = None
        self._receiver_thread = None

        self._lock = threading.Lock()
        self._disconnect_notified = False

        self._STOP = object()

    # =========================================================
    # START
    # =========================================================

    def start(self):
        """Start sender and receiver threads."""

        with self._lock:

            if self._running:
                return

            self._running = True

        self._sender_thread = threading.Thread(
            target=self._sender_loop,
            name="peer-sender",
            daemon=True,
        )

        self._receiver_thread = threading.Thread(
            target=self._receiver_loop,
            name="peer-receiver",
            daemon=True,
        )

        self._sender_thread.start()
        self._receiver_thread.start()

    # =========================================================
    # SEND
    # =========================================================

    def send(self, message: Message):
        """
        Queue a message for transmission.

        Only the sender thread writes to the socket.
        """

        if not isinstance(message, Message):
            raise TypeError(
                "message must be a Message instance"
            )

        with self._lock:

            if not self._running:
                raise ConnectionError(
                    "PeerConnection is not running"
                )

        self._outbound_queue.put(message)

    # =========================================================
    # CLOSE
    # =========================================================

    def close(self):
        """Close the TCP connection and stop worker threads."""

        with self._lock:

            was_running = self._running

            self._running = False

        if not was_running:
            return

        # Wake sender thread.
        self._outbound_queue.put(self._STOP)

        # Wake receiver thread.
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

        try:
            self.sock.close()
        except OSError:
            pass

        current_thread = threading.current_thread()

        if (
            self._sender_thread is not None
            and self._sender_thread is not current_thread
        ):
            self._sender_thread.join(timeout=1.0)

        if (
            self._receiver_thread is not None
            and self._receiver_thread is not current_thread
        ):
            self._receiver_thread.join(timeout=1.0)

        self._notify_disconnect()

    # =========================================================
    # SENDER LOOP
    # =========================================================

    def _sender_loop(self):

        while True:

            try:
                message = self._outbound_queue.get()

            except Exception:
                break

            if message is self._STOP:
                break

            with self._lock:

                if not self._running:
                    break

            try:

                send_message(
                    self.sock,
                    message,
                )

            except (
                OSError,
                ConnectionError,
                ValueError,
                TypeError,
            ):

                self._handle_connection_failure()

                break

    # =========================================================
    # RECEIVER LOOP
    # =========================================================

    def _receiver_loop(self):

        while True:

            with self._lock:

                if not self._running:
                    break

            try:

                message = recv_message(self.sock)

                # Clean remote shutdown.
                if message is None:

                    self._handle_connection_failure()

                    break

                self._dispatch_message(message)

            except (
                OSError,
                ConnectionError,
                ValueError,
                TypeError,
            ):

                self._handle_connection_failure()

                break

            except Exception:

                self._handle_connection_failure()

                break

    # =========================================================
    # DISPATCH MESSAGE
    # =========================================================

    def _dispatch_message(self, message: Message):

        # -----------------------------------------------------
        # HANDSHAKE
        # -----------------------------------------------------

        if isinstance(message, Handshake):

            self.remote_peer_id = message.peer_id

        # -----------------------------------------------------
        # CALLBACK
        # -----------------------------------------------------

        callback_name = self._callback_name_for_message(
            message
        )

        if callback_name is None:
            return

        callback = self.callbacks.get(callback_name)

        if callback is None:
            return

        try:

            callback(message)

        except TypeError:

            # Also support callbacks written as:
            # callback(connection, message)

            callback(
                self,
                message,
            )

    # =========================================================
    # MESSAGE → CALLBACK
    # =========================================================

    def _callback_name_for_message(
        self,
        message: Message,
    ):

        if isinstance(message, Handshake):
            return "on_handshake"

        if isinstance(message, BitfieldMsg):
            return "on_bitfield"

        if isinstance(message, Have):
            return "on_have"

        if isinstance(message, Interested):
            return "on_interested"

        if isinstance(message, NotInterested):
            return "on_not_interested"

        if isinstance(message, Choke):
            return "on_choke"

        if isinstance(message, Unchoke):
            return "on_unchoke"

        if isinstance(message, Request):
            return "on_request"

        if isinstance(message, Piece):
            return "on_piece"

        if isinstance(message, Cancel):
            return "on_cancel"

        if isinstance(message, Reject):
            return "on_reject"

        return None

    # =========================================================
    # CONNECTION FAILURE
    # =========================================================

    def _handle_connection_failure(self):

        with self._lock:

            was_running = self._running

            self._running = False

        if not was_running:
            return

        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

        try:
            self.sock.close()
        except OSError:
            pass

        self._outbound_queue.put(self._STOP)

        self._notify_disconnect()

    # =========================================================
    # DISCONNECT CALLBACK
    # =========================================================

    def _notify_disconnect(self):

        with self._lock:

            if self._disconnect_notified:
                return

            self._disconnect_notified = True

        callback = self.callbacks.get(
            "on_disconnect"
        )

        if callback is None:
            return

        try:

            callback(self)

        except TypeError:

            callback()