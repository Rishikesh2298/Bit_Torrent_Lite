"""Real adapter boundaries: no simulated file transfer claims here."""
import json
import queue
import socket
import struct
import threading
import time

import pytest

from bittorrent_lite.networking import messages as m
from bittorrent_lite.networking.framing import recv_message, send_message
from bittorrent_lite.networking.runtime_connection import RuntimeConnection


def connection(sock, **kwargs):
    return RuntimeConnection(sock, peer_id='local', file_id='f' * 64,
                             bitfield=[0, 0], ready=lambda c: None,
                             event=lambda *args: None, disconnected=lambda *args: None, **kwargs)


def test_fragmented_and_coalesced_frames_survive_socket_poll_timeout():
    left, right = socket.socketpair()
    left.settimeout(.02)
    header = json.dumps({'type': 'HAVE', 'piece_index': 1, 'payload_length': 0}).encode()
    wire = struct.pack('!I', len(header)) + header
    def write():
        for chunk in (wire[:2], wire[2:8], wire[8:] + wire):
            right.sendall(chunk)
            time.sleep(.06)
    thread = threading.Thread(target=write)
    thread.start()
    try:
        assert recv_message(left).piece_index == 1
        assert recv_message(left).piece_index == 1
    finally:
        thread.join(2)
        left.close()
        right.close()


def test_partial_frame_deadline_closes_instead_of_reparsing():
    left, right = socket.socketpair()
    left.settimeout(.02)
    right.sendall(b'\0\0')
    try:
        with pytest.raises(ConnectionError, match='timed out|deadline'):
            recv_message(left, frame_timeout=.08)
    finally:
        left.close()
        right.close()


def test_bounded_queue_withdraws_exact_object_before_writer_start():
    left, right = socket.socketpair()
    conn = connection(left, capacity=1)
    try:
        conn._running = True
        conn.handshake_complete = True
        first = m.Request(1, 0)
        conn.send(first)
        with pytest.raises(queue.Full):
            conn.send(m.Request(2, 1))
        assert not conn.withdraw(m.Request(1, 0))
        assert conn.withdraw(first)
        assert not conn.withdraw(first)
    finally:
        conn.close()
        right.close()


@pytest.mark.parametrize('failure', [False, True])
def test_writer_acknowledges_only_after_full_write_and_never_withdraws_started(failure):
    entered, release = threading.Event(), threading.Event()
    events = []
    class Socket:
        def settimeout(self, timeout): pass
        def sendall(self, data):
            entered.set()
            assert release.wait(2)
            if failure:
                raise OSError('partial write')
        def shutdown(self, how): pass
        def close(self): pass
    conn = connection(Socket())
    conn._event = lambda c, kind, message: events.append((kind, message))
    conn.activate()
    conn._running = True
    conn.handshake_complete = True
    message = m.Piece(1, 0, b'payload')
    conn.send(message)
    writer = threading.Thread(target=conn._writer_loop)
    writer.start()
    try:
        assert entered.wait(2)
        assert not events
        assert not conn.withdraw(message)
        release.set()
        deadline = time.monotonic() + 2
        while not events and time.monotonic() < deadline:
            time.sleep(.01)
        assert events[0] == ('send_failed' if failure else 'sent', message)
    finally:
        release.set()
        conn.close()
        writer.join(2)
        assert not writer.is_alive()


@pytest.mark.parametrize('bad', ['self', 'wrong-file', 'wrong-peer', 'version', 'bitfield', 'pre-handshake'])
def test_invalid_session_never_reaches_runtime(bad):
    left, right = socket.socketpair()
    ready = []
    conn = connection(left, expected_peer='remote')
    conn._ready = ready.append
    conn.start()
    try:
        handshake = m.Handshake(1, 'f' * 64, 'remote')
        if bad == 'self': handshake.peer_id = 'local'
        if bad == 'wrong-file': handshake.file_id = 'e' * 64
        if bad == 'wrong-peer': handshake.peer_id = 'stranger'
        if bad == 'version': handshake.protocol_version = 2
        if bad == 'pre-handshake':
            send_message(right, m.Interested())
        else:
            send_message(right, handshake)
            if bad == 'bitfield':
                send_message(right, m.BitfieldMsg([1]))
        assert conn.wait_for_disconnect(2)
        assert ready == []
    finally:
        conn.close()
        conn.join(2)
        right.close()
        assert not conn.workers_alive()


def test_early_events_wait_for_owner_admission():
    left, right = socket.socketpair()
    events = []
    conn = connection(left)
    conn._event = lambda c, kind, message: events.append((kind, message))
    try:
        message = m.Interested()
        conn._forward('received', message)
        conn.close()
        assert not events
        conn.activate()
        assert events == [('received', message), ('disconnected', None)]
    finally:
        right.close()
