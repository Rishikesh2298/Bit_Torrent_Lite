"""Remaining wire oracles prepared from the original Anik plan.

``unit`` tests use controlled socket doubles, including the cancellation and
simultaneous-failure compositions. ``socketpair`` tests exchange actual bytes
through connected sockets. Manually established session state is called out;
only the repeated-BITFIELD test performs the full handshake. None is a
multi-process, fresh-challenge, LAN, experiment or acceptance execution claim.
"""
import json
import socket
import struct
import threading

import pytest

from bittorrent_lite.application.adapters import SchedulerBridge
from bittorrent_lite.common import events as ev
from bittorrent_lite.examples.scheduler_dependencies import ManualClock
from bittorrent_lite.networking import framing, messages as m
from bittorrent_lite.networking import runtime_connection as rc
from bittorrent_lite.tests.integration.test_scheduler_integration import (
    disk_store, setup_scheduler,
)


pytestmark = pytest.mark.timeout(15)

# Literal independent wire headers: no Message.to_header or product encoder.
HAVE_HEADER = b'{"type":"HAVE","piece_index":1,"payload_length":0}'
PIECE_HEADER = b'{"type":"PIECE","request_id":17,"piece_index":0,"payload_length":4}'
INTERESTED_HEADER = b'{"type":"INTERESTED","payload_length":0}'
BINARY_PIECE = b'\x00\xff\x80a'


def frame(header, payload=b''):
    return struct.pack('!I', len(header)) + header + payload


def independent_frames(data):
    """Decode complete captured bytes independently of production framing."""
    result, offset = [], 0
    while offset < len(data):
        assert len(data) - offset >= 4, 'truncated prefix in captured stream'
        size = struct.unpack('!I', data[offset:offset + 4])[0]
        offset += 4
        assert 0 < size <= 16384
        assert len(data) - offset >= size, 'truncated header in captured stream'
        header = json.loads(data[offset:offset + size].decode('utf-8'))
        offset += size
        length = header['payload_length']
        assert type(length) is int and 0 <= length <= 65536
        assert len(data) - offset >= length, 'truncated body in captured stream'
        result.append((header, bytes(data[offset:offset + length])))
        offset += length
    assert offset == len(data)
    return result


class MemorySocket:
    """Finite mock socket, with read requests and successful writes visible."""
    def __init__(self, incoming=b''):
        self.incoming = incoming
        self.read_sizes = []
        self.writes = []
        self.written = bytearray()
        self.close_calls = 0

    def settimeout(self, timeout):
        self.timeout = timeout

    def recv(self, size):
        self.read_sizes.append(size)
        result, self.incoming = self.incoming[:size], self.incoming[size:]
        return result

    def sendall(self, data):
        self.writes.append(bytes(data))
        self.written.extend(data)

    def shutdown(self, how):
        pass

    def close(self):
        self.close_calls += 1


def connection(sock, *, events=None, ended=None, ready=None, pieces=2):
    events = [] if events is None else events
    ended = [] if ended is None else ended
    return rc.RuntimeConnection(
        sock, peer_id='local', file_id='f' * 64, bitfield=[0] * pieces,
        expected_peer='remote', ready=ready or (lambda conn: None),
        event=lambda conn, kind, message: events.append((kind, message)),
        disconnected=lambda conn, reason: ended.append(reason),
    )


def established(conn):
    """Install a validated session as a test precondition; no handshake claim."""
    conn.connection_id = 1
    conn.remote_peer_id = 'remote'
    conn._running = True
    conn.handshake_complete = True
    conn.bitfield_received = True
    conn.activate()
    return conn


def flush_writer(conn):
    """Bound one writer batch with its existing sentinel, without closing it."""
    conn._writer_queue.put_nowait(None)
    conn._writer_loop()


def test_unit_three_distinct_coalesced_frames_preserve_order_and_boundaries():
    incoming = (frame(HAVE_HEADER) + frame(PIECE_HEADER, BINARY_PIECE)
                + frame(INTERESTED_HEADER))
    sock = MemorySocket(incoming)
    messages = [framing.recv_message(sock) for _ in range(3)]
    assert [message.type for message in messages] == ['HAVE', 'PIECE', 'INTERESTED']
    assert messages[0].piece_index == 1
    assert (messages[1].request_id, messages[1].piece_index, messages[1].payload) == (
        17, 0, BINARY_PIECE)
    assert messages[2].payload == b''
    assert sock.incoming == b''
    assert framing.recv_message(sock) is None


