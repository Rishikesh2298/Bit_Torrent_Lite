"""
Peer connection implementation for BitTorrent-Lite.

Responsibilities
----------------
- Manage one TCP connection to one peer.
- Send and receive protocol messages.
- Maintain reader/writer threads.
- Perform the optional handshake.
- Maintain connection lifecycle state.
- Dispatch messages to callbacks.
- Maintain bitfield/HAVE state.
- Handle request/piece messages.
- Integrate RequestManager and PieceHandler.
- Handle choke/unchoke state.
- Detect remote connection closure.
- Enforce handshake-before-normal-message rules.
"""

from __future__ import annotations

import queue
import socket
import threading
import time
from typing import Any, Callable, Optional

from bittorrent_lite.networking.framing import recv_message
from bittorrent_lite.networking.framing import send_message

from bittorrent_lite.networking.messages import BitfieldMsg
from bittorrent_lite.networking.messages import Cancel
from bittorrent_lite.networking.messages import Choke
from bittorrent_lite.networking.messages import Handshake
from bittorrent_lite.networking.messages import Have
from bittorrent_lite.networking.messages import Interested
from bittorrent_lite.networking.messages import Message
from bittorrent_lite.networking.messages import NotInterested
from bittorrent_lite.networking.messages import Piece
from bittorrent_lite.networking.messages import Reject
from bittorrent_lite.networking.messages import Request
from bittorrent_lite.networking.messages import Unchoke

try:
    from bittorrent_lite.scheduling.legacy.request_manager import RequestManager
except ImportError:
    RequestManager = Any


Callback = Callable[..., Any]


