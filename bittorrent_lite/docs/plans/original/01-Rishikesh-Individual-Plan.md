# Rishikesh Kumar — individual execution plan

**Roll number:** 2405600  
**Project:** CS-30003 P8, BitTorrent-lite, CSE 33  
**Revision:** 22 September 2026 · **Work starts:** 23 September 2026 · **Deadline:** 24 October 2026  
**Ownership:** file storage, metadata, integrity, correctness evidence, and report assembly

## 1. Your outcome and how to use this plan

Your work makes this statement true: “Every piece advertised by a peer is verified and readable, and the completed output contains exactly the original file bytes.” You are also responsible for assembling the team report from sections written by their technical owners.

Work through tasks R01–R10 in order. Each task gives preparation, work, evidence, and a stopping condition. You can develop most of your module without a tracker or network. Use byte fixtures until Anik and Prabhat are ready. Do not wait for their entire components to finish.

This is a proposed plan, not completed work. First inspect your existing code and mark compatible tasks as verified only after running their tests. Keep working compatible code rather than rewriting it for cosmetic reasons.

Shared source of truth: [master guide](BitTorrent-Lite-Revised-Project-Guide.md). Your core implementation must be written and understood by you. AI assistance may explain, review, debug, generate tests, or help with documentation under the course rules; do not submit AI-generated core protocol work as your own.

## 2. What the whole project does

The tracker supplies peer addresses. Peers connect by TCP, exchange their identities and piece inventories, and request pieces directly. A downloader can upload a piece as soon as it has verified and stored it. Each peer has separate memory and disk storage.

Your position in the flow:

```text
Source file -> metadata + piece hashes
                         |
Network receives PIECE -> coordinator -> your verify/store function
                                             |
                                      success or failure
                                             |
                                   coordinator sends HAVE
                                             |
Another peer requests piece -> your read function -> network sends bytes
                                             |
                              all pieces -> assemble + final hash
```

You do not decide what to request, send HAVE yourself, run the tracker, or write TCP frames. Those actions belong to the other owners. You provide trustworthy metadata and storage operations.

## 3. Deliverables and source ownership

Primary source: `src/file_store.py`. A small separate metadata command is acceptable if the team agrees it improves readability; do not create a framework or many one-function modules.

Your proposed repository deliverables:

- Metadata-generation command or entry point with clear usage.
- Metadata validator and file-ID calculation.
- Source-file validation for seeders.
- Piece length/read/verify/store operations.
- Ordered assembly with final size and hash verification.
- Storage and metadata tests with deterministic fixtures.
- `docs/storage.md` explaining format, boundaries, errors, and limitations.
- Correctness evidence for final runs.
- Assembled final report, with team-written sections and contribution record.

You own your tests and documentation. Prabhat calls your functions; Anik carries their bytes; Debargha launches processes and collects measurements.

## 4. Essential concepts to learn before implementation

| Concept | Why you need it | Small exercise |
|---|---|---|
| Bytes versus text | A file can contain any byte, including zero | Read a binary fixture without decoding it |
| Fixed-size pieces | Peers can share before complete download | Split 10 bytes conceptually into 4, 4, and 2 |
| SHA-256 | Compare actual bytes to expected content | Change one byte and observe a changed digest |
| Offset | Locate a piece in the original source | Calculate piece 3's offset at 64 KiB |
| Metadata | All participants agree on file/piece expectations | Explain each field below |
| Temporary versus published files | Failed writes must not appear complete | Simulate an interrupted write |
| Final hash | Validate reconstruction order and output content | Swap two valid pieces and hash the result |

SHA-256 provides an integrity check against trusted metadata. It is not encryption, a password system, or a proof that the sender is honest. Anyone who can replace both data and metadata can provide a matching new hash.

## 5. Fixed contract for version 1

### Metadata

| Field | Type and validation |
|---|---|
| `format_version` | Integer exactly 1 |
| `filename` | Non-empty display string; never an output directory instruction |
| `file_size` | Integer from 1 through 67,108,864 bytes |
| `piece_size` | Integer exactly 65,536 for version 1 |
| `piece_hashes` | Ordered list, one lowercase 64-character hexadecimal SHA-256 per piece |
| `file_sha256` | Lowercase 64-character hexadecimal SHA-256 of full original file |