def test_socketpair_three_distinct_coalesced_frames_preserve_order():
    left, right = socket.socketpair()
    left.settimeout(2)
    try:
        right.sendall(frame(HAVE_HEADER) + frame(PIECE_HEADER, BINARY_PIECE)
                      + frame(INTERESTED_HEADER))
        right.shutdown(socket.SHUT_WR)
        messages = [framing.recv_message(left) for _ in range(3)]
        assert [message.type for message in messages] == ['HAVE', 'PIECE', 'INTERESTED']
        assert messages[0].piece_index == 1
        assert messages[1].payload == BINARY_PIECE
        assert messages[1].request_id == 17 and messages[1].piece_index == 0
        assert framing.recv_message(left) is None
    finally:
        left.close()
        right.close()


@pytest.mark.parametrize('size', [0, 16385, 2 ** 32 - 1],
                         ids=['zero', 'limit-plus-one', 'uint32-max'])
def test_unit_receiver_rejects_header_length_before_any_header_read(size):
    suffix = b'header must remain unread'
    sock = MemorySocket(struct.pack('!I', size) + suffix)
    with pytest.raises(ValueError, match='header length'):
        framing.recv_message(sock)
    assert sock.read_sizes == [4]
    assert sock.incoming == suffix
    events, ended = [], []
    bad_session = MemorySocket(struct.pack('!I', size) + suffix)
    conn = established(connection(bad_session, events=events, ended=ended))
    conn._reader_loop()
    assert bad_session.read_sizes == [4] and bad_session.incoming == suffix
    assert conn.closed and bad_session.close_calls == 1
    assert events == [('disconnected', None)] and len(ended) == 1


@pytest.mark.parametrize('token', ['-1', 'true', 'false', '1.5', '"4"', 'null', '65537'],
                         ids=['negative', 'true', 'false', 'float', 'string', 'null', 'oversize'])
def test_unit_receiver_rejects_invalid_payload_length_before_payload_read(token):
    header = ('{"type":"PIECE","request_id":17,"piece_index":0,"payload_length":'
              + token + '}').encode('ascii')
    suffix = b'payload must remain unread'
    sock = MemorySocket(frame(header) + suffix)
    with pytest.raises(ValueError, match='payload'):
        framing.recv_message(sock)
    assert sock.read_sizes == [4, len(header)]
    assert sock.incoming == suffix
    conn = established(connection(MemorySocket(frame(header) + suffix)))
    conn._reader_loop()
    assert conn.closed and conn.sock.close_calls == 1
    assert conn.sock.incoming == suffix


_PIECE_FRAME = frame(PIECE_HEADER, BINARY_PIECE)


@pytest.mark.parametrize('cut', [1, 2, 3, 4, 5, 4 + len(PIECE_HEADER) - 1,
                                 4 + len(PIECE_HEADER), len(_PIECE_FRAME) - 1],
                         ids=['prefix-1', 'prefix-2', 'prefix-3', 'header-empty',
                              'header-1', 'header-last-byte', 'payload-empty',
                              'payload-last-byte'])
def test_unit_partial_eof_never_delivers_frame_and_connection_closes_once(cut):
    truncated = _PIECE_FRAME[:cut]
    with pytest.raises(ConnectionError, match='closed while receiving'):
        framing.recv_message(MemorySocket(truncated))
    events, ended = [], []
    conn = established(connection(MemorySocket(truncated), events=events, ended=ended))
    conn._reader_loop()
    conn.close()  # Repeated cleanup must not duplicate the semantic notification.
    assert conn.closed and not conn.running and conn.sock.close_calls == 1
    assert events == [('disconnected', None)]
    assert len(ended) == 1


def test_unit_pure_idle_polls_do_not_close_or_consume_the_next_frame():
    class IdleSocket(MemorySocket):
        polls = 0

        def recv(self, size):
            assert self.close_calls == 0
            if self.polls < 5:
                self.polls += 1
                raise socket.timeout('idle without a prefix byte')
            return super().recv(size)

    sock, events, ended = IdleSocket(frame(HAVE_HEADER)), [], []
    conn = established(connection(sock, events=events, ended=ended))
    conn._reader_loop()
    assert sock.polls == 5
    assert len(events) == 2 and events[0] == ('received', m.Have(1))
    assert events[1] == ('disconnected', None)
    assert sock.close_calls == 1 and len(ended) == 1


