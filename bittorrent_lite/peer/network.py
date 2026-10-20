"""
Peer networking layer for BitTorrent-Lite.

Responsibilities:
- Create and manage the TCP listening socket.
- Accept incoming peer connections.
- Create outgoing TCP connections.
- Track active PeerConnection objects.
- Forward callbacks between PeerNetwork and PeerConnection.
- Remove disconnected connections.
- Configure local handshake and bitfield state.
"""

from __future__ import annotations

import socket
import threading
from typing import Any, Callable, Optional

from bittorrent_lite.peer.connection import PeerConnection


Callback = Callable[..., Any]


class PeerNetwork:
    """
    TCP networking manager for BitTorrent-Lite.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        *,
        callbacks: Optional[dict[str, Callback]] = None,
        on_connection: Optional[Callback] = None,
        on_peer_connected: Optional[Callback] = None,
        on_disconnect: Optional[Callback] = None,
        on_message: Optional[Callback] = None,
        piece_handler: Any = None,
        local_handshake: Any = None,
        expected_file_id: Optional[str] = None,
        expected_protocol_version: Any = None,
        require_handshake: bool = False,
        local_bitfield: Optional[list[int]] = None,
        connection_factory: Optional[
            Callable[..., PeerConnection]
        ] = None,
    ) -> None:

        self.host = host
        self.port = port

        self.server_socket: Optional[
            socket.socket
        ] = None

        self._accept_thread: Optional[
            threading.Thread
        ] = None

        self._running = False
        self._lock = threading.RLock()

        self.connections: list[
            PeerConnection
        ] = []

        self.connection_set: set[
            PeerConnection
        ] = set()

        self.callbacks = (
            callbacks
            if callbacks is not None
            else {}
        )

        self.on_connection = on_connection
        self.on_peer_connected = (
            on_peer_connected
        )
        self.on_disconnect = on_disconnect
        self.on_message = on_message

        self.piece_handler = piece_handler

        self.local_handshake = (
            local_handshake
        )

        self.expected_file_id = (
            expected_file_id
        )

        self.expected_protocol_version = (
            expected_protocol_version
        )

        self.require_handshake = (
            require_handshake
        )

        self.local_bitfield = (
            list(local_bitfield)
            if local_bitfield is not None
            else None
        )

        self.connection_factory = (
            connection_factory
        )

    # ---------------------------------------------------------
    # Properties
    # ---------------------------------------------------------

    @property
    def address(self) -> tuple[str, int]:
        if self.server_socket is not None:
            try:
                host, port = (
                    self.server_socket.getsockname()[:2]
                )

                return str(host), int(port)

            except OSError:
                pass

        return self.host, self.port

    @property
    def server_address(self) -> tuple[str, int]:
        return self.address

    @property
    def bound_port(self) -> int:
        return self.address[1]

    @property
    def connection_count(self) -> int:
        with self._lock:
            return len(self.connections)

    @property
    def running(self) -> bool:
        return self._running

    # ---------------------------------------------------------
    # Start / stop
    # ---------------------------------------------------------

    def start(self) -> "PeerNetwork":

        with self._lock:

            if self._running:
                return self

            server = socket.socket(
                socket.AF_INET,
                socket.SOCK_STREAM,
            )

            server.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_REUSEADDR,
                1,
            )

            server.bind(
                (
                    self.host,
                    self.port,
                )
            )

            server.listen()
            server.settimeout(0.5)

            self.server_socket = server

            self.port = int(
                server.getsockname()[1]
            )

            self._running = True

            self._accept_thread = (
                threading.Thread(
                    target=self._accept_loop,
                    name="bittorrent-accept",
                    daemon=True,
                )
            )

            self._accept_thread.start()

        return self

    def stop(self) -> None:

        with self._lock:

            if (
                not self._running
                and self.server_socket is None
            ):
                return

            self._running = False

            server = self.server_socket

            self.server_socket = None

            connections = list(
                self.connections
            )

        if server is not None:

            try:
                server.shutdown(
                    socket.SHUT_RDWR
                )
            except OSError:
                pass

            try:
                server.close()
            except OSError:
                pass

        thread = self._accept_thread

        if (
            thread is not None
            and thread
            is not threading.current_thread()
        ):
            thread.join(timeout=2)

        self._accept_thread = None

        for connection in connections:

            try:
                connection.close()
            except Exception:
                pass

        with self._lock:

            self.connections.clear()
            self.connection_set.clear()

    def __enter__(self) -> "PeerNetwork":
        self.start()
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ) -> None:
        self.stop()

    # ---------------------------------------------------------
    # Accept incoming connections
    # ---------------------------------------------------------

    def _accept_loop(self) -> None:

        while self._running:

            server = self.server_socket

            if server is None:
                break

            try:

                client_socket, _address = (
                    server.accept()
                )

            except socket.timeout:
                continue

            except OSError:

                if not self._running:
                    break

                continue

            try:

                connection = (
                    self._create_connection(
                        client_socket,
                        incoming=True,
                    )
                )

                self._register_connection(
                    connection
                )

                connection.start()

                self._notify_connection(
                    connection
                )

            except Exception:

                try:
                    client_socket.close()
                except OSError:
                    pass

    # ---------------------------------------------------------
    # Outgoing connection
    # ---------------------------------------------------------

    def connect(
        self,
        host: str,
        port: int,
        *,
        timeout: Optional[float] = 5.0,
    ) -> PeerConnection:

        client_socket = socket.create_connection(
            (
                host,
                int(port),
            ),
            timeout=timeout,
        )

        connection = (
            self._create_connection(
                client_socket,
                incoming=False,
            )
        )

        self._register_connection(
            connection
        )

        try:

            connection.start()

            self._notify_connection(
                connection
            )

        except Exception:

            self._remove_connection(
                connection
            )

            try:
                connection.close()
            except Exception:
                pass

            raise

        return connection

    # ---------------------------------------------------------
    # Create PeerConnection
    # ---------------------------------------------------------

    def _create_connection(
        self,
        sock: socket.socket,
        *,
        incoming: bool,
    ) -> PeerConnection:

        if self.connection_factory is not None:

            return self.connection_factory(
                sock,
                self._message_callback,
                self._disconnect_callback,
                self.piece_handler,
            )

        connection_callbacks = dict(
            self.callbacks
        )

        if (
            "on_message"
            not in connection_callbacks
            and self.on_message is not None
        ):
            connection_callbacks[
                "on_message"
            ] = self._message_callback

        if (
            "on_disconnect"
            not in connection_callbacks
            and self.on_disconnect is not None
        ):
            connection_callbacks[
                "on_disconnect"
            ] = self._disconnect_callback

        if "on_message" not in connection_callbacks:
            connection_callbacks[
                "on_message"
            ] = self._message_callback

        if "on_disconnect" not in connection_callbacks:
            connection_callbacks[
                "on_disconnect"
            ] = self._disconnect_callback

        return PeerConnection(
            sock,
            callbacks=connection_callbacks,
            piece_handler=self.piece_handler,
            local_handshake=self.local_handshake,
            expected_file_id=self.expected_file_id,
            expected_protocol_version=(
                self.expected_protocol_version
            ),
            require_handshake=(
                self.require_handshake
            ),

            # IMPORTANT:
            # Pass the network's local bitfield
            # into every PeerConnection.
            local_bitfield=(
                list(self.local_bitfield)
                if self.local_bitfield is not None
                else None
            ),
        )

    # ---------------------------------------------------------
    # Connection tracking
    # ---------------------------------------------------------

    def _register_connection(
        self,
        connection: PeerConnection,
    ) -> None:

        with self._lock:

            if connection in self.connection_set:
                return

            self.connection_set.add(
                connection
            )

            self.connections.append(
                connection
            )

    def _remove_connection(
        self,
        connection: PeerConnection,
    ) -> None:

        with self._lock:

            self.connection_set.discard(
                connection
            )

            try:
                self.connections.remove(
                    connection
                )
            except ValueError:
                pass

    # ---------------------------------------------------------
    # Callbacks
    # ---------------------------------------------------------

    def _notify_connection(
        self,
        connection: PeerConnection,
    ) -> None:

        callback = self.on_connection

        if callback is None:
            callback = self.on_peer_connected

        if callback is None:
            callback = self.callbacks.get(
                "on_connection"
            )

        if callback is None:
            callback = self.callbacks.get(
                "on_peer_connected"
            )

        if callback is None:
            return

        self._invoke_callback(
            callback,
            connection,
        )

    def _message_callback(
        self,
        *args,
    ) -> None:

        if len(args) == 2:

            connection, message = args

        elif len(args) == 1:

            connection = None
            message = args[0]

        else:
            return

        callback = self.on_message

        if callback is None:
            callback = self.callbacks.get(
                "on_message"
            )

        if callback is None:
            return

        self._invoke_callback(
            callback,
            connection,
            message,
        )

    def _disconnect_callback(
        self,
        *args,
    ) -> None:

        connection = None
        reason = None

        if len(args) >= 1:
            connection = args[0]

        if len(args) >= 2:
            reason = args[1]

        if isinstance(
            connection,
            PeerConnection,
        ):
            self._remove_connection(
                connection
            )

        callback = self.on_disconnect

        if callback is None:
            callback = self.callbacks.get(
                "on_disconnect"
            )

        if callback is None:
            return

        self._invoke_callback(
            callback,
            connection,
            reason,
        )

    @staticmethod
    def _invoke_callback(
        callback: Callback,
        *args,
    ) -> None:

        attempts = [args]

        if len(args) >= 1:
            attempts.append(
                (args[-1],)
            )

        attempts.append(())

        last_error = None

        for callback_args in attempts:

            try:
                callback(*callback_args)
                return

            except TypeError as exc:
                last_error = exc

        if last_error is not None:
            raise last_error

    # ---------------------------------------------------------
    # Public helpers
    # ---------------------------------------------------------

    def get_connections(
        self,
    ) -> list[PeerConnection]:

        with self._lock:
            return list(
                self.connections
            )

    def remove_connection(
        self,
        connection: PeerConnection,
    ) -> None:

        self._remove_connection(
            connection
        )

    def close_connection(
        self,
        connection: PeerConnection,
    ) -> None:

        self._remove_connection(
            connection
        )

        try:
            connection.close()
        except Exception:
            pass