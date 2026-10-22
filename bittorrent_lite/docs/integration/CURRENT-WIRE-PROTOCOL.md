# Current JSON wire protocol, version 1

This document describes `networking/framing.py`, `messages.py` and the runtime
adapter. Anik's [original protocol draft](../anik/protocol_spec.md) is preserved
as historical design material. Its binary message IDs, bit-packed bitfield and
unframed handshake are not the current implementation's wire format.

Every message, including HANDSHAKE, is framed as:

```text
4-byte unsigned big-endian JSON-header byte length
UTF-8 JSON object (no delimiter)
payload_length raw bytes
```

Header length is 1–16,384 bytes. Payload length is an integer 0–65,536; booleans
are rejected. Only PIECE carries a nonempty payload. Unknown types are rejected.
The sender counts encoded UTF-8 bytes, not characters. TCP reads may split or
coalesce frames; framing accumulates bytes across reads and applies a deadline.

Every header has `type` and `payload_length`, plus:

| Type | Additional fields |
|---|---|
| HANDSHAKE | `protocol_version` (integer 1), `file_id`, `peer_id` |
| BITFIELD | `pieces` (JSON array of integer 0 or 1) |
| HAVE | `piece_index` |
| INTERESTED | none |
| NOT_INTERESTED | none |
| CHOKE | none |
| UNCHOKE | none |
| REQUEST | `request_id`, `piece_index` |
| PIECE | `request_id`, `piece_index`; exact binary piece payload follows |
| CANCEL | `request_id`, `piece_index` |
| REJECT | `request_id`, `piece_index`, `reason` (string) |

Request IDs on the wire are integers 1 through 2^63−1; booleans are rejected.
The scheduler allocates IDs independently per connection. Piece indices are
nonnegative integers; the runtime also checks them against the metadata piece
count. Runtime bitfields must have exactly that count. Legacy convenience
message constructors remain available and can have broader in-process input
contracts; wire validation is applied when encoding/decoding frames.

The runtime validates the expected file identity and peer identity, rejects
self/duplicate/unexpected peers, requires the initial bitfield after handshake,
and rejects duplicate initial handshakes/bitfields. Runtime peer IDs use the
tracker's safe 1–32-character ASCII identifier domain. A wrong-length or corrupt
piece must not become owned or advertise HAVE; storage verifies SHA-256 first.

Requests are for whole pieces. Interest, choking permission, request identity,
successful full socket writes, storage verification and ownership are distinct
state transitions. A queued frame is not proof of a successful send. Failed
sendall calls do not expose an exact partial byte count.

Duplicate-key/unknown-field policy across every JSON parser and all remaining
acceptance cases must be resolved in the preparation ledger before freeze.
This document is a current implementation description, not an independent
certification that the complete protocol campaign passed.