Read no more than the agreed 256 KiB metadata limit. Reject malformed UTF-8/JSON, wrong types, incorrect hash counts, unexpected version, and inconsistent size information. Do not accept JSON booleans where integers are required. Keep validation errors readable; the CLI should report the offending field.

**File ID:** SHA-256 of the exact metadata-file bytes before parsing. Every participant must receive the identical file. JSON reformatting may preserve values but changes this ID. The metadata does not include its own ID. Tracker location is a separate CLI setting.

### Piece arithmetic

For file size F and piece size P:

- Number of pieces N = ceiling(F/P).
- Valid indices: 0 through N−1.
- Piece i begins at offset i×P.
- Expected length = minimum(P, F−i×P).

Concrete examples:

| File bytes | Piece count | Piece lengths |
|---|---|---|
| 1 | 1 | 1 |
| 65,535 | 1 | 65,535 |
| 65,536 | 1 | 65,536 |
| 65,537 | 2 | 65,536; 1 |
| 131,072 | 2 | 65,536; 65,536 |

There is no zero-length extra piece after an exact multiple. Do not pad the final piece. Empty source files are explicitly unsupported in this version.

### Storage rules

- A downloader uses a unique storage directory; no sharing piece files between processes.
- Store verified pieces under names derived from their numeric indices, not remote filenames.
- Maintain enough local storage bookkeeping for `read_piece` to reject missing pieces; the coordinator remains the authority for advertised HAVE state.
- For a received piece: validate index and exact byte length, hash, compare, write to a temporary file, then publish the completed piece file within the same directory.
- Return success only when the published piece is readable. Clean up partial temporary output after failure where possible.
- This process protects normal execution from partial writes; it is not a promise of power-loss durability or restart recovery.
- A seeder may read directly from its prevalidated source file. Treat that source as immutable while seeding.
- A peer retains verified pieces while advertising them. Manual deletion during a run is unsupported and must produce a visible local error if detected.
- Assembly can temporarily require about twice the source size: individual pieces plus output file. Report disk-space errors distinctly.

## 6. Interfaces you provide

Agree exact names with Prabhat, then keep them stable. These are responsibilities, not supplied implementations.

| Operation | Input | Result | Failure categories |
|---|---|---|---|
| Create metadata | Source path, output metadata path | Saved metadata with ordered hashes | Source missing/unreadable, empty/oversized, output error |
| Load metadata | Metadata path | Validated record + byte-based file ID | Invalid metadata, input too large, I/O |
| Expected piece length | Validated metadata, index | Integer length | Invalid index |
| Validate seed source | Source path, metadata | Success with all pieces verified | Size/hash mismatch, I/O |
| Read piece | Piece index | Exact immutable bytes | Invalid index, unavailable, local I/O |
| Verify and store | Index, bytes | Success after publication | Wrong length, bad hash, local I/O |
| Assemble file | Explicit output path | Verified output size and hash | Missing piece, read/write failure, final mismatch |

Choose one consistent error style: explicit result categories or documented exceptions. Do not return the same `False` for corruption and disk-full conditions, since those require different coordinator decisions.

## 7. Ordered implementation tasks

### R01 — Set up fixtures and prove boundary arithmetic

**When:** 23–24 September. **Dependency:** agreed piece size.

1. Review existing helpers and tests.
2. Create deterministic binary fixtures for the five sizes above.
3. Calculate expected piece counts and lengths independently on paper.
4. Write tests for valid indices and rejection of −1, N, non-integers, and booleans.
5. Test pure boundary helpers before performing file I/O.

**Done when:** every fixture has the correct partition with no missing/duplicated bytes. Share a table of expected lengths with Anik and Prabhat.

### R02 — Generate metadata from a real file

**When:** 24 September. **Dependency:** R01.

1. Read the source in piece-sized chunks.
2. Generate one hash per exact chunk and a whole-file hash over the same byte sequence.
3. Build only the agreed fields.
4. Save the metadata once; distribute that saved file for integration.
5. Document that regeneration/reformatting may create a different swarm ID.

**Evidence:** independently hash a fixture and compare. Generate twice under a stable serialization convention and inspect results, while retaining the rule that peers hash actual saved bytes.

**Done when:** list order, hash count, source size, and final hash all agree for boundary fixtures.

### R03 — Validate metadata before using it

**When:** 24–25 September. **Dependency:** R02.

