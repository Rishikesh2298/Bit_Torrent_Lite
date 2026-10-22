# BitTorrent-Lite Protocol Specification

**Version:** 0.1 (Draft)
**Authors:** Anik Dey (primary), Team P8
**Last Updated:** 2026-09-15

---

## 1. Overview

This document specifies the peer wire protocol used by BitTorrent-Lite.
All peers in the swarm must implement this protocol to participate in
file distribution.

The protocol operates over **TCP** connections between peers.

---

## 2. Connection Lifecycle

```
Peer A                           Peer B
  |                                 |
  |──── TCP connect ───────────────>|
  |                                 |
  |──── HANDSHAKE ────────────────->|
  |<─── HANDSHAKE ──────────────────|
  |                                 |
  |   (verify info_hash matches)    |
  |                                 |
  |──── BITFIELD ──────────────────>|
  |<─── BITFIELD ───────────────────|
  |                                 |
  |   (normal message exchange)     |
  |                                 |
```

1. One peer initiates a TCP connection to the other.
2. Both peers exchange HANDSHAKE messages.
3. If info_hash doesn't match, the connection is closed.
4. Both peers exchange BITFIELD messages.
5. Normal message exchange begins.

---

## 3. Message Framing

All messages (except HANDSHAKE) use length-prefixed framing:

```
┌─────────────────┬──────────────────────────────────┐
│  Length (4B)     │  Payload                         │
│  big-endian u32 │  [msg_type: 1B] [fields: var]    │
└─────────────────┴──────────────────────────────────┘
```

- **Length** = number of bytes in the payload (NOT including the 4-byte length itself)
- **msg_type** = single byte identifying the message type
- **fields** = type-specific payload bytes

A message with length=0 is a **keep-alive** and should be ignored.

---

## 4. HANDSHAKE

The handshake uses a **fixed format** (NOT length-prefixed):

```
┌───────────────────┬──────────────────┬──────────────────┬───────────────┬────────────┐
│ proto_name_len    │ protocol_name    │ info_hash        │ peer_id_len   │ peer_id    │
│ 1 byte            │ variable         │ 32 bytes         │ 1 byte        │ variable   │
└───────────────────┴──────────────────┴──────────────────┴───────────────┴────────────┘
```

| Field | Size | Encoding | Description |
|---|---|---|---|
| `proto_name_len` | 1 byte | unsigned int | Length of protocol name |
| `protocol_name` | variable | UTF-8 | `"BitTorrent-Lite"` |
| `info_hash` | 32 bytes | raw bytes | SHA-256 of metadata content |
| `peer_id_len` | 1 byte | unsigned int | Length of peer ID |
| `peer_id` | variable | UTF-8 | e.g., `"peer-001"` |

**Validation:**
- Protocol name must be `"BitTorrent-Lite"`
- info_hash must match (same torrent)
- If validation fails → close connection

---

## 5. Message Types

<!-- TODO: Anik — fill in the exact binary layout for each message -->

### 5.1 CHOKE (type=0)
- **Payload:** none
- **Meaning:** "I will not upload to you"

### 5.2 UNCHOKE (type=1)
- **Payload:** none
- **Meaning:** "I am willing to upload to you"

### 5.3 INTERESTED (type=2)
- **Payload:** none
- **Meaning:** "You have pieces I want"

### 5.4 NOT_INTERESTED (type=3)
- **Payload:** none
- **Meaning:** "You have nothing I need"

### 5.5 HAVE (type=4)
- **Payload:** `piece_index` (4 bytes, big-endian u32)
- **Meaning:** "I just obtained this piece"

### 5.6 BITFIELD (type=5)
- **Payload:** bitfield bytes (⌈num_pieces / 8⌉ bytes)
- **Encoding:** Bit `i` of byte `⌊i/8⌋` (MSB first) = 1 if piece `i` is owned
- **Meaning:** "Here are all pieces I currently have"

### 5.7 REQUEST (type=6)
- **Payload:** `piece_index` (4B) + `offset` (4B) + `length` (4B)
- **All big-endian u32**
- **Meaning:** "Send me this piece/block"

### 5.8 PIECE (type=7)
- **Payload:** `piece_index` (4B) + `offset` (4B) + `data` (variable)
- **Meaning:** "Here is the data you requested"

### 5.9 CANCEL (type=8)
- **Payload:** `piece_index` (4B) + `offset` (4B) + `length` (4B)
- **Meaning:** "Disregard my previous request"

---

## 6. Bitfield Encoding

Example for 10 pieces where pieces 0, 1, 3, 7, 9 are owned:

```
Piece indices: 0 1 2 3 4 5 6 7 | 8 9 _ _ _ _ _ _
Bit values:    1 1 0 1 0 0 0 1 | 0 1 0 0 0 0 0 0
Byte values:        0xD1       |      0x40
```

Spare bits in the last byte (positions beyond num_pieces) MUST be zero.

---

## 7. Error Handling

| Condition | Action |
|---|---|
| Unknown msg_type | Log warning, ignore message |
| Payload too short | Log error, close connection |
| Length > MAX_MESSAGE_SIZE | Log error, close connection |
| info_hash mismatch in HANDSHAKE | Close connection |
| Protocol name mismatch | Close connection |
| Connection closed mid-read | Clean up, remove peer |

---

## 8. State Transitions

<!-- TODO: Anik — document the per-connection state transitions -->

---

## 9. Revision History

| Version | Date | Changes |
|---|---|---|
| 0.1 | 2026-09-15 | Initial draft |