def test_socketpair_idle_polls_keep_session_open_until_a_valid_frame_arrives():
    left, right = socket.socketpair()
    arrived, ended_event = threading.Event(), threading.Event()
    events = []
    conn = established(connection(left))

    def delivered(connection, kind, message):
        events.append((kind, message))
        if kind == 'received':
            arrived.set()

    conn._event = delivered
    conn._disconnected = lambda *args: ended_event.set()
    reader = threading.Thread(target=conn._reader_loop, daemon=True)
    reader.start()
    try:
        assert not ended_event.wait(.45)  # More than two normal 0.2s socket polls.
        assert reader.is_alive() and not conn.closed and events == []
        right.sendall(frame(HAVE_HEADER))
        assert arrived.wait(2)
        assert events == [('received', m.Have(1))]
        assert not conn.closed
    finally:
        conn.close()
        right.close()
        reader.join(2)
        assert not reader.is_alive()


def test_socketpair_frame_deadline_closes_transport_without_external_cleanup(monkeypatch):
    left, right = socket.socketpair()
    events, ended = [], []
    conn = established(connection(left, events=events, ended=ended))
    # Exercise the real deadline algorithm at a shorter injected test interval.
    monkeypatch.setattr(rc, 'recv_message',
                        lambda sock: framing.recv_message(sock, frame_timeout=.05))
    left.settimeout(.01)
    try:
        right.sendall(b'\x00\x00')
        conn._reader_loop()
        assert conn.closed and not conn.running
        assert left.fileno() == -1  # Assert before any test-finally close.
        assert events == [('disconnected', None)] and len(ended) == 1
    finally:
        conn.close()
        right.close()


def test_socketpair_repeated_initial_bitfield_closes_after_one_ready_notification():
    left, right = socket.socketpair()
    right.settimeout(2)
    ready_event, ended_event = threading.Event(), threading.Event()
    ready_calls, events = [], []

    def ready(conn):
        ready_calls.append(conn)
        ready_event.set()

    conn = connection(left, events=events, ready=ready)
    conn._disconnected = lambda *args: ended_event.set()
    conn.activate()
    conn.start()
    try:
        header = ('{"type":"HANDSHAKE","protocol_version":1,"file_id":"'
                  + 'f' * 64 + '","peer_id":"remote","payload_length":0}').encode()
        bitfield = frame(b'{"type":"BITFIELD","pieces":[1,0],"payload_length":0}')
        right.sendall(frame(header) + bitfield)
        assert ready_event.wait(2)
        assert [framing.recv_message(right).type for _ in range(2)] == ['HANDSHAKE', 'BITFIELD']
        right.sendall(bitfield + frame(HAVE_HEADER))
        assert ended_event.wait(2)
        conn.join(2)
        assert ready_calls == [conn]
        assert events == [('disconnected', None)]
        assert conn.closed and left.fileno() == -1 and not conn.workers_alive()
    finally:
        conn.close()
        conn.join(2)
        right.close()
        assert not conn.workers_alive()


def test_unit_partial_send_is_attempted_once_and_never_replays_or_sends_next_frame(monkeypatch):
    class FailingSocket(MemorySocket):
        def sendall(self, data):
            self.writes.append(bytes(data))
            self.written.extend(data[:3])  # Only the double knows the partial count.
            raise OSError('controlled failure after three bytes')

    sock, events, records = FailingSocket(), [], []
    monkeypatch.setattr(rc.run_log, 'emit',
                        lambda event, **fields: records.append(dict(event=event, **fields)))
    conn = established(connection(sock, events=events))
    piece, following = m.Piece(17, 0, BINARY_PIECE), m.Have(1)
    conn.send(piece)
    conn.send(following)
    conn._writer_loop()
    assert len(sock.writes) == 1
    assert sock.written == sock.writes[0][:3]
    assert independent_frames(sock.writes[0])[0][0]['type'] == 'PIECE'
    assert events == [('send_failed', piece), ('disconnected', None)]
    assert conn.closed and sock.close_calls == 1
    assert not [r for r in records if r['event'] in ('frame_sent', 'piece_uploaded')]
    failed = [r for r in records if r['event'] == 'frame_send_failed']
    assert len(failed) == 1 and failed[0]['frame_bytes'] is None
    assert failed[0]['partial_bytes_known'] is False


def upload_bridge(tmp_path, conn):
    store, pieces = disk_store(tmp_path)
    for index, data in enumerate(pieces):
        assert store.verify_and_store(index, data)
    bridge = SchedulerBridge(ManualClock())
    coordinator = bridge.create_coordinator(store)

    def forward(connection, kind, message):
        if kind == 'disconnected':
            bridge.disconnected(1)
        else:
            getattr(bridge, kind)(1, message)

    conn._event = forward
    bridge.register(1, 'remote', conn.send, withdraw=conn.withdraw,
                    close=lambda reason: conn.close())
    bridge.received(1, m.Interested())
    bridge.drain(coordinator)
    flush_writer(conn)
    bridge.drain(coordinator)
    return bridge, coordinator, pieces