Test missing fields, wrong version, invalid lengths, bad hex strings, zero size, oversized file, wrong piece size, mismatched hash count, truncated JSON, invalid UTF-8, and too-large input. Reject safely before allocating structures from untrusted lengths.

**Evidence:** one valid fixture loads; deliberately invalid variants each produce a useful error. Reformat the valid JSON and demonstrate why file ID changes.

**Done when:** Prabhat can rely on returned metadata without reimplementing your field-validation logic.

### R04 — Read and validate source pieces

**When:** 25 September. **Dependency:** R03.

1. Validate the seeder source against metadata before advertising all pieces.
2. Read one piece at its calculated offset.
3. Return exact bytes, including the short last piece.
4. If the source is truncated or unreadable later, raise a local storage error rather than fabricate missing bytes.
5. Avoid a shared seek pointer accessed concurrently. The initial design calls storage from the coordinator; if future workers read directly, choose independently opened handles or explicit synchronization.

**Done when:** all piece reads reconstruct the original byte sequence in order.

### R05 — Verify and publish incoming pieces

**When:** 25–26 September. **Dependency:** R03.

Implement the validation and temporary-publication sequence in section 5. Test a valid piece, one changed byte, correct prefix but truncated data, excessive data, invalid index, and a simulated write failure.

**Critical handoff:** return success only after storage succeeds. Prabhat sets HAVE and sends advertisements afterward. Never announce before disk success.

**Done when:** corrupt/failed writes cannot be read as owned pieces and valid saved bytes can be read unchanged.

### R06 — Integrate one piece

**When:** 26–27 September. **Dependencies:** Anik's real REQUEST/PIECE; Prabhat's reservation lifecycle.

1. Provide one canonical metadata fixture and its source.
2. Observe the received bytes passed to your function.
3. Show hash/length validation and stored bytes.
4. Confirm HAVE occurs after success.
5. Repeat once with corrupt bytes using a test hook; it must not produce HAVE.

**Done when:** test I01 and corruption behavior are reproducible with separate peer processes.

### R07 — Assemble and verify a complete file

**When:** 28–29 September. **Dependency:** R05.

1. Require all indices to be present.
2. Read pieces by numeric index, not lexicographic directory listing.
3. Write to a temporary output destination.
4. Confirm exact size and full SHA-256.
5. Publish final output only after verification.
6. Refuse to overwrite unrelated existing output silently; use an explicit chosen destination or documented overwrite option.

**Evidence:** complete fixture succeeds; one missing piece, a reordered sequence, a damaged stored piece, and output-write failure produce clear failure. Include a fixture with indices 9 and 10 to expose lexical ordering mistakes.

**Done when:** a complete network download has the same bytes and final hash as the source.

### R08 — Support real redistribution and scale tests

**When:** 30 September–11 October.

Work with Anik/Prabhat to serve a newly downloaded piece. Your `read_piece` must work for both the source seeder and verified downloader storage behind one agreed interface. Check six independent output directories and the second seeder's source validation.

Help inject corruption at the uploader boundary in a test run: change the transmitted bytes without changing metadata. Save evidence of rejection, recovery, and final correctness. Do not “test corruption” by updating the expected hash to match the corrupted bytes.

### R09 — Collect independent correctness evidence

**When:** 12–21 October.

For measured runs, independently hash each completed output instead of trusting only its COMPLETE log. Record run ID, peer ID, source hash, output hash, expected/actual size, and pass/fail. Debargha joins this evidence with timing rows.

Check that no killed peer is presented as a completed downloader. A failed run remains in the result record. If disk space is low, preserve metadata/logs/hash evidence before removing only disposable run files.

### R10 — Assemble the report and rehearse

**When:** 22–24 October.

Collect the four owners' sections, normalize terminology and units, verify every graph has a matching dataset, and separate implemented behavior from planned features. Have each owner approve their technical section. Add limitations, contribution summary, and truthful AI-use entries.

Rehearse your part: metadata fields, piece length example, one corrupt-piece rejection, and source/output equality. Perform one live boundary-check change and run its test.

## 8. Your test checklist