class PeerConnection:
    """
    Represents one TCP connection between two BitTorrent-Lite peers.
    """

    def __init__(
        self,
        sock: socket.socket,
        callbacks: Optional[dict[str, Callback]] = None,
        *,
        on_message: Optional[Callback] = None,
        on_disconnect: Optional[Callback] = None,
        on_handshake: Optional[Callback] = None,
        on_bitfield: Optional[Callback] = None,
        on_have: Optional[Callback] = None,
        on_interested: Optional[Callback] = None,
        on_not_interested: Optional[Callback] = None,
        on_choke: Optional[Callback] = None,
        on_unchoke: Optional[Callback] = None,
        on_request: Optional[Callback] = None,
        on_piece: Optional[Callback] = None,
        on_piece_received: Optional[Callback] = None,
        on_cancel: Optional[Callback] = None,
        on_reject: Optional[Callback] = None,
        piece_handler: Any = None,
        local_handshake: Optional[Handshake] = None,
        expected_file_id: Optional[str] = None,
        expected_protocol_version: Any = None,
        require_handshake: bool = False,
        request_manager: Optional[RequestManager] = None,
        peer_id: Optional[str] = None,
        local_bitfield: Optional[list[int]] = None,
    ) -> None:

        self.sock = sock

        self.callbacks: dict[str, Callback] = (
            dict(callbacks)
            if callbacks is not None
            else {}
        )

        explicit_callbacks = {
            "on_message": on_message,
            "on_disconnect": on_disconnect,
            "on_handshake": on_handshake,
            "on_bitfield": on_bitfield,
            "on_have": on_have,
            "on_interested": on_interested,
            "on_not_interested": on_not_interested,
            "on_choke": on_choke,
            "on_unchoke": on_unchoke,
            "on_request": on_request,
            "on_piece": on_piece,
            "on_piece_received": on_piece_received,
            "on_cancel": on_cancel,
            "on_reject": on_reject,
        }

        for name, callback in explicit_callbacks.items():
            if callback is not None:
                self.callbacks[name] = callback

        self.piece_handler = piece_handler

        self.local_handshake = local_handshake

        self.expected_file_id = expected_file_id

        self.expected_protocol_version = (
            expected_protocol_version
        )

        self.require_handshake = bool(
            require_handshake
        )

        self.request_manager = (
            request_manager
            if request_manager is not None
            else self._make_default_request_manager()
        )

        self.peer_id = peer_id

        self.remote_peer_id: Optional[str] = None

        # ---------------------------------------------------------
        # Connection state
        # ---------------------------------------------------------

        self._state_lock = threading.RLock()

        self._running = False

        self._closed = False

        self._disconnect_notified = False

        # ---------------------------------------------------------
        # Handshake state
        # ---------------------------------------------------------

        self.handshake_complete = False

        self._handshake_sent = False

        self._handshake_received = False

        # ---------------------------------------------------------
        # Choking state
        # ---------------------------------------------------------

        self._remote_choked = True

        self._local_choking = True

        self._local_choke_enforced = False

        # ---------------------------------------------------------
        # Bitfield state
        # ---------------------------------------------------------

        self.local_bitfield = (
            list(local_bitfield)
            if local_bitfield is not None
            else None
        )

        self.bitfield_sent = False

        self.bitfield_received = False

        self.remote_bitfield: Optional[list[int]] = None

        # ---------------------------------------------------------
        # Threads
        # ---------------------------------------------------------

        self._reader_thread: Optional[
            threading.Thread
        ] = None

        self._writer_thread: Optional[
            threading.Thread
        ] = None

        self._writer_queue: queue.Queue[
            Optional[Message]
        ] = queue.Queue()

        # ---------------------------------------------------------
        # Socket configuration
        # ---------------------------------------------------------

        try:
            self.sock.settimeout(0.2)
        except (
            OSError,
            AttributeError,
        ):
            pass

    # ============================================================
    # Request manager
    # ============================================================

    def _make_default_request_manager(self):

        try:
            return RequestManager()

        except Exception:
            return None

    # ============================================================
    # Properties
    # ============================================================

    @property
    def running(self) -> bool:

        with self._state_lock:
            return self._running

    @property
    def closed(self) -> bool:

        with self._state_lock:
            return self._closed

    @property
    def handshake_sent(self) -> bool:

        with self._state_lock:
            return self._handshake_sent

    @property
    def handshake_received(self) -> bool:

        with self._state_lock:
            return self._handshake_received

    @property
    def remote_choked(self) -> bool:

        with self._state_lock:
            return self._remote_choked

    @property
    def local_choking(self) -> bool:

        with self._state_lock:
            return self._local_choking

    # ============================================================
    # Callback helper
    # ============================================================

    @staticmethod
    def _invoke_callback(
        callback: Optional[Callback],
        *args: Any,
    ) -> None:

        if callback is None:
            return

        attempts = []

        if args:
            attempts.append(args)

        if len(args) >= 1:
            attempts.append((args[-1],))

        attempts.append(())

        last_error: Optional[TypeError] = None

        for callback_args in attempts:

            try:

                callback(*callback_args)

                return

            except TypeError as exc:

                last_error = exc

        if last_error is not None:
            raise last_error

    def _callback(
        self,
        name: str,
    ) -> Optional[Callback]:

        return self.callbacks.get(name)

    # ============================================================
    # Start
    # ============================================================

    def start(self) -> "PeerConnection":

        with self._state_lock:

            if self._closed:

                raise RuntimeError(
                    "Cannot start a closed PeerConnection"
                )

            if self._running:
                return self

            self._running = True

        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            name="bittorrent-peer-writer",
            daemon=True,
        )

        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name="bittorrent-peer-reader",
            daemon=True,
        )

        self._writer_thread.start()

        self._reader_thread.start()

        if self.local_handshake is not None:

            try:

                self.send_handshake()

            except (
                ConnectionError,
                OSError,
            ):

                self.close()

        return self

    # ============================================================
    # Writer loop
    # ============================================================

    def _writer_loop(self) -> None:

        while True:

            try:

                message = (
                    self._writer_queue.get(
                        timeout=0.2
                    )
                )

            except queue.Empty:

                with self._state_lock:

                    if (
                        not self._running
                        and self._writer_queue.empty()
                    ):
                        break

                continue

            if message is None:

                with self._state_lock:

                    if not self._running:
                        break

                continue

            try:

                send_message(
                    self.sock,
                    message,
                )

            except (
                OSError,
                ConnectionError,
                EOFError,
            ):

                self._handle_transport_failure()

                break

    # ============================================================
    # Reader loop
    # ============================================================

    def _reader_loop(self) -> None:

        try:

            while True:

                with self._state_lock:

                    if (
                        not self._running
                        or self._closed
                    ):
                        break

                try:

                    message = recv_message(
                        self.sock
                    )

                except socket.timeout:

                    continue

                except (
                    EOFError,
                    ConnectionError,
                    OSError,
                    ValueError,
                ):

                    break

                # ------------------------------------------------
                # Remote peer closed the connection cleanly.
                # recv_message() returns None in this situation.
                # ------------------------------------------------

                if message is None:
                    break

                try:

                    self._dispatch_message(
                        message
                    )

                except (
                    ValueError,
                    TypeError,
                    RuntimeError,
                    ConnectionError,
                ):

                    break

        finally:

            # Framing validation and remote EOF must release the transport,
            # not only mark it disconnected and leave its socket open.
            self.close()

    # ============================================================
    # Transport failure
    # ============================================================

    def _handle_transport_failure(
        self,
    ) -> None:

        self.close()

    # ============================================================
    # Send
    # ============================================================

    def send(
        self,
        message: Message,
    ) -> None:
        """
        Send a protocol message.

        If the connection has not been started, sending is
        synchronous.

        If the connection has been started, sending is queued
        for the writer thread.

        When require_handshake=True, only the Handshake message
        itself may be sent before the handshake is complete.
        """

        if message is None:

            raise ValueError(
                "Cannot send None as a protocol message"
            )

        # --------------------------------------------------------
        # IMPORTANT HANDSHAKE ENFORCEMENT
        # --------------------------------------------------------
        #
        # A handshake is the only legal protocol message before
        # handshake completion when require_handshake=True.
        #
        # We explicitly allow Handshake here because
        # send_handshake() itself eventually calls send().
        # --------------------------------------------------------

        if (
            self.require_handshake
            and not isinstance(
                message,
                Handshake,
            )
        ):

            with self._state_lock:

                handshake_complete = (
                    self.handshake_complete
                )

            if not handshake_complete:

                raise ConnectionError(
                    "Cannot send normal message "
                    "before handshake is complete"
                )

        with self._state_lock:

            if self._closed:

                raise ConnectionError(
                    "PeerConnection is closed"
                )

            running = self._running

        # --------------------------------------------------------
        # Synchronous send before start()
        # --------------------------------------------------------

        if not running:

            send_message(
                self.sock,
                message,
            )

            return

        # --------------------------------------------------------
        # Asynchronous send after start()
        # --------------------------------------------------------

        self._writer_queue.put(
            message
        )

    # ============================================================
    # Handshake
    # ============================================================

    def send_handshake(
        self,
        handshake: Optional[Handshake] = None,
    ) -> bool:
        """
        Send the local handshake exactly once.

        Returns:
            True  if the handshake was sent now.
            False if it had already been sent.
        """

        if handshake is None:

            handshake = self.local_handshake

        if handshake is None:

            raise ValueError(
                "No local handshake configured"
            )

        with self._state_lock:

            if self._handshake_sent:

                return False

            # Mark it before sending so another thread cannot
            # send a duplicate handshake.
            self._handshake_sent = True

        try:

            self.send(
                handshake
            )

        except Exception:

            with self._state_lock:

                self._handshake_sent = False

            raise

        self._update_handshake_complete()

        return True

    def _handle_handshake(
        self,
        message: Handshake,
    ) -> None:

        self._validate_handshake(
            message
        )

        with self._state_lock:

            self._handshake_received = True

            self.remote_peer_id = (
                message.peer_id
            )

        callback = self._callback(
            "on_handshake"
        )

        self._invoke_callback(
            callback,
            self,
            message,
        )

        # If the remote side initiated the handshake,
        # send our handshake in response.
        if self.local_handshake is not None:

            with self._state_lock:

                already_sent = (
                    self._handshake_sent
                )

            if not already_sent:

                self.send_handshake()

        self._update_handshake_complete()

    def _validate_handshake(
        self,
        handshake: Handshake,
    ) -> None:

        if (
            self.expected_protocol_version
            is not None
        ):

            received_version = (
                handshake.protocol_version
            )

            expected_version = (
                self.expected_protocol_version
            )

            if (
                received_version
                != expected_version
            ):

                if str(
                    received_version
                ) != str(
                    expected_version
                ):

                    raise ValueError(
                        "Protocol version mismatch"
                    )

        if (
            self.expected_file_id
            is not None
            and handshake.file_id
            != self.expected_file_id
        ):

            raise ValueError(
                "File ID mismatch"
            )

    def _update_handshake_complete(
        self,
    ) -> None:

        with self._state_lock:

            complete = (
                self._handshake_sent
                and self._handshake_received
            )

            self.handshake_complete = (
                complete
            )

        if complete:

            self._send_local_bitfield_if_needed()

    # ============================================================
    # Bitfield
    # ============================================================

    def _send_local_bitfield_if_needed(
        self,
    ) -> None:

        if self.local_bitfield is None:
            return

        if self.bitfield_sent:
            return

        self.send_bitfield(
            self.local_bitfield
        )

    def send_bitfield(
        self,
        pieces: Optional[list[int]] = None,
    ) -> None:

        if pieces is None:

            pieces = self.local_bitfield

        if pieces is None:

            raise ValueError(
                "Bitfield pieces are required"
            )

        message = BitfieldMsg(
            list(pieces)
        )

        self.send(
            message
        )

        self.bitfield_sent = True

    def _handle_bitfield(
        self,
        message: BitfieldMsg,
    ) -> None:

        self.remote_bitfield = list(
            message.pieces
        )

        self.bitfield_received = True

        callback = self._callback(
            "on_bitfield"
        )

        self._invoke_callback(
            callback,
            self,
            message,
        )

    # ============================================================
    # HAVE
    # ============================================================

    def send_have(
        self,
        piece_index: int,
    ) -> None:

        self.send(
            Have(piece_index)
        )

    def _handle_have(
        self,
        message: Have,
    ) -> None:

        if self.remote_bitfield is not None:

            index = message.piece_index

            if index >= 0:

                while len(
                    self.remote_bitfield
                ) <= index:

                    self.remote_bitfield.append(
                        0
                    )

                self.remote_bitfield[
                    index
                ] = 1

        callback = self._callback(
            "on_have"
        )

        self._invoke_callback(
            callback,
            self,
            message,
        )

    # ============================================================
    # Interested / Not Interested
    # ============================================================

    def send_interested(
        self,
    ) -> None:

        self.send(
            Interested()
        )

    def send_not_interested(
        self,
    ) -> None:

        self.send(
            NotInterested()
        )

    def _handle_interested(
        self,
        message: Interested,
    ) -> None:

        callback = self._callback(
            "on_interested"
        )

        self._invoke_callback(
            callback,
            self,
            message,
        )

    def _handle_not_interested(
        self,
        message: NotInterested,
    ) -> None:

        callback = self._callback(
            "on_not_interested"
        )

        self._invoke_callback(
            callback,
            self,
            message,
        )

    # ============================================================
    # Choke / Unchoke
    # ============================================================

    def send_choke(
        self,
    ) -> None:

        with self._state_lock:

            self._local_choking = True

            self._local_choke_enforced = True

        self.send(
            Choke()
        )

    def send_unchoke(
        self,
    ) -> None:

        with self._state_lock:

            self._local_choking = False

            self._local_choke_enforced = False

        self.send(
            Unchoke()
        )

    def _handle_choke(
        self,
        message: Choke,
    ) -> None:

        with self._state_lock:

            self._remote_choked = True

        callback = self._callback(
            "on_choke"
        )

        self._invoke_callback(
            callback,
            self,
            message,
        )

    def _handle_unchoke(
        self,
        message: Unchoke,
    ) -> None:

        with self._state_lock:

            self._remote_choked = False

        callback = self._callback(
            "on_unchoke"
        )

        self._invoke_callback(
            callback,
            self,
            message,
        )

    # ============================================================
    # Request
    # ============================================================

    def send_request(
        self,
        piece_index: int,
    ) -> Optional[Request]:

        with self._state_lock:

            if self._remote_choked:

                return None

        request = self._create_request(
            piece_index
        )

        if request is None:

            return None

        self.send(
            request
        )

        return request

    def _create_request(
        self,
        piece_index: int,
    ) -> Optional[Request]:

        manager = self.request_manager

        if manager is None:

            return Request(
                request_id=int(
                    time.time_ns()
                    & 0x7FFFFFFF
                ),
                piece_index=piece_index,
            )

        for method_name in (
            "create_request",
            "make_request",
            "request",
        ):

            method = getattr(
                manager,
                method_name,
                None,
            )

            if method is None:
                continue

            try:

                result = method(
                    piece_index
                )

                if isinstance(
                    result,
                    Request,
                ):

                    return result

                if isinstance(
                    result,
                    int,
                ):

                    return Request(
                        request_id=result,
                        piece_index=piece_index,
                    )

            except TypeError:

                continue

        return Request(
            request_id=int(
                time.time_ns()
                & 0x7FFFFFFF
            ),
            piece_index=piece_index,
        )

    def _handle_request(
        self,
        message: Request,
    ) -> None:

        callback = self._callback(
            "on_request"
        )

        self._invoke_callback(
            callback,
            self,
            message,
        )

        with self._state_lock:

            locally_choked = (
                self._local_choke_enforced
            )

        if locally_choked:

            try:

                self.send(
                    Reject(
                        message.request_id,
                        message.piece_index,
                        "choked",
                    )
                )

            except Exception:
                pass

            return

        if self.piece_handler is None:

            return

        try:

            piece = (
                self.piece_handler.handle_request(
                    message
                )
            )

            if piece is not None:

                self.send(
                    piece
                )

        except Exception:

            try:

                self.send(
                    Reject(
                        message.request_id,
                        message.piece_index,
                        "request_failed",
                    )
                )

            except Exception:
                pass

    # ============================================================
    # PIECE
    # ============================================================

    def _handle_piece(
        self,
        message: Piece,
    ) -> None:

        self._complete_request(
            message
        )

        if self.piece_handler is not None:

            try:

                self.piece_handler.handle_piece(
                    message
                )

            except Exception:
                pass

        callback = self._callback(
            "on_piece"
        )

        self._invoke_callback(
            callback,
            self,
            message,
        )

        callback = self._callback(
            "on_piece_received"
        )

        self._invoke_callback(
            callback,
            self,
            message,
        )

    def _complete_request(
        self,
        message: Piece,
    ) -> None:

        manager = self.request_manager

        if manager is None:
            return

        for method_name in (
            "complete_request",
            "mark_complete",
            "complete",
            "receive_piece",
        ):

            method = getattr(
                manager,
                method_name,
                None,
            )

            if method is None:
                continue

            try:

                method(
                    message.request_id
                )

                return

            except TypeError:

                try:

                    method(
                        message
                    )

                    return

                except (
                    TypeError,
                    KeyError,
                ):

                    continue

    # ============================================================
    # CANCEL
    # ============================================================

    def send_cancel(
        self,
        request_id: int,
        piece_index: int,
    ) -> None:

        self.send(
            Cancel(
                request_id,
                piece_index,
            )
        )

    def _handle_cancel(
        self,
        message: Cancel,
    ) -> None:

        manager = self.request_manager

        if manager is not None:

            for method_name in (
                "cancel_request",
                "cancel",
                "remove_request",
            ):

                method = getattr(
                    manager,
                    method_name,
                    None,
                )

                if method is None:
                    continue

                try:

                    method(
                        message.request_id
                    )

                    break

                except TypeError:

                    try:

                        method(
                            message
                        )

                        break

                    except TypeError:

                        continue

        callback = self._callback(
            "on_cancel"
        )

        self._invoke_callback(
            callback,
            self,
            message,
        )

    # ============================================================
    # REJECT
    # ============================================================

    def _handle_reject(
        self,
        message: Reject,
    ) -> None:

        manager = self.request_manager

        if manager is not None:

            for method_name in (
                "reject_request",
                "mark_rejected",
                "reject",
                "cancel_request",
            ):

                method = getattr(
                    manager,
                    method_name,
                    None,
                )

                if method is None:
                    continue

                try:

                    method(
                        message.request_id
                    )

                    break

                except TypeError:

                    try:

                        method(
                            message
                        )

                        break

                    except TypeError:

                        continue

        callback = self._callback(
            "on_reject"
        )

        self._invoke_callback(
            callback,
            self,
            message,
        )

    # ============================================================
    # Message dispatch
    # ============================================================

    def _dispatch_message(
        self,
        message: Message,
    ) -> None:

        if message is None:
            return

        # --------------------------------------------------------
        # Handshake is always allowed as the first message.
        # --------------------------------------------------------

        if isinstance(
            message,
            Handshake,
        ):

            self._handle_handshake(
                message
            )

            return

        # --------------------------------------------------------
        # Incoming messages also require a completed handshake.
        # --------------------------------------------------------

        if (
            self.require_handshake
            and not self.handshake_complete
        ):

            raise ConnectionError(
                "Protocol message received "
                "before handshake"
            )

        # --------------------------------------------------------
        # Bitfield
        # --------------------------------------------------------

        if isinstance(
            message,
            BitfieldMsg,
        ):

            self._handle_bitfield(
                message
            )

            return

        # --------------------------------------------------------
        # HAVE
        # --------------------------------------------------------

        if isinstance(
            message,
            Have,
        ):

            self._handle_have(
                message
            )

            return

        # --------------------------------------------------------
        # Interested
        # --------------------------------------------------------

        if isinstance(
            message,
            Interested,
        ):

            self._handle_interested(
                message
            )

            return

        # --------------------------------------------------------
        # Not Interested
        # --------------------------------------------------------

        if isinstance(
            message,
            NotInterested,
        ):

            self._handle_not_interested(
                message
            )

            return

        # --------------------------------------------------------
        # Choke
        # --------------------------------------------------------

        if isinstance(
            message,
            Choke,
        ):

            self._handle_choke(
                message
            )

            return

        # --------------------------------------------------------
        # Unchoke
        # --------------------------------------------------------

        if isinstance(
            message,
            Unchoke,
        ):

            self._handle_unchoke(
                message
            )

            return

        # --------------------------------------------------------
        # Request
        # --------------------------------------------------------

        if isinstance(
            message,
            Request,
        ):

            self._handle_request(
                message
            )

            return

        # --------------------------------------------------------
        # PIECE
        # --------------------------------------------------------

        if isinstance(
            message,
            Piece,
        ):

            self._handle_piece(
                message
            )

            return

        # --------------------------------------------------------
        # CANCEL
        # --------------------------------------------------------

        if isinstance(
            message,
            Cancel,
        ):

            self._handle_cancel(
                message
            )

            return

        # --------------------------------------------------------
        # REJECT
        # --------------------------------------------------------

        if isinstance(
            message,
            Reject,
        ):

            self._handle_reject(
                message
            )

            return

        # --------------------------------------------------------
        # Generic callback
        # --------------------------------------------------------

        callback = self._callback(
            "on_message"
        )

        self._invoke_callback(
            callback,
            self,
            message,
        )

    # ============================================================
    # Disconnect notification
    # ============================================================

    def _notify_disconnect(
        self,
        reason: Optional[Any] = None,
    ) -> None:

        with self._state_lock:

            if self._disconnect_notified:
                return

            self._disconnect_notified = True

            self._running = False

            self._closed = True

        callback = self._callback(
            "on_disconnect"
        )

        try:

            self._invoke_callback(
                callback,
                self,
                reason,
            )

        except Exception:
            pass

    # ============================================================
    # Close
    # ============================================================

    def close(
        self,
    ) -> None:

        with self._state_lock:

            if self._closed:

                already_closed = True

            else:

                already_closed = False

                self._closed = True

                self._running = False

        if already_closed:

            self._notify_disconnect()

            return

        try:

            self._writer_queue.put_nowait(
                None
            )

        except Exception:
            pass

        try:

            self.sock.shutdown(
                socket.SHUT_RDWR
            )

        except (
            OSError,
            AttributeError,
        ):
            pass

        try:

            self.sock.close()

        except OSError:
            pass

        self._notify_disconnect()

    # ============================================================
    # Join
    # ============================================================

    def join(
        self,
        timeout: Optional[float] = None,
    ) -> None:

        current = (
            threading.current_thread()
        )

        threads = (
            self._reader_thread,
            self._writer_thread,
        )

        start_time = time.monotonic()

        for thread in threads:

            if thread is None:
                continue

            if thread is current:
                continue

            remaining = timeout

            if timeout is not None:

                elapsed = (
                    time.monotonic()
                    - start_time
                )

                remaining = max(
                    0.0,
                    timeout - elapsed,
                )

            thread.join(
                remaining
            )

    # ============================================================
    # Wait for disconnect
    # ============================================================

    def wait_for_disconnect(
        self,
        timeout: Optional[float] = None,
    ) -> bool:

        start_time = time.monotonic()

        while True:

            with self._state_lock:

                if self._closed:
                    return True

            if timeout is not None:

                elapsed = (
                    time.monotonic()
                    - start_time
                )

                if elapsed >= timeout:

                    return False

            time.sleep(
                0.01
            )

    # ============================================================
    # Context manager
    # ============================================================

    def __enter__(
        self,
    ) -> "PeerConnection":

        self.start()

        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ) -> None:

        self.close()

    # ============================================================
    # Representation
    # ============================================================

    def __repr__(
        self,
    ) -> str:

        return (
            f"PeerConnection("
            f"peer_id={self.remote_peer_id!r}, "
            f"running={self.running}, "
            f"closed={self.closed}, "
            f"handshake_complete="
            f"{self.handshake_complete}"
            f")"
        )
