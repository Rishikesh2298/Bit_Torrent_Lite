# College submission handoff — 22 October 2026

The current working repository is ready for a local college-project demonstration
and review before GitHub upload. It retains the member-owned `BitTorrent/bittorrent_lite`
layout, all five original plans and the standalone implementations. Start with
[COLLEGE-SUBMISSION.md](../../../COLLEGE-SUBMISSION.md).

The user explicitly reduced the task to practical submission readiness, stopped
intensive testing, requested no ZIP, and requested no upload. No files were
staged, committed, pushed or merged during this handoff. Existing uncommitted
reorganization changes remain in place; an older remote commit does not contain
these working files.

## Verified results

Windows, Python 3.12.14, real localhost TCP/HTTP. Tests used strict warnings,
stopped on unexpected failure, and retained stdout/stderr, JUnit and test-identity
ledgers. Collected identities matched the executed results with no skips or
xfails in the listed groups. Counts below overlap as explicitly indicated.

| Check | Result | Evidence |
|---|---|---|
| Experiment reporting repairs | 30 passed; included in the 788 below | [JUnit](evidence/college-2026-10-22/077-junit.xml), [console](evidence/college-2026-10-22/077-stdout.txt) |
| Common, storage, discovery, networking, scheduling and integration | 788 passed | [JUnit](evidence/college-2026-10-22/078-junit.xml), [console](evidence/college-2026-10-22/078-stdout.txt) |
| Real project/network demonstrations | 9 passed | [JUnit](evidence/college-2026-10-22/079-junit.xml), [console](evidence/college-2026-10-22/079-stdout.txt) |
| Earlier same-session live fault checks | 6 passed, reported separately | [JUnit](evidence/college-2026-10-22/076-junit.xml), [console](evidence/college-2026-10-22/076-stdout.txt) |
| Relocated source, fresh installed package and isolated real transfers | 3 transfers passed at 1, 65,536 and 524,411 bytes | [Install/transfer record](evidence/college-2026-10-22/081-portable-install.json) |

The final regression therefore covers **797 distinct pytest cases**, plus three
installed-package transfers. This is the selected submission scope, not a claim
that every acceptance-helper or extended end-to-end case was rerun. No overall
line or branch coverage percentage is claimed.

The nine live checks exercised exact file reconstruction, graceful peer shutdown,
a completed downloader acting as the only source for a late joiner, six concurrent
downloaders with one and two seeders, and real baseline/free-rider/failure harness
runs. The six separate fault checks exercised unavailable final providers, tracker
outage and restart, downloader restart using verified pieces, malformed clients,
tracker absence at startup, and corrupt payload rejection followed by healthy-source
recovery. These are real local network checks, not stand-in simulation results.

The portable check copied the source with byte-for-byte hash verification into a
new folder containing spaces and a non-ASCII character, built and installed it into
a fresh environment, and checked that isolated imports came from that installation.
All three installed downloads matched the original bytes/hash and byte counters.
Dependency checking, help commands and owned-process cleanup passed. Production
code, tests and configuration bytes were unchanged between the final regression
and handoff verification.

## Comparison with the original plans

| Original plan | Functional coverage in this handoff | Remaining limits |
|---|---|---|
| Rishikesh — file and metadata | Splitting, SHA-256 piece validation, metadata validation, storage/reconstruction and resume tests; actual exact output comparisons | Maximum-size/live boundary cases outside this final selected rerun retain earlier evidence only |
| Debargha — tracker and discovery | Tracker/client tests, real discovery, outage/restart, real experiment launcher and collector checks | The nine-configuration, three-repeat measured study and resulting figures are not completed |
| Anik — networking | Framing, handshake, TCP lifecycle, messages, malformed input and real payload/corruption tests | Other operating systems and actual LAN devices remain untested |
| Prabhat — scheduling and concurrency | Selection strategies, request windows, retry/cancel, upload/choking, standalone modules and integrations; six-downloader live swarms | No new prolonged stress or exhaustive scheduling exploration |
| Revised project guide — integrated project | Real end-to-end file delivery, redistribution, multiple seeders, free rider, failure handling, portable setup and ownership documentation | Team presentation/report signoff, external-device demo and the complete measured study are not represented as done |

All five original plan files match their preserved SHA-256 values. The
[machine-readable summary](evidence/college-2026-10-22/summary.json) records those
hashes, evidence-file hashes, command-record references and exact counts.

## Repairs and preserved diagnostic history

The final experiment repairs make missing/wrong outputs and unsuccessful ordinary
peer exits fail a run, reject stale/completed failure targets, stop a matrix on an
unsuccessful run, use first-peer launch timing, and derive metrics from the actual
wire/verification events. Killed peers retain explicitly labelled observed prefixes;
their unknown final counters are not invented. Free-rider plots compare the same
peer populations with one observation per repeat. Focused regressions and the real
launcher checks passed after these changes.

Earlier preparation repaired validation, framing/logging and path handling as
documented in the retained preparation records. In particular, the installed-output
verifier was corrected to use the metadata-hash piece directory, and the coverage
helper now copies startup arguments before Python can mutate them. These were test
tool repairs; their first failed records remain available locally.

The first final portable check completed installation and transfers but exposed a
pip console encoding error for the non-ASCII path. Its logs remain under local
record 080. The helper and Windows setup instructions now use explicit UTF-8;
fresh record 081 repeated installation and the three transfers without that error.

Full command records, process logs, failures and source snapshots remain under
`.validation/college-readiness-20261022/` and
`.validation/final-acceptance/preparation-20261022-01/`. These bulky local records
are Git-ignored; the compact evidence linked above is included with the source.
No formal acceptance attempt was opened, so no completed full-campaign restart is
claimed. The reduced user scope superseded that campaign before this handoff.

## Handoff boundaries

There is no known failing case in the selected final checks. This is not a guarantee
for an unknown professor's machine: Python 3.10+ is declared, Python 3.12.14 on
Windows was tested, and macOS/Linux/LAN instructions are supplied without claiming
those environments were executed. Recreate the virtual environment after moving
the source folder. The core application has no external runtime dependencies.

The full 27-run study, extended stress campaign, external challenge/seals and
independent reviewer verification were not performed for this reduced handoff.
Output hashes were checked locally by the test tools; no independent human approval
is claimed. Original authorship, standalone modules, documents and Git history were
preserved. [AI-USE.md](../../../AI-USE.md) describes the assistance; team review and
the actual presentation remain the team's responsibility.