| ID | Test | Required result |
|---|---|---|
| R-T01 | Sizes 1, P−1, P, P+1, 2P | Correct count/last length |
| R-T02 | Empty or >64 MiB file | Explicit unsupported-input error |
| R-T03 | Invalid metadata types/fields | Reject before use |
| R-T04 | Exact copied metadata | Same file ID |
| R-T05 | Reformat JSON | Different byte-based file ID |
| R-T06 | Negative/out-of-range/bool index | Rejected |
| R-T07 | Valid received piece | Saved and readable unchanged |
| R-T08 | Hash or length mismatch | No verified publication |
| R-T09 | Write fails after partial temporary data | No success result or HAVE eligibility |
| R-T10 | Missing stored piece | Assembly fails clearly |
| R-T11 | More than ten pieces | Numeric assembly order |
| R-T12 | Correct assembled file | Exact size and final SHA-256 |
| R-T13 | Source does not match seed metadata | Seeder cannot advertise all pieces |

Use test temporary directories, not a member's real documents. Map R-T01/R-T08/R-T05/R-T11 to master F01/F02/F03/F04 when recording evidence.

## 9. Handoffs and what to do while waiting

| Partner | You provide | You need | Work available if blocked |
|---|---|---|---|
| Prabhat | Metadata, exact lengths, read/store/assemble results | Agreed coordinator call sites and completion handling | Test all operations with plain bytes |
| Anik | Payload lengths, source bytes, corrupt fixtures | Raw PIECE payload kept as bytes | Boundary and malformed-data tests |
| Debargha | Fixture file, metadata, correctness verification method | Run directories and output paths | Write correctness summary template |

Do not send a changed metadata schema without notifying all three members. Record interface version or commit in the handoff so old fixtures are not mistaken for new ones.

## 10. Debugging guide

- **All last pieces fail:** inspect expected length and accidental padding.
- **Hashes differ only on text files:** check newline translation; use binary reads/writes.
- **Metadata seems identical but peers reject the swarm:** compare exact metadata bytes and file IDs.
- **Individual pieces verify but output differs:** check numerical order, repeated/missing writes, and destination length.
- **Piece advertises but cannot be read:** inspect success timing and temporary-file publication.
- **Corruption retry repeats forever:** distinguish your hash error from a local disk error; show Prabhat the exact category.
- **Seeder output changes mid-run:** inspect whether the source file was edited or overwritten by a download destination.

## 11. Viva questions and live practice

| Question | Your explanation |
|---|---|
| Why hash both pieces and the whole file? | Pieces permit immediate verification/retry; full hash verifies final reconstruction |
| Why not load the entire source into RAM? | Piece reads bound working memory and fit streaming transfer |
| Is hashing reversible? | It is not an encoding we decode back to the file |
| Does a matching hash prove an honest sender? | Only agreement with trusted expected content, not identity |
| What happens at exactly one piece size? | One full piece, no extra empty piece |
| Why metadata-byte hashing? | Everyone uses an identical simple identifier without reserialization ambiguity |
| Why temporary storage? | Avoid publishing partially written data as owned |
| Is restart recovery implemented? | No automatic crash-resume in this scope; fresh runs are the default |
| Who sends HAVE? | Coordinator, after my function reports verified storage success |
| Why no remote filenames as paths? | Output location is a local decision; display metadata must not select arbitrary paths |

Practice: calculate piece lengths for a new file size; explain a source/metadata mismatch; show exactly where a hash failure becomes a retry; trace one piece from disk through Anik's sender and back into your storage function.

## 12. Daily routine and final sign-off

Start each session by reading the current interface contract and latest merged changes. Pick one small R-task, write or identify its expected test, implement, run the relevant test, and commit with a descriptive message. Send the affected member your result and next dependency. Record AI assistance as it occurs.

Suggested commit-sized outcomes: metadata validation, final-piece boundary tests, verified-piece publication, numeric assembly, correctness summary. Preserve your own authorship; report assembly does not replace code contribution.

Final checklist:

- [ ] Metadata and file-ID rules match the shared protocol.
- [ ] Source validation and all boundary cases pass.
- [ ] No bad/failed piece becomes HAVE.
- [ ] Downloaded pieces can be read and uploaded.
- [ ] Final reconstruction has independent size/hash evidence.
- [ ] Six-peer and second-seeder runs have valid outputs.
- [ ] Your report section and integrated report are reviewed.
- [ ] You can explain and modify your implementation without AI during viva.

Selective reference: [Python hashlib documentation](https://docs.python.org/3/library/hashlib.html) for digest operations. Read only the APIs your implementation actually uses; the storage and protocol logic remain your own work.
