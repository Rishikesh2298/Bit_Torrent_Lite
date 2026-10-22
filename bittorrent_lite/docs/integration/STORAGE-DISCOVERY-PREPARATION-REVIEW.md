# Storage, discovery and common-module preparation review

This is a source review and static test mapping, not execution evidence. The
entire controlling plan including Appendices A–D, all five original plans and
all four follow-up plans were read. The root preparation task owns the complete
source-span normative inventory and final ledger; this file supplies scoped
review notes and must not be counted as that inventory's completion.

Original plan aliases below are the immutable files in `docs/plans/original/`:
R = `01-Rishikesh-Individual-Plan.md`; D = `02-Debargha-Individual-Plan.md`;
A = `03-Anik-Individual-Plan.md`; P = `04-Prabhat-Individual-Plan.md`;
G = `BitTorrent-Lite-Revised-Project-Guide.md`. Preserve every original's text,
authorship and hash. A superseding decision belongs in integration records.

## Precise clauses and review consequences

| Source | Exact excerpt | Review consequence |
|---|---|---|
| R:85 | “Read no more than the agreed 256 KiB metadata limit.” | Bounded read plus rejection before parse is required; an after-parse size assertion is insufficient. Added boundary and read-spy methods in `test_storage_contracts.py`. |
| R:87 | “SHA-256 of the exact metadata-file bytes before parsing.” | Equal parsed values with different formatting must have different IDs. Test exact bytes independently, not only create/save round trips. |
| R:156 | “Read the source in piece-sized chunks.” | The source-read spy records requested lengths and independent handles; it is not a peak-RSS proof. |
| R:183 | “If the source is truncated or unreadable later, raise a local storage error rather than fabricate missing bytes.” | Still requires live process fault timing and source availability evidence in later phases. |
| R:184 | “choose independently opened handles or explicit synchronization.” | Concurrent reads use per-call handles. Do not infer this from a sequential correct output. |
| R:216–218 | “Write to a temporary output destination.” / “Confirm exact size and full SHA-256.” / “Publish final output only after verification.” | Inject partial write, final hash and replace failures with a pre-existing unrelated sentinel. Added procedures preserve destination and check temporary files. |
| R:219 | “use an explicit chosen destination or documented overwrite option.” | Existing explicit output-path behavior must be recorded as the reviewed policy before freeze; do not silently invent a universal no-overwrite behavior. |
| D:64 | “Require a valid bounded Content-Length” | Test invalid/missing/oversize lengths, unsupported transfer encoding, UTF-8 and content type before membership mutation. |
| D:70 | “You may consolidate validation errors as 400” | Proposed status codes are alternatives, not simultaneously mandatory. Freeze the actual reviewed error contract and test it consistently. |
| D:93 | “Start announcing only after the listener binds successfully.” | A fake HTTP payload test cannot establish bind/announce ordering. A live process observation is still required. |
| D:95 | “Use a three-second HTTP timeout; bound response size, proposed 64 KiB.” | Standalone timeout is 3s; integration currently supplies 1s for shutdown bounds. Record that intentional integration choice, not a false match. |
| D:96 | “retry after 2, 4, then at most 10 seconds; reset after success.” | Added worker-loop fake-wait procedure observes actual retry choices and reset; live tracker outage remains separate. |
| D:97 | “Do not allow a nonsense interval to cause a tight request loop.” | Boundary/type/peer response validation and bounded nested JSON failures need explicit identities. |
| D:99 | “after the coordinator's final verified completion.” | Runtime completion before tracker notification is an integration ordering assertion, not parser coverage. |
| D:102 | “Rate-limit repeated console errors; retain structured events.” | Complete structured failure evidence and rate-limited console output must be reconciled, not treated as equivalent. |
| G:311 | “The prefix counts encoded bytes, not characters.” | Literal non-ASCII golden wire tests must not derive their expected headers from project encoders. Runtime byte observers do not replace this oracle. |
| G:431 | “Choked neighbors may still count toward replication” | Rarity knowledge and eligible source selection are different facts; original P language cannot be used to exclude choked advertisements globally. |
| G:567 | “Never mix those timing definitions.” | Readiness barrier or first-launch fallback must be declared consistently for all measured runs. Historical pre-tracker origin is not automatically equivalent. |
| G:881 | “A late REJECT cannot release a replacement request with a different ID.” | Requires exact stale-key regression; instrumentation of requests is only support. |
| G:887 | “Do not permanently blacklist an entire swarm because of one failure.” | Corruption classification, bounded source avoidance and healthy-provider opportunity require separate actual policy tests. |

## Follow-up boundaries that must remain distinct

- Part2:27 says “explicitly authorized duplicate requests”; Part2:37 defaults
  `max_copies=2`; Part2:51 permits copies1–2. The integrated runtime's no-endgame,
  single-copy behavior does not supersede the standalone pipeline contract.
  Part2:91 says repeated confirmations do not extend deadlines; Part2:95 says
  “Always match all three key fields.” Preserve exact stale-key tests.
- Part3:72 defaults `endgame_enabled=True`; Part3:80 says these are local
  defaults with no configuration imports. Part3:88 requires retry2,4,10 for its
  retryable reasons. Do not globally change defaults to match the integrated
  runtime profile.
- Part4:17 permits piece lengths1–4194304 and1–4096 entries, and normalizes
  hashes. Part4:25 limits its manifest to1MiB and rejects unknown fields.
  Those rules do not silently redefine the original metadata JSON schema.
  Part4:56 requires public owner-thread access; Part4:78 states read/output
  reservations overlap, so their sum is not measured allocated payload RAM.
  Part4:90 explicitly calls demo acknowledgements “simulated delivery”; the
  65536-byte demo counter is not a real network transfer result.
- Part5:30 requires caller-supplied nondecreasing time with no wall clock or
  sleeps. Part5:90 retains overdue permission reservations and original tokens;
  a timeout cannot fabricate denial/success. Part5:104 gives operation-specific
  success schemas: tick/snapshot/ack responses are not required to contain the
  `ok:true` field used by other successes.

## Static mapping and outstanding work

The authored mapping files identify every parameter explicitly, split unit
from live-HTTP and composition procedures, and mark all results NOT RUN:

- `tests/acceptance/case_mapping_storage_discovery_common.json`: 86 expected
  cases for metadata/store boundaries, tracker HTTP/parser/retry and logging.
- `tests/acceptance/case_mapping_runtime_telemetry.json`: 38 expected cases;
  fake sockets and fake OS metrics provide no live-network/process credit.
- `tests/acceptance/case_mapping_e2e_support.json`: 22 expected helper-unit
  cases; no children, sockets or acceptance challenge are generated by tests.

Remaining gaps include metadata duplicate/extra-key policy review; documented
explicit-destination overwrite policy; direct wire literal/non-ASCII oracles;
hostile HTTP response Content-Length/stall/reset cases; live listener/announce
ordering and source I/O faults; alternate transfer-store/legacy package branch
coverage; alias/symlink/junction/hardlink/reserved-name portability; real
resource peaks; multi-host/source-access-denial evidence; complete27-run matrix;
and independent challenge, evidence audit and genuine human demonstrations.
No one should infer that an existing broad test closes every enumerated clause.

`docs/anik/protocol_spec.md` is a preserved old draft describing binary-packed
messages, nonframed handshake, bit-packed bitfield and keepalives. Its behavior
differs from the current JSON header framing. Preserve the draft and authorship,
and explicitly identify the canonical current specification in integration
documentation for EV07. Do not quietly rewrite the historical protocol draft.
