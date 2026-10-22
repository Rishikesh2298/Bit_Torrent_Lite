# Storage and integrity

Lead: Rishikesh. Source: [storage package](../../storage/).

- `metadata.py`: metadata generation, loading and validation.
- `hashing.py`: hashing helpers (formerly `file_manager/hasher.py`).
- `pieces.py`: file splitting (formerly `file_manager/splitter.py`).
- `file_store.py`: verified piece storage and assembly.
- `generate_metadata.py`: metadata command-line tool.
- `transfer_store.py`: the separately contributed network-facing file store,
  preserved with its existing interface and tests.

[Original individual plan](../plans/original/01-Rishikesh-Individual-Plan.md)
and [storage tests](../../tests/storage/) describe intended behavior and existing
checks. The layout migration did not execute those tests.
