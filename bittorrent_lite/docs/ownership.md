# Member ownership

Ownership describes responsibility, not a reassignment of Git authorship.
All existing implementations and contributor history are retained.

| Area | Lead | Source location relative to repository root |
|---|---|---|
| Metadata, hashing, splitting, verified storage and assembly | Rishikesh | `bittorrent_lite/storage/` |
| Tracker membership and discovery client | Debargha | `bittorrent_lite/discovery/` |
| Experiment launch, collection, fixtures and plots | Debargha | `bittorrent_lite/experiments/` |
| Framing, messages, sockets, sessions and network piece handling | Anik | `bittorrent_lite/networking/` |
| Selection, reservations, recovery, uploads and choking | Prabhat | `bittorrent_lite/scheduling/` |
| Entry point, runtime, peer state and adapters | Prabhat leads integration | `bittorrent_lite/application/` |
| Configuration, events, interfaces, types and logs | Shared | `bittorrent_lite/common/` |

`storage/transfer_store.py` preserves the separate file-store implementation used
by the networking contribution. It is not interchangeable with
`storage/file_store.py`; both implementations and their tests remain intact.

`scheduling/legacy/` preserves the original piece-manager implementations,
including the network-facing scheduler, picker, request manager and choking
manager. The newer coordinator is in `scheduling/coordinator.py`. No algorithms
have been merged or discarded merely because their names overlap.

The existing multi-file policy components remain subpackages:
`scheduling/request_pipeline/`, `scheduling/recovery/`,
`scheduling/upload_service/`, and `scheduling/choking_policy/`.
This preserves their public types, models, command-line examples and documentation.

Tests are grouped under `tests/storage/`, `tests/discovery/`,
`tests/networking/`, `tests/scheduling/`, and `tests/integration/` within
`bittorrent_lite/`. Cross-component tests belong to the integration folder even
when originally contributed by one member. Every original test function is retained.

`tests/end_to_end/` contains separate-process acceptance tests. The added
`application/network_backend.py` and `networking/runtime_connection.py` connect
the existing implementations; they do not reassign contribution ownership.