def test_socketpair_cancel_before_writer_sends_zero_piece_bytes_and_next_frame_is_valid(tmp_path):
    """Actual socket writes; upload requests/cancel are owner-thread injection."""
    left, right = socket.socketpair()
    right.settimeout(2)
    conn = established(connection(left))
    coordinator = None
    try:
        bridge, coordinator, pieces = upload_bridge(tmp_path, conn)
        assert isinstance(framing.recv_message(right), m.Unchoke)
        bridge.received(1, m.Request(1, 0))
        bridge.drain(coordinator)
        assert any(isinstance(item, m.Piece) for item in list(conn._writer_queue.queue))
        bridge.received(1, m.Cancel(1, 0))
        bridge.drain(coordinator)
        assert coordinator.uploads.snapshot()['service']['active_jobs'] == 0
        conn.send(m.Have(1))
        flush_writer(conn)
        bridge.drain(coordinator)
        left.shutdown(socket.SHUT_WR)
        # If any canceled frame/header/body had escaped, these two reads fail.
        assert framing.recv_message(right) == m.Have(1)
        assert framing.recv_message(right) is None
        assert coordinator.uploads.snapshot()['service']['sent_bytes'] == 0
    finally:
        conn.close()
        right.close()
        if coordinator is not None:
            coordinator.uploads.shutdown()


def test_unit_started_cancel_finishes_frame_then_valid_next_frame_and_late_piece_is_ignored(tmp_path):
    """Controlled partial socket write plus real upload/scheduler components."""
    entered, release = threading.Event(), threading.Event()

    class GatedSocket(MemorySocket):
        gated = False

        def sendall(self, data):
            self.writes.append(bytes(data))
            if self.gated:
                self.gated = False
                self.written.extend(data[:3])
                entered.set()
                if not release.wait(3):
                    raise OSError('test did not release the started frame')
                self.written.extend(data[3:])
            else:
                self.written.extend(data)

    sock = GatedSocket()
    conn = established(connection(sock))
    bridge, coordinator, pieces = upload_bridge(tmp_path, conn)
    sock.written.clear()
    sock.writes.clear()
    writer = None
    try:
        bridge.received(1, m.Request(1, 0))
        bridge.drain(coordinator)
        piece = next(item for item in list(conn._writer_queue.queue) if isinstance(item, m.Piece))
        sock.gated = True
        writer = threading.Thread(target=conn._writer_loop, daemon=True)
        writer.start()
        assert entered.wait(2)
        assert len(sock.written) == 3 and not conn.withdraw(piece)
        bridge.received(1, m.Cancel(1, 0))
        bridge.drain(coordinator)
        assert coordinator.uploads.snapshot()['service']['active_jobs'] == 1
        assert coordinator.uploads.snapshot()['service']['sent_bytes'] == 0
        conn.send(m.Have(1))
        conn._writer_queue.put_nowait(None)
        release.set()
        writer.join(3)
        assert not writer.is_alive() and not conn.closed
        bridge.drain(coordinator)
        decoded = independent_frames(bytes(sock.written))
        assert [header['type'] for header, payload in decoded] == ['PIECE', 'HAVE']
        assert decoded[0][0]['request_id'] == 1 and decoded[0][0]['piece_index'] == 0
        assert decoded[0][1] == pieces[0] and decoded[1][0]['piece_index'] == 1
        assert len(sock.writes) == 2
        assert coordinator.uploads.snapshot()['service']['active_jobs'] == 0
        assert coordinator.uploads.snapshot()['service']['sent_bytes'] == len(pieces[0])

        # Separate receiver oracle: revoke an exact request before its late
        # response, then deliver bytes of its correct length/hash. No corruption
        # rejection can accidentally stand in for stale-request rejection.
        receiver, clock, transport, store, receiver_pieces = setup_scheduler(n=2)
        pending = receiver.snapshot()['pending'][0]
        receiver.handle_event(ev.ChokeReceived(1))
        assert receiver.snapshot()['pending'] == []
        receiver.handle_event(ev.PieceReceived(1, pending['request_id'],
                                               pending['piece_index'],
                                               receiver_pieces[pending['piece_index']]))
        receiver.handle_event(ev.HaveReceived(1, 1))
        assert receiver.snapshot()['owned'] == 0
        assert receiver.snapshot()['local_bitfield'] == [False, False]
        assert receiver.snapshot()['availability'] == [1, 1]
        assert not [entry for entry in transport.log if entry[0] == 'HAVE']
    finally:
        release.set()
        conn.close()
        if writer is not None:
            writer.join(3)
            assert not writer.is_alive()
        coordinator.uploads.shutdown()


def test_socketpair_concurrent_producers_emit_only_complete_ordered_frames():
    """Four producer threads, one real socket writer; no swarm-scale claim."""
    left, right = socket.socketpair()
    right.settimeout(3)
    events, errors = [], []
    conn = established(connection(left, events=events, pieces=48))
    start = threading.Barrier(5)

    def producer(number):
        try:
            start.wait(3)
            for sequence in range(12):
                conn.send(m.Have(number * 12 + sequence))
        except BaseException as exc:
            errors.append(exc)

    writer = threading.Thread(target=conn._writer_loop, daemon=True)
    producers = [threading.Thread(target=producer, args=(number,), daemon=True)
                 for number in range(4)]
    writer.start()
    for thread in producers:
        thread.start()
    try:
        start.wait(3)
        messages = [framing.recv_message(right) for _ in range(48)]
        for thread in producers:
            thread.join(3)
            assert not thread.is_alive()
        assert errors == []
        assert all(isinstance(message, m.Have) for message in messages)
        observed = [message.piece_index for message in messages]
        assert sorted(observed) == list(range(48))
        for number in range(4):
            assert [value for value in observed if value // 12 == number] == list(
                range(number * 12, (number + 1) * 12))
        conn._writer_queue.put_nowait(None)
        writer.join(3)
        assert not writer.is_alive()
        assert len([kind for kind, message in events if kind == 'sent']) == 48
    finally:
        conn.close()
        right.close()
        for thread in producers:
            thread.join(3)
            assert not thread.is_alive()
        writer.join(3)
        assert not writer.is_alive()


def test_unit_concurrent_reader_writer_failures_notify_and_release_reservations_once(tmp_path):
    reader_entered, writer_entered, release = (threading.Event() for _ in range(3))

    class FailedBothSocket(MemorySocket):
        def recv(self, size):
            reader_entered.set()
            if not release.wait(3):
                raise OSError('reader test gate expired')
            raise ConnectionResetError('controlled read failure')

        def sendall(self, data):
            writer_entered.set()
            if not release.wait(3):
                raise OSError('writer test gate expired')
            raise BrokenPipeError('controlled write failure')

    sock, ended, forwarded = FailedBothSocket(), [], []
    store, pieces = disk_store(tmp_path)
    bridge = SchedulerBridge(ManualClock())
    coordinator = bridge.create_coordinator(store)
    conn = established(connection(sock, ended=ended, pieces=len(pieces)))

    def forward(connection, kind, message):
        forwarded.append(kind)
        if kind == 'disconnected':
            bridge.disconnected(1)
        else:
            getattr(bridge, kind)(1, message)

    conn._event = forward
    bridge.register(1, 'remote', conn.send, withdraw=conn.withdraw,
                    close=lambda reason: conn.close())
    bridge.received(1, m.BitfieldMsg([1] * len(pieces)))
    bridge.received(1, m.Unchoke())
    bridge.drain(coordinator)
    assert coordinator.snapshot()['pending']
    workers = [threading.Thread(target=target, daemon=True)
               for target in (conn._reader_loop, conn._writer_loop)]
    for thread in workers:
        thread.start()
    try:
        assert reader_entered.wait(2) and writer_entered.wait(2)
        release.set()
        for thread in workers:
            thread.join(3)
            assert not thread.is_alive()
        bridge.drain(coordinator)
        snapshot = coordinator.snapshot()
        assert conn.closed and sock.close_calls == 1 and len(ended) == 1
        assert forwarded.count('disconnected') == 1
        assert snapshot['pending'] == []
        assert snapshot['availability'] == [0] * len(pieces)
        assert not snapshot['neighbors'][1]['active']
        assert snapshot['neighbors'][1]['outstanding'] == 0
        assert snapshot['piece_states']['MISSING'] == len(pieces)
        assert sum(snapshot['piece_states'].values()) == len(pieces)
        assert all(type(value) is int and value >= 0
                   for value in snapshot['piece_states'].values())
        assert all(type(value) is int and value >= 0
                   for value in snapshot['pipeline_counters'].values())
        service = coordinator.uploads.snapshot()['service']
        for name in ('active_jobs', 'queued_jobs', 'reading_jobs', 'output_slots',
                     'reserved_output_bytes', 'reserved_read_bytes'):
            assert service[name] == 0, name
        assert all(value >= 0 for value in service.values() if type(value) is int)
    finally:
        release.set()
        conn.close()
        for thread in workers:
            thread.join(3)
            assert not thread.is_alive()
        coordinator.uploads.shutdown()
